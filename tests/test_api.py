"""Pruebas de la API HTTP del Módulo 2 (FastAPI).

Usan ``TestClient``, que ejercita la app de FastAPI en memoria: NO requieren
Docker ni un servidor uvicorn corriendo.
"""
import importlib

import pytest

# La API depende de FastAPI; si no está instalado, se omiten estas pruebas.
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.classifier import api as api_module  # noqa: E402


def _client():
    """Devuelve un TestClient sobre la app de FastAPI."""
    return TestClient(api_module.app)


def test_api_health_endpoint():
    """GET /health responde 200 con la estructura {status, model_loaded}."""
    response = _client().get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "model_loaded" in body
    assert isinstance(body["model_loaded"], bool)


def test_api_classify_without_trained_model(tmp_path, monkeypatch):
    """POST /classify sin modelo entrenado responde 503 con mensaje claro."""
    # Apunta MODEL_DIR a una carpeta vacía: fuerza el escenario "sin modelo".
    monkeypatch.setattr(api_module, "MODEL_DIR", str(tmp_path))

    device = {
        "ip": "192.168.1.1",
        "os_detected": "Cisco IOS-XE Software",
        "os_version": "17.6.3",
        "device_type": "router",
        "vendor": "Cisco",
        "open_ports": [22, 443, 161],
        "ipv6_address": "2001:db8:100::1",
        "ttl": 255,
        "snmp_available": True,
        "firmware_version": "17.06.03",
        "ipv6_score": 95,
        "os_detection_method": "fingerprint",
    }

    response = _client().post("/classify", json=[device])

    assert response.status_code == 503
    detail = response.json()["detail"].lower()
    assert "entrenar" in detail or "no entrenado" in detail
