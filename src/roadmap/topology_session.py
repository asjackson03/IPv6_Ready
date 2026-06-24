"""topology_session.py — Flujo conversacional de levantamiento (Módulo 3a).

Contiene :class:`TopologySession`, que orquesta en la terminal el
levantamiento de la capa 3 y seguridad de la red de un cliente: pregunta el
perfil (cliente final / ISP) y la topología perimetral, guía al administrador
sobre qué comando ejecutar en cada equipo (vía :class:`CommandGuide`), recibe
el output pegado, lo reduce de forma determinista (:class:`ConfigPrefilter`)
y lo estructura con el LLM local (:class:`OllamaClient`).

Es un modo de CLI completamente separado del flujo de discovery/clasificación:
se invoca con ``python main.py --topology`` y captura información que NO es
descubrible por escaneo de red (rol lógico real, relación firewall↔ISP, etc.).
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
        print("Este asistente te guiará para relevar los equipos de capa 3 y "
              "seguridad de la red.\n")
        self._aviso_alcance()

        self._capturar_perfil_y_perimetro()

        while True:
            self._capturar_dispositivo()
            if not self._si_no("¿Quieres agregar otro dispositivo a este "
                               "levantamiento?"):
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
            "Este levantamiento es para relevar equipos con función de capa 3\n"
            "(enrutamiento) y/o seguridad perimetral del cliente (routers,\n"
            "firewalls, equipos con interfaces ruteadas). Si en la topología\n"
            "existen switches puramente de capa 2 (sin enrutamiento), NO es\n"
            "necesario relevarlos individualmente aquí — basta con mencionarlos\n"
            "en la pregunta sobre topología perimetral si son relevantes para\n"
            "entender cómo se conecta el firewall al proveedor de internet."
            f"{Style.RESET_ALL}"
        )
        print(f"{Fore.YELLOW}{'─' * 60}{Style.RESET_ALL}\n")

    # ------------------------------------------------------------------ #
    #  Etapas
    # ------------------------------------------------------------------ #
    def _capturar_perfil_y_perimetro(self) -> None:
        """Pregunta perfil de cliente y topología perimetral (no descubrible)."""
        self._subtitulo("Perfil del cliente")
        opcion = self._preguntar("¿Es un cliente final o un ISP? [1=cliente "
                                 "final / 2=ISP]").strip()
        tipo_cliente = "isp" if opcion == "2" else "cliente_final"

        self._subtitulo("Topología perimetral")
        dispositivo_intermedio = None
        if self._si_no("¿Hay algún dispositivo (IPS u otro) entre el firewall "
                       "y el proveedor de internet?"):
            dispositivo_intermedio = self._preguntar(
                "Indica nombre/tipo del dispositivo intermedio"
            ).strip()

        conexion_isp = self._preguntar(
            "¿Cómo se conecta el firewall al ISP? "
            "(ej: directa, vía router del ISP, etc.)"
        ).strip()

        self.sesion_info = {
            "tipo_cliente": tipo_cliente,
            "dispositivo_intermedio_perimetral": dispositivo_intermedio,
            "conexion_firewall_isp": conexion_isp,
            "timestamp_inicio": datetime.now().isoformat(timespec="seconds"),
        }

    def _capturar_dispositivo(self) -> None:
        """Captura y estructura un equipo de red individual."""
        self._subtitulo(f"Dispositivo #{len(self.dispositivos) + 1}")

        # (a) Marca/modelo → familia conocida.
        entrada = self._preguntar("¿Qué marca/modelo es este equipo de red?")
        vendor_key = self._match_vendor(entrada)
        print(f"{Fore.CYAN}Familia detectada:{Style.RESET_ALL} {vendor_key}")

        # (b) Comando sugerido, destacado.
        sugerencia = self.guide.get_command_suggestion(vendor_key)
        self._mostrar_comando(sugerencia)

        # (c) Captura multilínea hasta una línea que diga exactamente "FIN".
        print(f"{Style.BRIGHT}Pega aquí el resultado del comando "
              f"(termina con una línea que solo diga FIN):{Style.RESET_ALL}")
        raw_config = self._leer_multilinea()

        # (d) Pre-filtrado determinista + resumen de reducción.
        filtrado = self.prefilter.prefilter(raw_config, vendor_key)
        reduccion = self.prefilter.estimate_reduction(raw_config, filtrado)
        print(f"\n{Fore.CYAN}Pre-filtrado:{Style.RESET_ALL} "
              f"{reduccion['lineas_originales']} líneas → "
              f"{reduccion['lineas_filtradas']} líneas "
              f"({reduccion['porcentaje_reduccion']}% de reducción)")

        # (e) Extracción con el LLM local (puede tardar 1-2 minutos).
        print(f"\n{Fore.YELLOW}Procesando con el modelo local... "
              f"(esto puede tardar uno o dos minutos){Style.RESET_ALL}")
        info = self.ollama.extract_device_info(
            filtrado, vendor_key, vendor_modelo_declarado=entrada
        )

        # (f) Resumen legible del resultado.
        self._mostrar_resumen_dispositivo(info)

        # (g) Relación de rol firewall si el LLM no la dejó clara.
        if not info.get("rol_logico") or info.get("rol_logico") == "desconocido":
            resp = self._preguntar(
                "¿Este mismo equipo también maneja la seguridad (firewall), o "
                "es un dispositivo separado? [mismo/separado]"
            ).strip().lower()
            info["rol_logico"] = (
                "capa3_y_seguridad" if resp.startswith("mismo") else "capa3_solo"
            )

        info["_vendor_declarado"] = vendor_key
        info["_entrada_usuario"] = entrada
        self.dispositivos.append(info)

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

        print(f"{Style.BRIGHT}Dispositivos relevados:{Style.RESET_ALL} {total}")
        print(f"{Style.BRIGHT}VLANs totales detectadas:{Style.RESET_ALL} "
              f"{len(vlans)} {sorted(vlans) if vlans else ''}")
        print(f"{Style.BRIGHT}Requieren revisión manual "
              f"(confianza baja):{Style.RESET_ALL} {len(baja_confianza)}")

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
