"""topology_session.py — Flujo conversacional de levantamiento (Módulo 3a).

Contiene :class:`TopologySession`, que orquesta en la terminal el
levantamiento de los equipos de capa 3 de la red de un cliente: pregunta el
perfil (cliente final / ISP) y la cantidad de sedes, guía al administrador
sobre qué comando ejecutar en cada equipo (vía :class:`CommandGuide`), recibe
el output pegado, lo reduce de forma determinista (:class:`ConfigPrefilter`)
y lo estructura con el LLM local (:class:`OllamaClient`).

Este módulo se enfoca exclusivamente en identificar y estructurar los equipos
de capa 3 (firewall o switch core que enrute) y, cuando la capa 3 la cumple un
switch core, también el firewall complementario de la sede. El contexto
perimetral (cómo se conecta el firewall al ISP, dispositivos intermedios) se
capturará en el Módulo 3b, todavía no implementado.

Es un modo de CLI completamente separado del flujo de discovery/clasificación:
se invoca con ``python main.py --topology`` y captura información que NO es
descubrible por escaneo de red (rol lógico real, etc.).
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from colorama import Fore, Style, init as colorama_init
from tabulate import tabulate

from src.roadmap.command_guide import CommandGuide, VENDOR_COMMANDS
from src.roadmap.config_prefilter import ConfigPrefilter
from src.roadmap.ollama_client import OllamaClient

colorama_init(autoreset=True)

# Carpeta donde se guardan los levantamientos.
OUTPUT_DIR = "data/processed"


class TopologySession:
    """Orquesta el levantamiento conversacional de topología en CLI."""

    def __init__(self):
        self.dispositivos: list[dict] = []
        self.sesion_info: dict = {}
        self.guide = CommandGuide()
        self.prefilter = ConfigPrefilter()
        self.ollama = OllamaClient()

    # ------------------------------------------------------------------ #
    #  Flujo principal
    # ------------------------------------------------------------------ #
    def run_interactive(self) -> dict:
        """Ejecuta el levantamiento completo en la terminal.

        Returns:
            La estructura consolidada del levantamiento (también persistida
            en disco).
        """
        self._titulo("LEVANTAMIENTO DE TOPOLOGÍA — Módulo 3a")
        print("Este asistente te guiará para levantar la información de los "
              "equipos de capa 3 de la red.\n")
        self._aviso_alcance()

        self._capturar_perfil()

        while True:
            self._capturar_dispositivo()
            if not self._si_no("¿Quieres agregar información de otro equipo con "
                               "función de capa 3 (por ejemplo, de otra sede)?"):
                break

        resultado = self._consolidar()
        ruta = self._guardar(resultado)
        self._resumen_final(resultado, ruta)
        return resultado

    def _aviso_alcance(self) -> None:
        """Aclara el alcance del levantamiento antes de la primera pregunta."""
        print(f"{Fore.YELLOW}{'─' * 60}")
        print(f"{Style.BRIGHT}Alcance de este levantamiento:{Style.RESET_ALL}")
        print(
            f"{Fore.YELLOW}"
            "Este levantamiento se enfoca en los equipos que cumplen la\n"
            "función de capa 3 (enrutamiento) de la red: el firewall cuando\n"
            "también enruta, o el switch core cuando la capa 3 está separada\n"
            "de la seguridad. Los switches puramente de capa 2 (sin\n"
            "enrutamiento) NO se levantan aquí.\n"
            "Por cada equipo se solicitará la marca, el comando de verificación\n"
            "a ejecutar y su salida, que será procesada por una IA local. Se\n"
            "levanta un equipo a la vez; al terminar se podrá agregar otro\n"
            "(por ejemplo, de otra sede)."
            f"{Style.RESET_ALL}"
        )
        print(f"{Fore.YELLOW}{'─' * 60}{Style.RESET_ALL}\n")

    # ------------------------------------------------------------------ #
    #  Etapas
    # ------------------------------------------------------------------ #
    def _capturar_perfil(self) -> None:
        """Pregunta perfil de cliente y cantidad de sedes (no descubribles)."""
        self._subtitulo("Perfil del cliente")
        print(f"{Fore.CYAN}El perfil ayuda a interpretar la topología: un ISP "
              f"y un cliente final tienen necesidades de capa 3 "
              f"distintas.{Style.RESET_ALL}")
        opcion = self._preguntar("Indica si es un cliente final o un ISP "
                                 "[1=cliente final / 2=ISP]").strip()
        tipo_cliente = "isp" if opcion == "2" else "cliente_final"

        print(f"{Fore.CYAN}La cantidad de sedes da una idea de cuántos equipos "
              f"de capa 3 podrían tener que levantarse.{Style.RESET_ALL}")
        cantidad_sedes = self._preguntar_entero_positivo(
            "Indica cuántas sedes tiene la organización"
        )

        self.sesion_info = {
            "tipo_cliente": tipo_cliente,
            "cantidad_sedes": cantidad_sedes,
            "timestamp_inicio": datetime.now().isoformat(timespec="seconds"),
        }

    def _capturar_dispositivo(self) -> None:
        """Captura uno o más equipos según quién cumpla la función de capa 3.

        Pregunta primero qué equipo enruta en esta sede/segmento y deriva el
        flujo: si el firewall es quien enruta, se levanta solo ese equipo; si
        la capa 3 la cumple un switch core, se levanta el switch y, de forma
        obligatoria, también el firewall complementario de la sede.
        """
        self._subtitulo(f"Equipo de capa 3 #{len(self.dispositivos) + 1}")
        print(f"{Fore.CYAN}Por favor indica cuál equipo hace las funciones de "
              f"capa 3 de la red en esta sede o segmento; posteriormente, en "
              f"otra línea de comando, se solicitará la marca y los comandos "
              f"de verificación, que serán procesados por una IA "
              f"local.{Style.RESET_ALL}")

        opcion = self._preguntar_opcion(
            "¿Qué equipo maneja las funciones de capa 3 en esta sede/segmento?\n"
            "  [1] Firewall (también es responsable de capa 3)\n"
            "  [2] Switch core (capa 3 separada de la seguridad)\n"
            "  [3] Otro equipo",
            {"1", "2", "3"},
        )

        if opcion == "1":
            self._caso_firewall_hace_capa3()
        elif opcion == "2":
            self._caso_switch_core_y_firewall()
        else:
            self._caso_otro_equipo()

    def _caso_firewall_hace_capa3(self) -> None:
        """Caso 1: el firewall enruta y cubre la seguridad — un solo equipo."""
        print(f"{Fore.CYAN}Se levantará el firewall, que en este caso también "
              f"cumple la función de capa 3 de la red.{Style.RESET_ALL}")
        entrada = self._preguntar("Indica la marca/modelo del firewall")
        info = self._procesar_equipo(entrada, preguntar_rol_fallback=False)
        self.dispositivos.append(info)

    def _caso_switch_core_y_firewall(self) -> None:
        """Caso 2: el switch core enruta; el firewall se levanta aparte.

        Es obligatorio levantar también el firewall: aunque no enrute, tiene
        interfaces relevantes (ej. zonas DMZ con servidores) que importan para
        entender la topología completa de la sede.
        """
        print(f"{Fore.CYAN}Primero se levantará el switch core, que es quien "
              f"cumple la función de capa 3 de la red.{Style.RESET_ALL}")
        entrada_switch = self._preguntar("Indica la marca/modelo del switch core")
        info_switch = self._procesar_equipo(entrada_switch,
                                            preguntar_rol_fallback=False)
        self.dispositivos.append(info_switch)

        self._subtitulo("Firewall complementario de la sede")
        print(f"{Fore.CYAN}Dado que la función de capa 3 la cumple el switch "
              f"core que se acaba de levantar, ahora se levantará la "
              f"información del firewall de la organización. Aunque no haga "
              f"enrutamiento dinámico, sí tiene interfaces configuradas "
              f"relevantes (por ejemplo, zonas DMZ con servidores) que es "
              f"importante estructurar para entender la topología "
              f"completa.{Style.RESET_ALL}")
        entrada_fw = self._preguntar("Indica la marca/modelo del firewall")
        info_fw = self._procesar_equipo(entrada_fw, preguntar_rol_fallback=False)
        info_fw = self._forzar_rol_firewall_complementario(info_fw)
        info_fw["_es_firewall_sin_capa3"] = True
        self.dispositivos.append(info_fw)

    @staticmethod
    def _forzar_rol_firewall_complementario(info: dict) -> dict:
        """Fuerza rol_logico del firewall complementario por contexto del flujo.

        El rol lógico del firewall complementario se determina por el
        contexto del flujo (no tiene capa 3 por definición, ya que esa
        función la cumple el switch core procesado en este mismo caso), no
        por la inferencia del modelo, que puede confundir la presencia de
        interfaces con IP como evidencia de enrutamiento dinámico aunque no
        exista ningún protocolo de enrutamiento real configurado.
        """
        politicas = info.get("politicas") or {}
        total_politicas = politicas.get("cantidad_total_declaradas") or 0
        info["rol_logico"] = (
            "seguridad_solo" if total_politicas > 0 else "desconocido"
        )
        return info

    def _caso_otro_equipo(self) -> None:
        """Caso 3: otro tipo de equipo de capa 3 — flujo estándar."""
        print(f"{Fore.CYAN}Indica de qué tipo de equipo se trata para registrar "
              f"el contexto antes de pedir su marca y comando.{Style.RESET_ALL}")
        descripcion = self._preguntar(
            "Describe qué tipo de equipo es (texto libre)"
        ).strip()
        entrada = self._preguntar("Indica la marca/modelo del equipo")
        info = self._procesar_equipo(entrada, preguntar_rol_fallback=True)
        info["_descripcion_otro"] = descripcion
        self.dispositivos.append(info)

    def _procesar_equipo(self, entrada: str,
                         preguntar_rol_fallback: bool) -> dict:
        """Procesa un equipo: comando → captura → prefiltrado → LLM → resumen.

        Args:
            entrada: marca/modelo declarado por el administrador.
            preguntar_rol_fallback: si ``True`` y el LLM no determina el rol
                lógico, pregunta al administrador si el equipo también hace de
                firewall. Se usa solo cuando el rol no se conoce de antemano
                (Caso 3); en los casos 1 y 2 el rol ya quedó definido por la
                selección inicial.

        Returns:
            El dict de información del equipo (sin agregar a ``self.dispositivos``).
        """
        vendor_key = self._match_vendor(entrada)
        print(f"{Fore.CYAN}Familia detectada:{Style.RESET_ALL} {vendor_key}")

        # (a) Comando sugerido, destacado.
        sugerencia = self.guide.get_command_suggestion(vendor_key)
        self._mostrar_comando(sugerencia)

        # (b) Captura multilínea hasta una línea que diga exactamente "FIN".
        print(f"{Style.BRIGHT}Pega aquí el resultado del comando "
              f"(termina con una línea que solo diga FIN):{Style.RESET_ALL}")
        print(f"{Style.DIM}Si no tienes esta información disponible ahora, o "
              f"este equipo no aplica (ej: resultó ser de capa 2 sin "
              f"componente de capa 3), escribe una breve nota explicando la "
              f"situación y luego FIN — el sistema lo marcará para revisión "
              f"manual en vez de inventar datos.{Style.RESET_ALL}")
        raw_config = self._leer_multilinea()

        # (c) Pre-filtrado determinista + resumen de reducción.
        filtrado = self.prefilter.prefilter(raw_config, vendor_key)
        reduccion = self.prefilter.estimate_reduction(raw_config, filtrado)
        print(f"\n{Fore.CYAN}Pre-filtrado:{Style.RESET_ALL} "
              f"{reduccion['lineas_originales']} líneas → "
              f"{reduccion['lineas_filtradas']} líneas "
              f"({reduccion['porcentaje_reduccion']}% de reducción)")

        # (d) Extracción con el LLM local (puede tardar 1-2 minutos).
        print(f"\n{Fore.YELLOW}Procesando con el modelo local... "
              f"(esto puede tardar uno o dos minutos){Style.RESET_ALL}")
        info = self.ollama.extract_device_info(
            filtrado, vendor_key, vendor_modelo_declarado=entrada
        )

        # (e) Resumen legible del resultado.
        self._mostrar_resumen_dispositivo(info)

        # (f) Relación de rol firewall si el LLM no la dejó clara (solo Caso 3).
        if preguntar_rol_fallback and (
            not info.get("rol_logico") or info.get("rol_logico") == "desconocido"
        ):
            print(f"{Fore.YELLOW}El análisis automático no pudo determinar con "
                  f"certeza si este equipo cumple función de firewall a "
                  f"partir de la configuración proporcionada — esta respuesta "
                  f"ayuda a completar esa información.{Style.RESET_ALL}")
            resp = self._preguntar(
                "¿Este mismo equipo también maneja la seguridad (firewall), o "
                "es un dispositivo separado? [mismo/separado]"
            ).strip().lower()
            info["rol_logico"] = (
                "capa3_y_seguridad" if resp.startswith("mismo") else "capa3_solo"
            )

        info["_vendor_declarado"] = vendor_key
        info["_entrada_usuario"] = entrada
        return info

    # ------------------------------------------------------------------ #
    #  Consolidación / salida
    # ------------------------------------------------------------------ #
    def _consolidar(self) -> dict:
        """Arma la estructura final del levantamiento."""
        return {
            "sesion_levantamiento": {
                **self.sesion_info,
                "timestamp_fin": datetime.now().isoformat(timespec="seconds"),
                "total_dispositivos": len(self.dispositivos),
            },
            "dispositivos": self.dispositivos,
        }

    def _guardar(self, resultado: dict) -> str:
        """Persiste el levantamiento en data/processed/."""
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(OUTPUT_DIR, f"topology_session_{timestamp}.json")
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(resultado, fh, indent=2, ensure_ascii=False)
        return ruta

    def _resumen_final(self, resultado: dict, ruta: str) -> None:
        """Imprime el resumen ejecutivo del levantamiento."""
        self._titulo("RESUMEN DEL LEVANTAMIENTO")

        dispositivos = resultado["dispositivos"]
        total = len(dispositivos)
        cantidad_sedes = resultado["sesion_levantamiento"].get("cantidad_sedes")

        # VLANs totales detectadas (unión de todas las declaradas).
        vlans: set = set()
        for d in dispositivos:
            for v in (d.get("vlans_detectadas") or []):
                vlans.add(v)

        # Dispositivos con baja confianza (requieren revisión manual).
        baja_confianza = [
            d for d in dispositivos
            if d.get("confianza_extraccion") == "baja"
        ]

        if cantidad_sedes is not None:
            print(f"{Style.BRIGHT}Sedes de la organización:{Style.RESET_ALL} "
                  f"{cantidad_sedes}")
        print(f"{Style.BRIGHT}Equipos levantados:{Style.RESET_ALL} {total}")
        print(f"{Style.BRIGHT}VLANs totales detectadas:{Style.RESET_ALL} "
              f"{len(vlans)} {sorted(vlans) if vlans else ''}")
        print(f"{Style.BRIGHT}Requieren revisión manual "
              f"(confianza baja):{Style.RESET_ALL} {len(baja_confianza)}")
        if baja_confianza:
            print(f"{Style.DIM}Estos dispositivos necesitan que confirmes "
                  f"manualmente la información en una fase posterior, ya que "
                  f"el análisis automático no tuvo suficiente "
                  f"certeza.{Style.RESET_ALL}")

        # Listado de equipos: el firewall complementario se muestra agrupado
        # (indentado) bajo el switch core que lo precede en la lista.
        self._subtitulo("Equipos levantados")
        for d in dispositivos:
            etiqueta = d.get("_entrada_usuario", "?")
            rol = d.get("rol_logico", "—")
            if d.get("_es_firewall_sin_capa3"):
                print(f"    └─ Firewall complementario (sin capa 3): "
                      f"{etiqueta} — {rol}")
            else:
                print(f"  • {etiqueta} — {rol}")

        if baja_confianza:
            filas = [
                [
                    d.get("_entrada_usuario", "?"),
                    d.get("_vendor_declarado", "?"),
                    "; ".join(d.get("notas_ambiguedad", []) or [])[:60],
                ]
                for d in baja_confianza
            ]
            print()
            print(tabulate(
                filas,
                headers=["Equipo", "Familia", "Motivo (resumen)"],
                tablefmt="rounded_outline",
            ))

        print(f"\n{Fore.GREEN}Levantamiento guardado en:{Style.RESET_ALL} {ruta}")

    # ------------------------------------------------------------------ #
    #  Utilidades de presentación / entrada
    # ------------------------------------------------------------------ #
    @staticmethod
    def _match_vendor(entrada: str) -> str:
        """Mapea texto libre a una clave conocida de CommandGuide.

        Matching simple case-insensitive por substring contra las claves y
        algunos alias comunes; si nada coincide, devuelve ``"desconocido"``.
        """
        texto = (entrada or "").lower()
        # Alias frecuentes → clave canónica.
        alias = {
            "cisco_ios_xe": ["ios-xe", "ios xe", "iosxe", "catalyst 9", "isr 4"],
            "cisco_ios": ["cisco", "ios", "catalyst"],
            "fortinet": ["forti", "fortigate", "fortios"],
            "paloalto": ["palo alto", "paloalto", "pan-os", "panos"],
            "juniper": ["juniper", "junos", "srx", "mx"],
            "checkpoint": ["check point", "checkpoint", "gaia"],
        }
        for clave, palabras in alias.items():
            if any(p in texto for p in palabras):
                return clave
        # Coincidencia directa con una clave del diccionario.
        for clave in VENDOR_COMMANDS:
            if clave != "desconocido" and clave in texto:
                return clave
        return "desconocido"

    def _mostrar_comando(self, sugerencia: dict) -> None:
        """Muestra el comando sugerido destacado en consola."""
        print()
        print(f"{Fore.GREEN}{'─' * 60}")
        print(f"{Style.DIM}Este comando extrae solo la información relevante "
              f"(no el archivo de configuración completo). El resultado se "
              f"analizará con un modelo de IA que corre localmente en este "
              f"equipo — nada se envía a internet.{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}Ejecuta en el equipo y pega la salida:"
              f"{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{sugerencia['comando_sugerido']}{Style.RESET_ALL}")
        print(f"{Style.DIM}{sugerencia['notas']}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{'─' * 60}{Style.RESET_ALL}\n")

    def _mostrar_resumen_dispositivo(self, info: dict) -> None:
        """Presenta el JSON extraído como resumen legible (no JSON crudo)."""
        confianza = info.get("confianza_extraccion", "desconocida")
        color = {
            "alta": Fore.GREEN, "media": Fore.YELLOW, "baja": Fore.RED
        }.get(confianza, Fore.WHITE)

        interfaces = info.get("interfaces") or []
        enrutamiento = info.get("enrutamiento") or {}
        politicas = info.get("politicas") or {}

        filas = [
            ["Rol lógico", info.get("rol_logico", "—")],
            ["Modelo", info.get("modelo") or "—"],
            ["Versión SO", info.get("version_so") or "—"],
            ["Interfaces detectadas", len(interfaces)],
            ["VLANs", ", ".join(str(v) for v in (info.get("vlans_detectadas") or [])) or "—"],
            ["Protocolos enrutamiento",
             ", ".join(enrutamiento.get("protocolos_detectados") or []) or "—"],
            ["Políticas (total/activas/inactivas)",
             f"{politicas.get('cantidad_total_declaradas', '—')}/"
             f"{politicas.get('cantidad_activas', '—')}/"
             f"{politicas.get('cantidad_inactivas_o_deshabilitadas', '—')}"],
            ["IPv6 configurado", info.get("ipv6_configurado_en_algo", "—")],
            ["Confianza extracción", f"{color}{confianza}{Style.RESET_ALL}"],
        ]
        print()
        print(tabulate(filas, headers=["Campo", "Valor"],
                       tablefmt="rounded_outline"))

        notas = info.get("notas_ambiguedad") or []
        if notas:
            print(f"{Fore.YELLOW}Notas de ambigüedad:{Style.RESET_ALL}")
            for n in notas:
                print(f"  • {n}")

    @staticmethod
    def _leer_multilinea() -> str:
        """Lee líneas de stdin hasta una línea que sea exactamente 'FIN'."""
        lineas: list[str] = []
        while True:
            try:
                linea = input()
            except EOFError:
                break
            if linea.strip() == "FIN":
                break
            lineas.append(linea)
        return "\n".join(lineas)

    @staticmethod
    def _preguntar(texto: str) -> str:
        """Pregunta de texto libre."""
        return input(f"{Style.BRIGHT}{texto}{Style.RESET_ALL} ")

    def _si_no(self, texto: str) -> bool:
        """Pregunta sí/no; devuelve True si la respuesta empieza por 's'."""
        return self._preguntar(f"{texto} [s/n]").strip().lower().startswith("s")

    def _preguntar_entero_positivo(self, texto: str) -> int:
        """Pregunta un entero positivo; reintenta si la entrada no es válida."""
        while True:
            respuesta = self._preguntar(texto).strip()
            try:
                valor = int(respuesta)
            except ValueError:
                print(f"{Fore.RED}Por favor ingresa un número entero "
                      f"(ej: 1, 2, 3).{Style.RESET_ALL}")
                continue
            if valor <= 0:
                print(f"{Fore.RED}El número debe ser mayor que cero. Intenta "
                      f"de nuevo.{Style.RESET_ALL}")
                continue
            return valor

    def _preguntar_opcion(self, texto: str, validas: set[str]) -> str:
        """Pregunta una opción; reintenta hasta recibir un valor permitido."""
        opciones = "/".join(sorted(validas))
        while True:
            respuesta = self._preguntar(texto).strip()
            if respuesta in validas:
                return respuesta
            print(f"{Fore.RED}Respuesta no válida. Indica una de estas "
                  f"opciones: {opciones}.{Style.RESET_ALL}")

    @staticmethod
    def _titulo(texto: str) -> None:
        print()
        print(f"{Style.BRIGHT}{'=' * 60}")
        print(f"{Style.BRIGHT}  {texto}")
        print(f"{Style.BRIGHT}{'=' * 60}{Style.RESET_ALL}")

    @staticmethod
    def _subtitulo(texto: str) -> None:
        print()
        print(f"{Style.BRIGHT}{Fore.CYAN}── {texto} ──{Style.RESET_ALL}")
