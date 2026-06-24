"""ollama_client.py — Wrapper sobre el LLM local (Ollama) para extracción.

Contiene :class:`OllamaClient`, que envía una configuración ya pre-filtrada al
modelo local y le pide estructurarla en un JSON con un esquema fijo.

Principio de diseño heredado del Módulo 1: NUNCA inventar. Tras el caso real
"Sony Blu-Ray Player" (un falso positivo de fingerprinting con alta accuracy
pero contradictorio), el Módulo 1 incorporó ``os_detection_method`` para ser
honesto sobre la confianza del dato. Aquí se aplica el mismo criterio: se
instruye explícitamente al modelo a usar ``null``/listas vacías cuando un dato
no aparece, y a declarar baja ``confianza_extraccion`` en vez de rellenar
huecos con invenciones. La extracción honesta-pero-incompleta es preferible a
la completa-pero-alucinada en un diagnóstico técnico auditable.
"""
from __future__ import annotations

import json
import re

import httpx
import ollama

from src.roadmap.config_prefilter import ConfigPrefilter

# Esquema exacto que debe devolver el modelo. Se incluye literal en el prompt.
JSON_SCHEMA = """{
  "rol_logico": "capa3_y_seguridad|capa3_solo|seguridad_solo|capa2_solo|desconocido",
  "modelo": "string o null si no se detecta",
  "version_so": "string o null",
  "licencias_adicionales": {"detectadas": bool, "notas": "string"},
  "interfaces": [{"nombre": "string", "ip_v4": "string o null", "ip_v6": "string o null", "vlan_id": "int o null", "estado": "string"}],
  "vlans_detectadas": ["lista de ints"],
  "dhcp": {"es_servidor_dhcp": bool, "tiene_dhcp_relay": bool, "ip_relay_destino": "string o null"},
  "enrutamiento": {"protocolos_detectados": ["lista de strings"], "rutas_estaticas": ["lista de strings"], "bgp_detalle": {"as_number": "string o null", "vecinos": ["lista de strings"]}},
  "politicas": {"cantidad_total_declaradas": "int", "cantidad_activas": "int", "cantidad_inactivas_o_deshabilitadas": "int"},
  "ipv6_configurado_en_algo": bool,
  "confianza_extraccion": "alta|media|baja",
  "notas_ambiguedad": ["lista de strings, explica cualquier dato que no pudiste determinar con certeza"]
}"""

# Excepciones que indican que el servicio Ollama no está accesible (contenedor
# apagado, puerto cerrado, conexión rechazada), a diferencia de una respuesta
# recibida pero mal formada.
CONNECTION_ERRORS = (
    ConnectionError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RequestError,
)


class OllamaClient:
    """Cliente del LLM local para estructurar configuraciones de red."""

    def __init__(
        self,
        model: str = "llama3.1:8b",
        host: str = "http://localhost:11434",
    ):
        self.model = model
        self.host = host
        # ollama.Client no abre conexión en el constructor (es perezoso), así
        # que instanciarlo es seguro aunque el servicio esté apagado.
        self._client = ollama.Client(host=host)
        self._prefilter = ConfigPrefilter()

    def extract_device_info(
        self,
        filtered_config: str,
        vendor_declarado: str,
        vendor_modelo_declarado: str | None = None,
    ) -> dict:
        """Estructura una configuración pre-filtrada en el JSON del esquema.

        Hace hasta dos intentos (el segundo con un prompt más enfático) por si
        el modelo no devuelve JSON válido al primer intento — algo frecuente en
        modelos pequeños. Nunca lanza excepción: ante fallo persistente o
        servicio caído, devuelve un dict de baja confianza con una nota
        accionable.

        Args:
            filtered_config: configuración ya reducida por ConfigPrefilter.
            vendor_declarado: familia/vendor declarado por el administrador
                (usado para elegir el carácter de comentario, etc.).
            vendor_modelo_declarado: texto libre que el administrador escribió
                como marca/modelo del equipo (ej. "cisco nexus 9400"). Se pasa
                como contexto adicional al prompt para rellenar el campo
                "modelo" cuando el texto de configuración no lo menciona
                explícitamente (ej. no hay un "show version" en el recorte).

        Returns:
            Dict con el esquema :data:`JSON_SCHEMA` (o un dict de fallback de
            baja confianza si no se pudo extraer).
        """
        # Guardia determinista: si no hay evidencia técnica real, ni siquiera
        # se llama al modelo. Caso real que motivó esto (sesión --topology):
        # el texto "es capa 2, no tiene componente capa 3" se filtró a 0
        # líneas útiles, pero se envió igual a Ollama, que ALUCINÓ 100 VLANs
        # y protocolos RIP/OSPF con confianza "alta" sin ninguna base real.
        # Es el mismo principio del caso "Sony Blu-Ray Player" del Módulo 1:
        # ante ausencia de datos, declarar explícitamente que no hay datos en
        # vez de dejar que el modelo rellene el vacío con invenciones.
        if not self._prefilter.has_meaningful_content(filtered_config):
            return self._sin_informacion_dict()

        # Primer intento.
        prompt = self._build_prompt(
            filtered_config, vendor_declarado, emphatic=False,
            vendor_modelo_declarado=vendor_modelo_declarado,
        )
        try:
            raw = self._generate(prompt)
        except CONNECTION_ERRORS:
            return self._connection_error_dict()

        parsed = self._try_parse_json(raw)
        if parsed is not None:
            return self._normalizar(parsed)

        # Segundo intento (más enfático en "solo JSON").
        prompt2 = self._build_prompt(
            filtered_config, vendor_declarado, emphatic=True,
            vendor_modelo_declarado=vendor_modelo_declarado,
        )
        try:
            raw2 = self._generate(prompt2)
        except CONNECTION_ERRORS:
            return self._connection_error_dict()

        parsed2 = self._try_parse_json(raw2)
        if parsed2 is not None:
            return self._normalizar(parsed2)

        # Falló dos veces: devolver fallback honesto de baja confianza.
        return self._invalid_json_dict()

    # ------------------------------------------------------------------ #
    #  Internos
    # ------------------------------------------------------------------ #
    def _generate(self, prompt: str) -> str:
        """Llama a Ollama y devuelve el texto de respuesta.

        Usa ``format='json'`` (fuerza salida JSON en el servidor) y temperatura
        baja para minimizar creatividad/alucinación en una tarea de extracción.
        """
        response = self._client.generate(
            model=self.model,
            prompt=prompt,
            format="json",
            stream=False,
            options={"temperature": 0.15},
        )
        return response.get("response", "") if isinstance(response, dict) else ""

    def _build_prompt(
        self,
        filtered_config: str,
        vendor_declarado: str,
        emphatic: bool,
        vendor_modelo_declarado: str | None = None,
    ) -> str:
        """Construye el prompt de extracción."""
        enfasis = ""
        if emphatic:
            enfasis = (
                "\nIMPORTANTE: tu respuesta anterior no fue JSON válido. "
                "Responde EXCLUSIVAMENTE con el objeto JSON, sin ```json, sin "
                "explicaciones, sin texto antes ni después. Empieza con '{' y "
                "termina con '}'.\n"
            )

        contexto_modelo = ""
        if vendor_modelo_declarado:
            contexto_modelo = (
                f"\nEl usuario ha declarado que este equipo es: "
                f"'{vendor_modelo_declarado}'. Usa este dato para el campo "
                f"'modelo' SI no encuentras una declaración más específica de "
                f"modelo/versión dentro del texto de configuración mismo (ej. "
                f"un 'show version' con el modelo exacto tendría prioridad "
                f"sobre lo declarado por el usuario, pero si el texto no lo "
                f"menciona, usa el dato declarado por el usuario en vez de "
                f"dejarlo null).\n"
            )

        return (
            "Eres un asistente experto en redes que extrae información "
            "estructurada de configuraciones de equipos de red. El equipo es de "
            f"la familia/vendor: '{vendor_declarado}'.\n"
            f"{contexto_modelo}\n"
            "Analiza la siguiente configuración y devuelve SOLO un objeto JSON "
            "válido (sin texto adicional antes ni después) con EXACTAMENTE este "
            "esquema y tipos de dato:\n\n"
            f"{JSON_SCHEMA}\n\n"
            "Reglas estrictas:\n"
            "- Si algún dato no aparece claramente en la configuración, usa null "
            "o lista vacía. NUNCA inventes valores.\n"
            "- Si tienes baja confianza en la extracción general, indícalo en "
            "confianza_extraccion='baja' y explica por qué en notas_ambiguedad.\n"
            "- Los campos cantidad_total_declaradas, cantidad_activas y "
            "cantidad_inactivas_o_deshabilitadas DEBEN ser siempre números "
            "enteros (nunca null). Si no encuentras ninguna política de "
            "firewall en el texto, usa 0 en los tres campos, no null.\n"
            "- Para determinar rol_logico, usa ESTRICTAMENTE este criterio:\n"
            "  * Si encuentras evidencia de funciones de firewall (políticas "
            "de acceso/firewall, NAT, reglas de filtrado de tráfico con "
            "source/destination) Y también evidencia de enrutamiento "
            "(interfaces con IP, protocolos de enrutamiento, rutas): usa "
            "'capa3_y_seguridad'.\n"
            "  * Si encuentras SOLO evidencia de enrutamiento sin ninguna "
            "mención de políticas de firewall/NAT/filtrado: usa "
            "'capa3_solo'.\n"
            "  * Si encuentras SOLO funciones de firewall sin enrutamiento "
            "dinámico propio: usa 'seguridad_solo'.\n"
            "  * Si no hay evidencia de ninguna IP ni interfaz ruteada: usa "
            "'capa2_solo' o 'desconocido' según corresponda.\n"
            "  La sola presencia de BGP, OSPF, rutas estáticas, o VLANs NO "
            "implica función de seguridad — eso es enrutamiento puro. No "
            "clasifiques como 'capa3_y_seguridad' únicamente porque el "
            "equipo parece importante o central en la red.\n"
            "- Si el texto proporcionado es insuficiente, ambiguo, o no "
            "contiene suficiente evidencia técnica concreta para alguno de "
            "los campos solicitados, NO inventes valores razonables. En su "
            "lugar, usa null, lista vacía, o 0 según corresponda al tipo de "
            "dato, y reduce confianza_extraccion a 'baja' o 'media' según la "
            "cantidad de evidencia real disponible. Es preferible una "
            "respuesta honesta con baja confianza que una respuesta completa "
            "pero inventada."
            f"{enfasis}\n"
            "Configuración a analizar:\n"
            "-----\n"
            f"{filtered_config}\n"
            "-----\n"
        )

    # rol_logico declarado → rol_logico degradado cuando no hay politicas
    # que lo respalden (ver _corregir_rol_logico_inconsistente).
    _DEGRADACION_SIN_SEGURIDAD = {
        "capa3_y_seguridad": "capa3_solo",
        "seguridad_solo": "desconocido",
    }

    @classmethod
    def _normalizar(cls, parsed: dict) -> dict:
        """Corrige defensivamente el JSON ya parseado antes de retornarlo.

        No basta con instruir al prompt: los modelos pequeños no siguen el
        100% de las reglas. Aplica dos normalizaciones independientes.
        """
        politicas = parsed.get("politicas")
        if isinstance(politicas, dict):
            for campo in (
                "cantidad_total_declaradas",
                "cantidad_activas",
                "cantidad_inactivas_o_deshabilitadas",
            ):
                if politicas.get(campo) is None:
                    politicas[campo] = 0

        cls._corregir_rol_logico_inconsistente(parsed)
        return parsed

    @classmethod
    def _corregir_rol_logico_inconsistente(cls, parsed: dict) -> None:
        """Degrada rol_logico si declara seguridad sin políticas de respaldo.

        Caso real (Nexus 9400, switch/router de core sin firewall): el
        modelo devolvió rol_logico="capa3_y_seguridad" con
        cantidad_total_declaradas=0 — un JSON internamente inconsistente
        (dice "tiene función de seguridad" pero "cero políticas de
        cualquier tipo"). "Seguridad" en este esquema es específicamente
        función de firewall/filtrado, no importancia general del equipo.

        Si rol_logico es 'capa3_y_seguridad' o 'seguridad_solo' pero no hay
        ninguna política declarada, se degrada a la versión sin componente
        de seguridad y se documenta el ajuste en notas_ambiguedad — somos
        transparentes sobre la corrección aplicada, no asumimos en silencio
        que el modelo se equivocó.
        """
        rol = parsed.get("rol_logico")
        nuevo_rol = cls._DEGRADACION_SIN_SEGURIDAD.get(rol)
        if nuevo_rol is None:
            return

        politicas = parsed.get("politicas")
        total_politicas = politicas.get("cantidad_total_declaradas") \
            if isinstance(politicas, dict) else None

        if total_politicas:  # None o 0 → sin respaldo
            return

        parsed["rol_logico"] = nuevo_rol
        notas = parsed.get("notas_ambiguedad")
        if not isinstance(notas, list):
            notas = []
        notas.append(
            "El modelo clasificó este equipo con función de seguridad, "
            "pero no se detectaron políticas de firewall en la "
            "configuración. Se ajustó el rol_logico para reflejar solo la "
            "evidencia de enrutamiento encontrada. Verificar manualmente si "
            "el equipo tiene función de seguridad no reflejada en este "
            "archivo de configuración."
        )
        parsed["notas_ambiguedad"] = notas

    @staticmethod
    def _try_parse_json(raw: str):
        """Intenta extraer y parsear un objeto JSON del texto del modelo.

        Tolera ruido típico de modelos pequeños: fences ```json ... ``` o prosa
        alrededor del objeto. Devuelve el dict o ``None`` si no hay JSON válido.
        """
        if not raw:
            return None

        text = raw.strip()

        # Quita fences de código si los hubiera.
        fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()

        # Recorta al primer '{' y último '}' (descarta prosa alrededor).
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None

        candidate = text[start:end + 1]
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            return None

        return parsed if isinstance(parsed, dict) else None

    def _connection_error_dict(self) -> dict:
        """Dict de fallback cuando el servicio Ollama no está disponible."""
        mensaje = (
            f"Servicio Ollama no disponible en {self.host}. Verifica que el "
            f"contenedor esté corriendo con: docker ps"
        )
        return {
            "error": mensaje,
            "confianza_extraccion": "baja",
            "notas_ambiguedad": [mensaje],
        }

    @staticmethod
    def _sin_informacion_dict() -> dict:
        """Dict determinista cuando el texto no supera el umbral de contenido.

        No pasa por Ollama en absoluto: es una decisión 100% en código Python,
        y además ahorra el tiempo de inferencia para un caso donde ya se sabe
        de antemano que no hay nada que extraer.
        """
        return {
            "rol_logico": "desconocido",
            "modelo": None,
            "version_so": None,
            "licencias_adicionales": {"detectadas": False, "notas": ""},
            "interfaces": [],
            "vlans_detectadas": [],
            "dhcp": {
                "es_servidor_dhcp": False,
                "tiene_dhcp_relay": False,
                "ip_relay_destino": None,
            },
            "enrutamiento": {
                "protocolos_detectados": [],
                "rutas_estaticas": [],
                "bgp_detalle": {"as_number": None, "vecinos": []},
            },
            "politicas": {
                "cantidad_total_declaradas": 0,
                "cantidad_activas": 0,
                "cantidad_inactivas_o_deshabilitadas": 0,
            },
            "ipv6_configurado_en_algo": False,
            "confianza_extraccion": "baja",
            "notas_ambiguedad": [
                "No se proporcionó información de configuración suficiente "
                "para el análisis. El texto recibido no contenía datos "
                "técnicos identificables (interfaces, rutas, IPs, etc.)."
            ],
        }

    @staticmethod
    def _invalid_json_dict() -> dict:
        """Dict de fallback cuando el modelo no produjo JSON válido (2 intentos)."""
        return {
            "confianza_extraccion": "baja",
            "notas_ambiguedad": [
                "El modelo no pudo generar una respuesta JSON válida, se "
                "requiere revisión manual de esta configuración"
            ],
        }
