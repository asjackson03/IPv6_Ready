"""command_guide.py — Conocimiento estático de comandos por fabricante.

Contiene :class:`CommandGuide`, un diccionario experto DETERMINISTA (sin LLM)
que mapea cada familia de equipos de red al comando que el administrador debe
ejecutar para extraer la configuración relevante (interfaces, rutas, políticas)
y al carácter de comentario que usa esa familia (necesario para el
pre-filtrado posterior en :class:`ConfigPrefilter`).

Se prefiere pedir secciones acotadas de la configuración (no el `show run`
completo) por dos razones: (1) reduce el ruido que llega al LLM y por tanto el
tiempo de inferencia y el riesgo de alucinación, y (2) evita que el
administrador comparta más información sensible de la estrictamente necesaria.
"""
from __future__ import annotations

# Mapa de familia → comandos sugeridos y patrón de comentario.
# Cada entrada documenta POR QUÉ ese comando es el adecuado para la familia.
VENDOR_COMMANDS = {
    # Cisco IOS / IOS-XE: el modificador "| section" filtra por bloque de
    # configuración; pedir interface + router + ipv6 cubre capa 3 y estado IPv6
    # sin volcar todo el running-config. "!" es el carácter de comentario.
    "cisco_ios": {
        "comando_sugerido": (
            "show running-config | section interface\n"
            "show running-config | section router\n"
            "show running-config | include ipv6"
        ),
        "patron_comentario": "!",
        "notas": (
            "Ejecuta los tres comandos y pega su salida combinada. El primero "
            "trae las interfaces y sus IPs, el segundo el enrutamiento "
            "(OSPF/BGP/estáticas) y el tercero confirma si hay IPv6 configurado."
        ),
    },
    "cisco_ios_xe": {
        "comando_sugerido": (
            "show running-config | section interface\n"
            "show running-config | section router\n"
            "show running-config | include ipv6"
        ),
        "patron_comentario": "!",
        "notas": (
            "Idéntico a IOS clásico: IOS-XE conserva la misma sintaxis de "
            "'show running-config | section'. Pega la salida combinada."
        ),
    },
    # FortiOS: la CLI usa 'show' por secciones de configuración. El carácter de
    # comentario en los volcados de FortiOS es '#'.
    "fortinet": {
        "comando_sugerido": (
            "show system interface\n"
            "show router static\n"
            "show firewall policy"
        ),
        "patron_comentario": "#",
        "notas": (
            "En FortiOS cada 'show' devuelve un bloque 'config ... edit ... "
            "next end'. El primero trae interfaces e IPs, el segundo rutas "
            "estáticas y el tercero las políticas (para contar activas vs "
            "deshabilitadas con 'set status disable')."
        ),
    },
    # Palo Alto PAN-OS: la CLI permite 'show config running' acotado por xpath
    # o, más simple para el administrador, el set-format por sección.
    "paloalto": {
        "comando_sugerido": (
            "set cli config-output-format set\n"
            "configure\n"
            "show network interface\n"
            "show network virtual-router\n"
            "show rulebase security"
        ),
        "patron_comentario": "#",
        "notas": (
            "El primer comando cambia la salida a formato 'set' (una línea por "
            "sentencia, fácil de filtrar). Luego se piden interfaces, "
            "virtual-routers (enrutamiento) y reglas de seguridad."
        ),
    },
    # Juniper JunOS: 'show configuration' por jerarquía. El carácter de
    # comentario es '#'. 'display set' aplana la jerarquía a líneas 'set'.
    "juniper": {
        "comando_sugerido": (
            "show configuration interfaces | display set\n"
            "show configuration routing-options | display set\n"
            "show configuration protocols | display set"
        ),
        "patron_comentario": "#",
        "notas": (
            "'| display set' convierte la configuración jerárquica de JunOS en "
            "líneas planas 'set ...', mucho más fáciles de filtrar. Cubre "
            "interfaces, rutas estáticas (routing-options) y protocolos "
            "dinámicos (OSPF/BGP bajo protocols)."
        ),
    },
    # Check Point Gaia: la configuración de red vive en clish (Gaia) y la de
    # seguridad en la SmartConsole; desde clish se obtiene la parte de red.
    "checkpoint": {
        "comando_sugerido": (
            "show configuration\n"
            "show interfaces\n"
            "show route static"
        ),
        "patron_comentario": "#",
        "notas": (
            "Desde clish (Gaia), 'show configuration' vuelca interfaces y "
            "rutas en formato 'set'. La política de seguridad de Check Point se "
            "gestiona aparte (SmartConsole); si necesitas las reglas, "
            "indícalo y se capturan por separado."
        ),
    },
    # Fallback genérico: cuando no se reconoce la familia, se guía al
    # administrador a localizar manualmente las secciones relevantes.
    "desconocido": {
        "comando_sugerido": (
            "Busca en la configuración de tu equipo las secciones de: "
            "interfaces (y sus direcciones IP), tabla de rutas / protocolos de "
            "enrutamiento, y políticas/reglas de firewall. Pega esas secciones "
            "tal cual aparezcan."
        ),
        "patron_comentario": "!",
        "notas": (
            "No se reconoció la marca/modelo. Se asume '!' como posible "
            "carácter de comentario, pero el pre-filtrado se apoya sobre todo "
            "en palabras clave y direcciones IP, así que funciona igual aunque "
            "el equipo use otro carácter."
        ),
    },
}


class CommandGuide:
    """Provee comandos y patrones de comentario por familia de equipo."""

    def get_command_suggestion(self, vendor: str) -> dict:
        """Devuelve la sugerencia de comando para una familia.

        Args:
            vendor: clave de familia (p.ej. ``"cisco_ios"``). Si no se
                reconoce, se devuelve la entrada ``"desconocido"``.

        Returns:
            Dict con ``comando_sugerido``, ``patron_comentario`` y ``notas``.
        """
        key = (vendor or "desconocido").lower()
        return VENDOR_COMMANDS.get(key, VENDOR_COMMANDS["desconocido"])

    def get_comment_pattern(self, vendor: str) -> str:
        """Devuelve el carácter de comentario de la familia (fallback ``!``)."""
        return self.get_command_suggestion(vendor)["patron_comentario"]
