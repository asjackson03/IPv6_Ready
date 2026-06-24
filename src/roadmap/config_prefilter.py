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
]

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
        """Reduce ``raw_config`` a las líneas relevantes.

        Reglas (en orden): se descartan líneas vacías y líneas que sean
        puramente un comentario (según el carácter de la familia); se conservan
        las que contengan alguna palabra clave de :data:`RELEVANT_KEYWORDS`
        (sin distinguir mayúsculas) o cualquier dirección IPv4/IPv6.

        Args:
            raw_config: texto pegado por el administrador.
            vendor: familia del equipo (para conocer el carácter de comentario).

        Returns:
            El texto filtrado (solo líneas relevantes), unido por saltos de línea.
        """
        comment_char = self._guide.get_comment_pattern(vendor)
        kept: list[str] = []

        for line in raw_config.splitlines():
            stripped = line.strip()

            # Línea vacía: descartar.
            if not stripped:
                continue

            # Comentario puro (empieza con el carácter de comentario): descartar.
            if comment_char and stripped.startswith(comment_char):
                continue

            lowered = stripped.lower()
            if any(keyword in lowered for keyword in RELEVANT_KEYWORDS):
                kept.append(line)
                continue

            # Sin keyword, pero contiene una dirección IP: conservar igual.
            if IPV4_RE.search(stripped) or IPV6_RE.search(stripped):
                kept.append(line)

        return "\n".join(kept)

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
