"""config_prefilter.py — Reducción determinista del texto de configuración.

Contiene :class:`ConfigPrefilter`, que recorta un volcado de configuración a
solo las líneas relevantes (interfaces, direcciones, enrutamiento, políticas,
versión/modelo) ANTES de enviarlo al LLM. Es 100% determinista (patrones de
texto, sin LLM): así se reduce el ruido, el tiempo de inferencia y el riesgo
de que el modelo alucine sobre líneas irrelevantes.

El criterio de "qué se conserva" es explícito y ampliable (ver
:data:`RELEVANT_KEYWORDS`), porque la transparencia del filtrado es un
requisito del proyecto: cualquiera debe poder auditar por qué una línea entró
o no entró al prompt.
"""
from __future__ import annotations

import re

from src.roadmap.command_guide import CommandGuide

# Palabras clave que marcan una línea como relevante para la topología y la
# compatibilidad IPv6. Lista deliberadamente amplia y ampliable: ante la duda
# se conserva la línea (es preferible algo de ruido a perder un dato de capa 3).
RELEVANT_KEYWORDS = [
    "interface", "ip address", "ipv6", "router", "bgp", "ospf", "route",
    "vlan", "dhcp", "policy", "license", "version", "hostname", "model",
    # Señales de reglas de firewall / políticas. Existen en la sintaxis de
    # varios vendors (no solo FortiOS): sirven para que una línea interna de
    # un bloque de políticas marque como relevante a TODO el bloque padre.
    "action",    # "set action accept/deny" (FortiOS), acción de la regla
    "srcintf",   # interfaz origen de una política (FortiOS)
    "dstintf",   # interfaz destino de una política (FortiOS)
    "srcaddr",   # objeto/dirección origen de una política (FortiOS)
    "dstaddr",   # objeto/dirección destino de una política (FortiOS)
    "status",    # "set status enable/disable" — política activa o no
    "schedule",  # ventana horaria de aplicación de la regla
    "permit",    # acción de permitir (ACL Cisco / otros)
    "deny",      # acción de denegar (ACL Cisco / otros)
    "accept",    # acción de aceptar (FortiOS / otros)
]

# Marcadores de bloques EXPLÍCITOS al estilo FortiOS: un bloque se abre con
# "config X" o "edit N" y se cierra con "end" o "next" (pueden anidarse:
# "config ... edit ... next ... end"). Se reconocen por la primera palabra de
# la línea. Otros formatos (Cisco IOS) no usan estos marcadores y se agrupan
# por indentación (ver heurística en prefilter()).
BLOCK_OPEN_MARKERS = ("config", "edit")
BLOCK_CLOSE_MARKERS = ("end", "next")

# Patrón básico de IPv4 (cuatro grupos de dígitos separados por puntos). No
# pretende validar rangos por RFC: solo detectar que la línea contiene algo
# con forma de dirección para no descartarla.
IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")

# Patrón básico de IPv6: al menos dos grupos hexadecimales separados por ':'
# (incluye la forma comprimida '::'). Deliberadamente laxo.
IPV6_RE = re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){1,}[0-9A-Fa-f:]*:[0-9A-Fa-f]{0,4}\b")


class ConfigPrefilter:
    """Filtra un volcado de configuración a sus líneas relevantes."""

    def __init__(self):
        self._guide = CommandGuide()

    def prefilter(self, raw_config: str, vendor: str = "desconocido") -> str:
        """Reduce ``raw_config`` a las líneas relevantes, evaluando POR BLOQUE.

        El filtrado ya no es línea-por-línea aislada: una línea relevante puede
        vivir dentro de un bloque cuyas demás líneas (apertura, cierre, líneas
        estructurales) no tienen keyword propia, y perderlas rompería el bloque.
        La heurística de bloque es deliberadamente simple y se basa en dos
        mecanismos complementarios:

        1. **Bloques EXPLÍCITOS (FortiOS y similares):** un bloque va desde una
           línea de apertura (``config X`` / ``edit N``) hasta su cierre
           (``end`` / ``next``), con anidamiento. Si CUALQUIER línea interna es
           relevante (keyword o IP), se conserva el bloque COMPLETO::

               config firewall policy   <- "policy" hace relevante TODO el bloque
                   edit 1
                       set action accept
                   next
                   edit 2
                       set status disable   <- se conserva (no se pierde)
                   next
               end

        2. **Bloques por INDENTACIÓN (Cisco IOS y similares):** una línea raíz
           no indentada agrupa a las líneas indentadas que cuelgan de ella. Si
           la línea raíz es relevante, se conserva el bloque completo; si no lo
           es, cada línea (raíz e hijas) se evalúa individualmente, igual que el
           comportamiento histórico (retrocompatibilidad con Cisco)::

               interface Vlan10          <- raíz relevante: conserva el bloque
                   ip address 10.0.0.1 255.255.255.0
                   no shutdown

        En todos los casos se descartan líneas vacías y comentarios puros
        (según el carácter de la familia). Las líneas sueltas que no pertenecen
        a ningún bloque se evalúan individualmente como siempre.

        Args:
            raw_config: texto pegado por el administrador.
            vendor: familia del equipo (para conocer el carácter de comentario).

        Returns:
            El texto filtrado (solo bloques/líneas relevantes), unido por
            saltos de línea.
        """
        comment_char = self._guide.get_comment_pattern(vendor)
        lines = raw_config.splitlines()
        kept: list[str] = []
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]
            first = self._first_token(line)
            indent = len(line) - len(line.lstrip())

            # (1) Bloque EXPLÍCITO: "config"/"edit" ... "end"/"next".
            if first in BLOCK_OPEN_MARKERS:
                fin, bloque = self._consume_explicit_block(lines, i)
                if self._block_has_relevant_line(bloque, comment_char):
                    kept.extend(self._emit_block(bloque, comment_char))
                i = fin
                continue

            # (2) Bloque por INDENTACIÓN: línea raíz + líneas indentadas.
            if indent == 0 and line.strip():
                fin = i + 1
                hijas: list[str] = []
                while fin < n:
                    siguiente = lines[fin]
                    sig_indent = len(siguiente) - len(siguiente.lstrip())
                    # Un nuevo abridor explícito no se absorbe como hija.
                    if self._first_token(siguiente) in BLOCK_OPEN_MARKERS:
                        break
                    # Línea vacía o más indentada que la raíz → es hija.
                    if not siguiente.strip() or sig_indent > indent:
                        hijas.append(siguiente)
                        fin += 1
                        continue
                    break

                if self._line_is_relevant(line):
                    # Raíz relevante: conserva raíz + hijas (bloque completo).
                    kept.extend(self._emit_block([line] + hijas, comment_char))
                else:
                    # Raíz no relevante: evalúa cada línea por separado
                    # (idéntico al comportamiento histórico para Cisco).
                    for ln in [line] + hijas:
                        if self._keep_standalone(ln, comment_char):
                            kept.append(ln)
                i = fin
                continue

            # (3) Línea suelta (p. ej. indentada sin raíz previa): individual.
            if self._keep_standalone(line, comment_char):
                kept.append(line)
            i += 1

        return "\n".join(kept)

    # ------------------------------------------------------------------ #
    #  Heurística de bloques (helpers deterministas, sin LLM)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _first_token(line: str) -> str:
        """Primera palabra de la línea en minúsculas ('' si está vacía)."""
        stripped = line.strip()
        return stripped.split()[0].lower() if stripped else ""

    def _consume_explicit_block(self, lines: list[str], start: int) -> tuple:
        """Consume un bloque explícito desde ``start`` contando anidamiento.

        Arranca en una línea de apertura (``config``/``edit``) y avanza hasta
        que el cierre correspondiente (``end``/``next``) devuelve la
        profundidad a cero. Si el bloque queda sin cerrar (config malformada),
        consume hasta el final: es preferible conservar de más que perder datos.

        Returns:
            ``(indice_siguiente, lineas_del_bloque)``.
        """
        depth = 0
        bloque: list[str] = []
        i = start
        n = len(lines)
        while i < n:
            first = self._first_token(lines[i])
            bloque.append(lines[i])
            if first in BLOCK_OPEN_MARKERS:
                depth += 1
            elif first in BLOCK_CLOSE_MARKERS:
                depth -= 1
                if depth <= 0:
                    i += 1
                    break
            i += 1
        return i, bloque

    def _block_has_relevant_line(self, bloque: list[str],
                                 comment_char: str) -> bool:
        """¿Alguna línea NO comentario del bloque es relevante (keyword/IP)?"""
        for ln in bloque:
            stripped = ln.strip()
            if not stripped:
                continue
            if comment_char and stripped.startswith(comment_char):
                continue
            if self._line_is_relevant(ln):
                return True
        return False

    @staticmethod
    def _emit_block(bloque: list[str], comment_char: str) -> list[str]:
        """Devuelve las líneas del bloque a conservar (sin vacías ni comentarios)."""
        out: list[str] = []
        for ln in bloque:
            stripped = ln.strip()
            if not stripped:
                continue
            if comment_char and stripped.startswith(comment_char):
                continue
            out.append(ln)
        return out

    def _keep_standalone(self, line: str, comment_char: str) -> bool:
        """Decide si una línea suelta se conserva (lógica histórica línea-a-línea)."""
        stripped = line.strip()
        if not stripped:
            return False
        if comment_char and stripped.startswith(comment_char):
            return False
        return self._line_is_relevant(line)

    @staticmethod
    def _line_is_relevant(line: str) -> bool:
        """¿La línea contiene una keyword de RELEVANT_KEYWORDS o una IP?"""
        stripped = line.strip()
        if not stripped:
            return False
        lowered = stripped.lower()
        if any(keyword in lowered for keyword in RELEVANT_KEYWORDS):
            return True
        return bool(IPV4_RE.search(stripped) or IPV6_RE.search(stripped))

    def has_meaningful_content(self, text: str, min_length: int = 30) -> bool:
        """Decide si ``text`` tiene evidencia técnica suficiente para analizar.

        Exige dos condiciones a la vez: al menos ``min_length`` caracteres
        no-whitespace, Y al menos una línea con una palabra clave técnica de
        :data:`RELEVANT_KEYWORDS` o una dirección IPv4/IPv6. Reutiliza el
        mismo criterio que :meth:`prefilter` para que "qué cuenta como
        relevante" se defina en un solo lugar.

        Args:
            text: texto a evaluar (típicamente ya pasado por ``prefilter``).
            min_length: mínimo de caracteres no-whitespace exigido.

        Returns:
            ``True`` si hay suficiente evidencia técnica real, ``False`` si no.
        """
        sin_espacios = "".join(text.split())
        if len(sin_espacios) < min_length:
            return False

        for line in text.splitlines():
            lowered = line.lower()
            if any(keyword in lowered for keyword in RELEVANT_KEYWORDS):
                return True
            if IPV4_RE.search(line) or IPV6_RE.search(line):
                return True

        return False

    def estimate_reduction(self, raw_config: str, filtered_config: str) -> dict:
        """Calcula cuánto se redujo el texto tras el filtrado.

        Args:
            raw_config: texto original.
            filtered_config: texto ya filtrado.

        Returns:
            Dict con ``lineas_originales``, ``lineas_filtradas`` y
            ``porcentaje_reduccion`` (0.0 si el original estaba vacío).
        """
        originales = len([ln for ln in raw_config.splitlines()])
        filtradas = len([ln for ln in filtered_config.splitlines()]) \
            if filtered_config else 0

        if originales == 0:
            porcentaje = 0.0
        else:
            porcentaje = (1 - filtradas / originales) * 100

        return {
            "lineas_originales": originales,
            "lineas_filtradas": filtradas,
            "porcentaje_reduccion": round(porcentaje, 1),
        }
