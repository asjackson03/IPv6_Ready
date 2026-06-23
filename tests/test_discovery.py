"""Pruebas unitarias del Módulo 1 — Discovery.

Cubren la carga de datos simulados, la evaluación de compatibilidad IPv6
y la construcción del inventario.
"""
import os

import pandas as pd
import pytest

from src.discovery import NetworkScanner, IPv6Checker, InventoryManager

# Ruta al JSON de datos simulados (relativa a la raíz del proyecto).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK_PATH = os.path.join(PROJECT_ROOT, "data", "sample", "mock_devices.json")


# --------------------------------------------------------------------------- #
#  NetworkScanner.load_mock_data
# --------------------------------------------------------------------------- #
def test_load_mock_data():
    """Carga el JSON de muestra y devuelve una lista no vacía con 'source'."""
    scanner = NetworkScanner()
    devices = scanner.load_mock_data(MOCK_PATH)

    assert isinstance(devices, list)
    assert len(devices) > 0
    assert len(devices) == 10  # el mock define exactamente 10 dispositivos
    assert all(d["source"] == "mock_data" for d in devices)


# --------------------------------------------------------------------------- #
#  IPv6Checker.evaluate_device
# --------------------------------------------------------------------------- #
def test_evaluate_device_compatible():
    """Un Linux moderno con IPv6 activo debe puntuar >= 80 y ser COMPATIBLE."""
    device = {
        "ip": "192.168.1.50",
        "hostname": "srv-linux-moderno",
        "os_detected": "Ubuntu Linux",
        "os_version": "22.04 LTS",
        "device_type": "server",
        "vendor": "Dell",
        "open_ports": [22, 443],
        "ipv6_address": "2001:db8::50",
        "ttl": 64,
        "snmp_available": True,
        "firmware_version": None,
    }
    result = IPv6Checker().evaluate_device(device)

    assert result["ipv6_score"] >= 80
    assert result["ipv6_status"] == "COMPATIBLE"
    assert "recomendacion_basica" in result
    assert "evaluated_at" in result


def test_evaluate_device_incompatible():
    """Un dispositivo IoT genérico sin IPv6 debe ser INCOMPATIBLE o REQUIERE_UPGRADE."""
    device = {
        "ip": "192.168.1.99",
        "hostname": "cam-iot-generica",
        "os_detected": "Embedded Linux (BusyBox)",
        "os_version": "unknown",
        "device_type": "iot",
        "vendor": "Generic",
        "open_ports": [80, 554],
        "ipv6_address": None,
        "ttl": 64,
        "snmp_available": False,
        "firmware_version": "V5.4.5",
    }
    result = IPv6Checker().evaluate_device(device)

    assert result["ipv6_status"] in ("INCOMPATIBLE", "REQUIERE_UPGRADE")
    assert 0 <= result["ipv6_score"] <= 49


# --------------------------------------------------------------------------- #
#  InventoryManager.build_inventory
# --------------------------------------------------------------------------- #
def test_build_inventory():
    """El DataFrame tiene las columnas clave y se ordena por score descendente."""
    scanner = NetworkScanner()
    checker = IPv6Checker()
    inventory = InventoryManager()

    devices = scanner.load_mock_data(MOCK_PATH)
    evaluated = [checker.evaluate_device(d) for d in devices]
    df = inventory.build_inventory(evaluated)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == len(devices)

    # Columnas esperadas presentes.
    for col in ("ip", "hostname", "ipv6_score", "ipv6_status"):
        assert col in df.columns

    # Orden descendente por puntaje.
    scores = df["ipv6_score"].tolist()
    assert scores == sorted(scores, reverse=True)
