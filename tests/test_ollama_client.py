"""Pruebas de OllamaClient (Módulo 3a).

Mockean la librería ollama: NO requieren que el servicio/contenedor esté
corriendo. Verifican el parseo de JSON, el reintento ante respuesta inválida
y el manejo de error de conexión.
"""
import json

import pytest

from src.roadmap.ollama_client import OllamaClient

# Configuración filtrada con evidencia técnica real suficiente para superar
# la guardia de has_meaningful_content() (usada en los tests que verifican
# parseo/retry/conexión, no la guardia en sí misma).
CONFIG_CON_EVIDENCIA = (
    "interface GigabitEthernet0/0\n"
    "ip address 10.0.0.1 255.255.255.0\n"
    "router bgp 65001\n"
)

# Respuesta JSON válida de ejemplo (mínima pero conforme al esquema).
VALID_JSON = json.dumps({
    "rol_logico": "capa3_solo",
    "modelo": "ISR 4331",
    "version_so": "17.6.3",
    "licencias_adicionales": {"detectadas": False, "notas": ""},
    "interfaces": [],
    "vlans_detectadas": [10, 20],
    "dhcp": {"es_servidor_dhcp": False, "tiene_dhcp_relay": False,
             "ip_relay_destino": None},
    "enrutamiento": {"protocolos_detectados": ["bgp"], "rutas_estaticas": [],
                     "bgp_detalle": {"as_number": "65001", "vecinos": []}},
    "politicas": {"cantidad_total_declaradas": 0, "cantidad_activas": 0,
                  "cantidad_inactivas_o_deshabilitadas": 0},
    "ipv6_configurado_en_algo": True,
    "confianza_extraccion": "alta",
    "notas_ambiguedad": [],
})


def test_extract_device_info_valid_json(monkeypatch):
    """Una respuesta JSON válida de Ollama se parsea correctamente."""
    client = OllamaClient()
    monkeypatch.setattr(
        client._client, "generate",
        lambda **kwargs: {"response": VALID_JSON},
    )

    result = client.extract_device_info(CONFIG_CON_EVIDENCIA, "cisco_ios")

    assert result["rol_logico"] == "capa3_solo"
    assert result["confianza_extraccion"] == "alta"
    assert result["vlans_detectadas"] == [10, 20]


def test_extract_device_info_invalid_json_retry(monkeypatch):
    """Primera respuesta inválida + segunda válida → el reintento funciona."""
    client = OllamaClient()
    respuestas = [
        {"response": "Claro, aquí tienes la información: no es JSON"},
        {"response": VALID_JSON},
    ]

    def fake_generate(**kwargs):
        return respuestas.pop(0)

    monkeypatch.setattr(client._client, "generate", fake_generate)

    result = client.extract_device_info(CONFIG_CON_EVIDENCIA, "cisco_ios")

    assert result["rol_logico"] == "capa3_solo"
    assert respuestas == []  # se consumieron ambas respuestas (hubo retry)


def test_extract_device_info_connection_error(monkeypatch):
    """Una excepción de conexión devuelve un mensaje claro, sin crashear."""
    client = OllamaClient()

    def fake_generate(**kwargs):
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(client._client, "generate", fake_generate)

    result = client.extract_device_info(CONFIG_CON_EVIDENCIA, "cisco_ios")

    assert result["confianza_extraccion"] == "baja"
    mensaje = (result.get("error", "") + " "
               + " ".join(result.get("notas_ambiguedad", []))).lower()
    assert "ollama no disponible" in mensaje
    assert "docker ps" in mensaje


def test_extract_device_info_empty_content_no_llm_call(monkeypatch):
    """Texto sin evidencia técnica: NUNCA se llama a Ollama (guardia previa)."""
    client = OllamaClient()
    llamadas = []

    def fake_generate(**kwargs):
        llamadas.append(kwargs)
        return {"response": VALID_JSON}

    monkeypatch.setattr(client._client, "generate", fake_generate)

    result = client.extract_device_info(
        "es capa 2, no tiene componente capa 3", "cisco_ios"
    )

    assert llamadas == []  # el modelo nunca se invocó
    assert result["confianza_extraccion"] == "baja"
    assert result["rol_logico"] == "desconocido"
    assert result["vlans_detectadas"] == []
    assert result["enrutamiento"]["protocolos_detectados"] == []


def test_extract_device_info_with_real_evidence_case(monkeypatch):
    """Caso real del bug: nunca debe devolver 100 VLANs ni RIP/OSPF inventados."""
    client = OllamaClient()

    def fake_generate(**kwargs):
        # Si esto se llegara a invocar, simula la alucinación real observada,
        # para que el test falle ruidosamente si la guardia no funciona.
        alucinado = json.loads(VALID_JSON)
        alucinado["vlans_detectadas"] = list(range(1, 101))
        alucinado["enrutamiento"]["protocolos_detectados"] = ["rip", "ospf"]
        alucinado["confianza_extraccion"] = "alta"
        return {"response": json.dumps(alucinado)}

    monkeypatch.setattr(client._client, "generate", fake_generate)

    result = client.extract_device_info(
        "es capa 2, no tiene componente capa 3", "cisco_ios"
    )

    assert result["confianza_extraccion"] == "baja"
    assert result["vlans_detectadas"] == []
    assert result["enrutamiento"]["protocolos_detectados"] == []


def test_extract_device_info_uses_declared_vendor_model(monkeypatch):
    """El prompt enviado incluye el vendor/modelo declarado por el usuario."""
    client = OllamaClient()
    prompts_enviados = []

    def fake_generate(**kwargs):
        prompts_enviados.append(kwargs.get("prompt", ""))
        return {"response": VALID_JSON}

    monkeypatch.setattr(client._client, "generate", fake_generate)

    client.extract_device_info(
        CONFIG_CON_EVIDENCIA, "cisco_ios",
        vendor_modelo_declarado="cisco nexus 9400",
    )

    assert len(prompts_enviados) == 1
    assert "cisco nexus 9400" in prompts_enviados[0]


def test_extract_device_info_politicas_null_normalized_to_zero(monkeypatch):
    """Si el modelo devuelve null en campos de politicas, se normalizan a 0."""
    client = OllamaClient()
    respuesta = json.loads(VALID_JSON)
    respuesta["politicas"] = {
        "cantidad_total_declaradas": None,
        "cantidad_activas": None,
        "cantidad_inactivas_o_deshabilitadas": None,
    }
    monkeypatch.setattr(
        client._client, "generate",
        lambda **kwargs: {"response": json.dumps(respuesta)},
    )

    result = client.extract_device_info(CONFIG_CON_EVIDENCIA, "cisco_ios")

    assert result["politicas"]["cantidad_total_declaradas"] == 0
    assert result["politicas"]["cantidad_activas"] == 0
    assert result["politicas"]["cantidad_inactivas_o_deshabilitadas"] == 0


def test_rol_logico_seguridad_sin_politicas_se_degrada(monkeypatch):
    """rol_logico='capa3_y_seguridad' sin políticas → se degrada a capa3_solo."""
    client = OllamaClient()
    respuesta = json.loads(VALID_JSON)
    respuesta["rol_logico"] = "capa3_y_seguridad"
    respuesta["politicas"] = {
        "cantidad_total_declaradas": 0,
        "cantidad_activas": 0,
        "cantidad_inactivas_o_deshabilitadas": 0,
    }
    monkeypatch.setattr(
        client._client, "generate",
        lambda **kwargs: {"response": json.dumps(respuesta)},
    )

    result = client.extract_device_info(CONFIG_CON_EVIDENCIA, "cisco_ios")

    assert result["rol_logico"] == "capa3_solo"
    notas = " ".join(result.get("notas_ambiguedad", [])).lower()
    assert "función de seguridad" in notas
    assert "no se detectaron políticas" in notas


def test_rol_logico_seguridad_con_politicas_se_mantiene(monkeypatch):
    """rol_logico='capa3_y_seguridad' con políticas reales → no se modifica.

    El texto incluye evidencia real de políticas ("access-list") para que la
    validación cruzada de _validar_politicas_contra_evidencia() no degrade el
    conteo a 0 (lo haría con CONFIG_CON_EVIDENCIA solo, que es enrutamiento
    puro sin ninguna mención de reglas de firewall).
    """
    client = OllamaClient()
    config_con_politicas = (
        CONFIG_CON_EVIDENCIA + "access-list 101 permit ip any any\n"
    )
    respuesta = json.loads(VALID_JSON)
    respuesta["rol_logico"] = "capa3_y_seguridad"
    respuesta["politicas"] = {
        "cantidad_total_declaradas": 12,
        "cantidad_activas": 10,
        "cantidad_inactivas_o_deshabilitadas": 2,
    }
    monkeypatch.setattr(
        client._client, "generate",
        lambda **kwargs: {"response": json.dumps(respuesta)},
    )

    result = client.extract_device_info(config_con_politicas, "cisco_ios")

    assert result["rol_logico"] == "capa3_y_seguridad"
    assert result.get("notas_ambiguedad", []) == []


def test_politicas_sin_evidencia_textual_se_degradan_a_cero(monkeypatch):
    """Caso real Nexus 9400: politicas>0 sin ninguna mención en el texto → 0."""
    client = OllamaClient()
    respuesta = json.loads(VALID_JSON)
    respuesta["politicas"] = {
        "cantidad_total_declaradas": 1,
        "cantidad_activas": 1,
        "cantidad_inactivas_o_deshabilitadas": 0,
    }
    monkeypatch.setattr(
        client._client, "generate",
        lambda **kwargs: {"response": json.dumps(respuesta)},
    )

    # CONFIG_CON_EVIDENCIA es enrutamiento puro: ninguna mención de políticas.
    result = client.extract_device_info(CONFIG_CON_EVIDENCIA, "cisco_ios")

    assert result["politicas"] == {
        "cantidad_total_declaradas": 0,
        "cantidad_activas": 0,
        "cantidad_inactivas_o_deshabilitadas": 0,
    }
    notas = " ".join(result.get("notas_ambiguedad", [])).lower()
    assert "evidencia de reglas de firewall" in notas


def test_politicas_con_evidencia_textual_se_mantienen(monkeypatch):
    """La misma respuesta, pero con 'policy' en el texto → no se modifica."""
    client = OllamaClient()
    config_con_policy = CONFIG_CON_EVIDENCIA + "ip access-list policy TEST\n"
    respuesta = json.loads(VALID_JSON)
    respuesta["politicas"] = {
        "cantidad_total_declaradas": 1,
        "cantidad_activas": 1,
        "cantidad_inactivas_o_deshabilitadas": 0,
    }
    monkeypatch.setattr(
        client._client, "generate",
        lambda **kwargs: {"response": json.dumps(respuesta)},
    )

    result = client.extract_device_info(config_con_policy, "cisco_ios")

    assert result["politicas"] == {
        "cantidad_total_declaradas": 1,
        "cantidad_activas": 1,
        "cantidad_inactivas_o_deshabilitadas": 0,
    }
    assert result.get("notas_ambiguedad", []) == []


def test_licencias_sin_evidencia_se_fuerzan_a_false(monkeypatch):
    """Caso real Nexus 9400: detectadas=true con notas vacío y sin evidencia."""
    client = OllamaClient()
    respuesta = json.loads(VALID_JSON)
    respuesta["licencias_adicionales"] = {"detectadas": True, "notas": ""}
    monkeypatch.setattr(
        client._client, "generate",
        lambda **kwargs: {"response": json.dumps(respuesta)},
    )

    # CONFIG_CON_EVIDENCIA no menciona "license"/"licencia"/"feature".
    result = client.extract_device_info(CONFIG_CON_EVIDENCIA, "cisco_ios")

    assert result["licencias_adicionales"]["detectadas"] is False
    notas = " ".join(result.get("notas_ambiguedad", [])).lower()
    assert "licencias adicionales" in notas
