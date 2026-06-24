"""Pruebas de TopologySession (Módulo 3a).

El flujo completo es interactivo (input() en vivo) y no se testea aquí. Estas
pruebas cubren _forzar_rol_firewall_complementario() de forma aislada: es un
método estático puro (dict -> dict), sin necesidad de mockear input/Ollama.
"""
from src.roadmap.topology_session import TopologySession


def test_forzar_rol_firewall_con_politicas():
    """Firewall complementario con políticas reales → rol_logico='seguridad_solo'."""
    info = {
        "politicas": {
            "cantidad_total_declaradas": 8,
            "cantidad_activas": 6,
            "cantidad_inactivas_o_deshabilitadas": 2,
        },
        "rol_logico": "capa3_y_seguridad",  # lo que infirió el modelo, se ignora
    }

    resultado = TopologySession._forzar_rol_firewall_complementario(info)

    assert resultado["rol_logico"] == "seguridad_solo"


def test_forzar_rol_firewall_sin_politicas():
    """Firewall complementario sin ninguna política → rol_logico='desconocido'."""
    info = {
        "politicas": {
            "cantidad_total_declaradas": 0,
            "cantidad_activas": 0,
            "cantidad_inactivas_o_deshabilitadas": 0,
        },
        "rol_logico": "capa3_y_seguridad",  # lo que infirió el modelo, se ignora
    }

    resultado = TopologySession._forzar_rol_firewall_complementario(info)

    assert resultado["rol_logico"] == "desconocido"
