"""Pruebas unitarias del Módulo 1 — Discovery.

Cubren la carga de datos simulados, la evaluación de compatibilidad IPv6
y la construcción del inventario.
"""
import os

import pandas as pd
import pytest

from src.discovery import NetworkScanner, IPv6Checker, InventoryManager
from src.classifier import FeatureExtractor, ModelTrainer, DeviceClassifier

# Ruta al JSON de datos simulados (relativa a la raíz del proyecto).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK_PATH = os.path.join(PROJECT_ROOT, "data", "sample", "mock_devices.json")
TRAINING_PATH = os.path.join(PROJECT_ROOT, "data", "sample", "training_dataset.json")
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
NO_OSMATCH_FIXTURE = os.path.join(FIXTURES_DIR, "nmap_no_osmatch.xml")
AMBIGUOUS_OSMATCH_FIXTURE = os.path.join(FIXTURES_DIR, "nmap_ambiguous_tplink.xml")


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
#  NetworkScanner._calculate_timeout
# --------------------------------------------------------------------------- #
def test_dynamic_timeout_calculation():
    """El timeout dinámico crece para rangos grandes y no cambia para una IP única."""
    base_timeout = 30

    cidr_timeout = NetworkScanner._calculate_timeout("192.168.1.0/24", base_timeout)
    assert cidr_timeout > base_timeout

    single_ip_timeout = NetworkScanner._calculate_timeout("192.168.1.1", base_timeout)
    assert single_ip_timeout == base_timeout


# --------------------------------------------------------------------------- #
#  NetworkScanner._parse_host — extracción de vendor a partir de MAC
# --------------------------------------------------------------------------- #
def test_parse_host_vendor_extraction():
    """_parse_host() debe extraer el vendor correcto a partir de la MAC.

    Se construye un host_data con la estructura REAL que produce
    python-nmap 0.7.1 al parsear una salida XML de nmap (confirmada
    inspeccionando nmap.py: 'addresses[\"mac\"]' y la clave de 'vendor'
    provienen del mismo atributo XML <address addrtype="mac" addr="..."
    vendor="..."/>, por lo que ambos deben coincidir exactamente). Se usa
    una MAC y vendor tomados de evidencia real de escaneo
    (sudo nmap -sV -O --version-intensity 5 -n 192.168.68.0/24):
    "88:DE:A9:99:68:05 (Roku)".
    """
    nmap = pytest.importorskip("nmap")

    xml_output = """<?xml version="1.0"?>
<nmaprun scanner="nmap" args="nmap -sV -O --version-intensity 5 -n" start="0"
 startstr="x" version="7.94" xmloutputversion="1.05">
<scaninfo type="syn" protocol="tcp" numservices="1000" services="80"/>
<host starttime="0" endtime="0">
<status state="up" reason="arp-response" reason_ttl="0"/>
<address addr="192.168.68.10" addrtype="ipv4"/>
<address addr="88:DE:A9:99:68:05" addrtype="mac" vendor="Roku"/>
<hostnames><hostname name="" type=""/></hostnames>
<ports>
<port protocol="tcp" portid="8060">
<state state="open" reason="syn-ack" reason_ttl="0"/>
<service name="http" method="table" conf="3"/>
</port>
</ports>
</host>
<runstats><finished time="0" timestr="x" elapsed="0" summary="x" exit="success"/>
<hosts up="1" down="0" total="1"/></runstats>
</nmaprun>
"""

    nm = nmap.PortScanner()
    nm.analyse_nmap_xml_scan(nmap_xml_output=xml_output)
    host = nm.all_hosts()[0]

    device = NetworkScanner()._parse_host(nm, host)

    assert device["mac"] == "88:DE:A9:99:68:05"
    assert device["vendor"] == "Roku"


# --------------------------------------------------------------------------- #
#  Diagnóstico + fallback de detección de SO (osmatch vacío / baja precisión)
#
#  Evidencia real: "sudo nmap -sV -O --version-intensity 5 -n 192.168.68.1"
#  (router TP-Link/OpenWrt) imprimió literalmente "No exact OS matches for
#  host" y "Service Info: OS: Linux; Devices: WAP, broadband router; CPE:
#  cpe:/o:linux:linux_kernel". El fixture tests/fixtures/nmap_no_osmatch.xml
#  reproduce esa estructura.
# --------------------------------------------------------------------------- #
def test_diagnostic_osmatch_empty_and_service_info_not_exposed():
    """Diagnóstico previo al fix (no asumir, confirmar con datos reales).

    Confirma dos hechos sobre python-nmap 0.7.1 a partir del fixture de
    evidencia real, ANTES de aplicar ningún parche: (a) 'osmatch' es
    realmente una lista vacía para este host (no hay nada que indexar mal
    en [0], el bug no es de scope/indexación), y (b) el atributo 'ostype'
    de <service> (origen de la línea "Service Info: OS: ...") no aparece en
    el dict que python-nmap expone por puerto, así que solo se puede leer
    reparseando el XML crudo (nm.get_nmap_last_output()).
    """
    nmap = pytest.importorskip("nmap")

    with open(NO_OSMATCH_FIXTURE, encoding="utf-8") as fh:
        xml_output = fh.read()

    nm = nmap.PortScanner()
    nm.analyse_nmap_xml_scan(nmap_xml_output=xml_output)
    host = nm.all_hosts()[0]
    host_data = nm[host]

    assert host_data.get("osmatch", []) == []
    assert "ostype" not in host_data["tcp"][80]
    assert host_data["tcp"][80]["cpe"] == "cpe:/o:linux:linux_kernel"
    assert "ostype" in xml_output  # el dato SÍ está en el XML crudo


def test_parse_host_no_osmatch_fallback():
    """Sin osmatch pero con 'Service Info' disponible: usa el fallback.

    Debe extraer 'Linux' desde el ostype del <service>, marcando
    os_detection_method='service_info', y NUNCA un SO no relacionado con
    los datos reales del host (el bug reportado: "Sony Blu-Ray Player").
    """
    nmap = pytest.importorskip("nmap")

    with open(NO_OSMATCH_FIXTURE, encoding="utf-8") as fh:
        xml_output = fh.read()

    nm = nmap.PortScanner()
    nm.analyse_nmap_xml_scan(nmap_xml_output=xml_output)
    host = nm.all_hosts()[0]

    device = NetworkScanner()._parse_host(nm, host)

    assert device["os_detected"] == "Linux"
    assert device["os_detection_method"] == "service_info"
    assert "blu-ray" not in device["os_detected"].lower()
    assert "sony" not in device["os_detected"].lower()


def test_parse_host_low_accuracy_osmatch_rejected():
    """Un osmatch de baja precisión se descarta y cae al fallback de servicio.

    Reproduce el mecanismo real del falso positivo: nmap SÍ puede devolver
    un osmatch (no está vacío), pero con una precisión muy baja (router con
    firmware no estándar adivinado como un dispositivo sin relación). El fix
    debe ignorar ese match por debajo de OSMATCH_MIN_ACCURACY y preferir el
    'Service Info' confiable en vez de confiar ciegamente en osmatches[0].
    """
    nmap = pytest.importorskip("nmap")

    xml_output = """<?xml version="1.0"?>
<nmaprun scanner="nmap" args="nmap -sV -O --version-intensity 5 -n" start="0"
 startstr="x" version="7.94" xmloutputversion="1.05">
<scaninfo type="syn" protocol="tcp" numservices="1000" services="80"/>
<host starttime="0" endtime="0">
<status state="up" reason="arp-response" reason_ttl="0"/>
<address addr="192.168.68.1" addrtype="ipv4"/>
<address addr="B8:FB:B3:CA:68:49" addrtype="mac" vendor="TP-Link Systems"/>
<hostnames><hostname name="" type=""/></hostnames>
<ports>
<port protocol="tcp" portid="80">
<state state="open" reason="syn-ack" reason_ttl="0"/>
<service name="http" ostype="Linux" devicetype="WAP, broadband router"
 method="probed" conf="10"/>
</port>
</ports>
<os>
<osmatch name="Sony BDP-S1500 Blu-ray Disc player" accuracy="23" line="1">
<osclass type="media device" vendor="Sony" osfamily="embedded" osgen=""
 accuracy="23"/>
</osmatch>
</os>
</host>
<runstats><finished time="0" timestr="x" elapsed="0" summary="x" exit="success"/>
<hosts up="1" down="0" total="1"/></runstats>
</nmaprun>
"""

    nm = nmap.PortScanner()
    nm.analyse_nmap_xml_scan(nmap_xml_output=xml_output)
    host = nm.all_hosts()[0]

    # Confirma primero que el osmatch de baja precisión SÍ llegó al dict
    # (para no confundir este caso con el de osmatch realmente vacío).
    assert nm[host].get("osmatch", []) != []

    device = NetworkScanner()._parse_host(nm, host)

    assert device["os_detected"] == "Linux"
    assert device["os_detection_method"] == "service_info"


def test_parse_host_no_data_at_all():
    """Sin osmatch y sin 'Service Info': os_detected explícito y sin crash."""
    nmap = pytest.importorskip("nmap")

    xml_output = """<?xml version="1.0"?>
<nmaprun scanner="nmap" args="nmap -sV -O --version-intensity 5 -n" start="0"
 startstr="x" version="7.94" xmloutputversion="1.05">
<scaninfo type="syn" protocol="tcp" numservices="1000" services="80"/>
<host starttime="0" endtime="0">
<status state="up" reason="arp-response" reason_ttl="0"/>
<address addr="192.168.68.55" addrtype="ipv4"/>
<hostnames><hostname name="" type=""/></hostnames>
<ports>
<port protocol="tcp" portid="80">
<state state="open" reason="syn-ack" reason_ttl="0"/>
<service name="http" method="table" conf="3"/>
</port>
</ports>
</host>
<runstats><finished time="0" timestr="x" elapsed="0" summary="x" exit="success"/>
<hosts up="1" down="0" total="1"/></runstats>
</nmaprun>
"""

    nm = nmap.PortScanner()
    nm.analyse_nmap_xml_scan(nmap_xml_output=xml_output)
    host = nm.all_hosts()[0]

    device = NetworkScanner()._parse_host(nm, host)

    assert device["os_detected"] == "desconocido"
    assert device["os_detection_method"] == "ninguno"


def test_parse_host_ambiguous_osmatch_heterogeneo():
    """osmatches reales y heterogéneos cerca del mejor accuracy → ambiguo.

    Evidencia real (192.168.68.1, TP-Link/OpenWrt): 10 osmatches con el
    mejor en 88% ("Sony Blu-Ray Player") pero 9 candidatos más a solo 1-3
    puntos de distancia, mezclando Linux genérico con dispositivos sin
    relación entre sí (MikroTik, Sonos, Dish Network). Ningún nombre
    individual es confiable: el resultado debe ser "desconocido" con
    método "ambiguo", NUNCA "Sony Blu-Ray Player".
    """
    nmap = pytest.importorskip("nmap")

    with open(AMBIGUOUS_OSMATCH_FIXTURE, encoding="utf-8") as fh:
        xml_output = fh.read()

    nm = nmap.PortScanner()
    nm.analyse_nmap_xml_scan(nmap_xml_output=xml_output)
    host = nm.all_hosts()[0]

    # El mejor match (88%) sí supera OSMATCH_MIN_ACCURACY=80: confirma que
    # este caso no se resuelve por el umbral simple, hace falta la lógica
    # de dispersión.
    osmatches = nm[host].get("osmatch", [])
    assert int(osmatches[0]["accuracy"]) >= 80

    device = NetworkScanner()._parse_host(nm, host)

    assert device["os_detected"] == "desconocido"
    assert device["os_detection_method"] == "ambiguo"
    assert "sony" not in device["os_detected"].lower()
    assert "blu-ray" not in device["os_detected"].lower()


def test_parse_host_ambiguous_osmatch_homogeneo_linux():
    """Candidatos cercanos en accuracy pero TODOS variantes de Linux.

    A diferencia del caso heterogéneo, si los matches "cercanos" al mejor
    son todos Linux (distintas versiones empatadas en precisión), sí hay
    una conclusión útil y consistente: es Linux, simplemente no se puede
    saber qué versión exacta.
    """
    nmap = pytest.importorskip("nmap")

    xml_output = """<?xml version="1.0"?>
<nmaprun scanner="nmap" args="nmap -sV -O --version-intensity 5 -n" start="0"
 startstr="x" version="7.94" xmloutputversion="1.05">
<scaninfo type="syn" protocol="tcp" numservices="1000" services="22"/>
<host starttime="0" endtime="0">
<status state="up" reason="arp-response" reason_ttl="0"/>
<address addr="192.168.68.20" addrtype="ipv4"/>
<hostnames><hostname name="" type=""/></hostnames>
<ports>
<port protocol="tcp" portid="22">
<state state="open" reason="syn-ack" reason_ttl="0"/>
<service name="ssh" method="probed" conf="10"/>
</port>
</ports>
<os>
<osmatch name="Linux 5.10 - 5.15" accuracy="92" line="1">
<osclass type="general purpose" vendor="Linux" osfamily="Linux" osgen="5.X" accuracy="92"/>
</osmatch>
<osmatch name="Linux 4.15 - 5.6" accuracy="90" line="2">
<osclass type="general purpose" vendor="Linux" osfamily="Linux" osgen="4.X" accuracy="90"/>
</osmatch>
<osmatch name="Linux 3.2 - 4.9" accuracy="89" line="3">
<osclass type="general purpose" vendor="Linux" osfamily="Linux" osgen="3.X" accuracy="89"/>
</osmatch>
</os>
</host>
<runstats><finished time="0" timestr="x" elapsed="0" summary="x" exit="success"/>
<hosts up="1" down="0" total="1"/></runstats>
</nmaprun>
"""

    nm = nmap.PortScanner()
    nm.analyse_nmap_xml_scan(nmap_xml_output=xml_output)
    host = nm.all_hosts()[0]

    device = NetworkScanner()._parse_host(nm, host)

    assert device["os_detected"] == "Linux"
    assert device["os_detection_method"] == "fingerprint_generico"


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


# --------------------------------------------------------------------------- #
#  InventoryManager.print_quality_summary
# --------------------------------------------------------------------------- #
def test_print_quality_summary_no_crash():
    """print_quality_summary() no debe lanzar excepciones con datos mixtos."""
    df = pd.DataFrame([
        {
            "ip": "192.168.1.1", "hostname": "rtr-core", "vendor": "Cisco",
            "os_detection_method": "fingerprint",
        },
        {
            "ip": "192.168.68.1", "hostname": "desconocido", "vendor": "TP-Link Systems",
            "os_detection_method": "service_info",
        },
        {
            "ip": "192.168.68.55", "hostname": "desconocido", "vendor": "desconocido",
            "os_detection_method": "ninguno",
        },
    ])

    InventoryManager().print_quality_summary(df)


# --------------------------------------------------------------------------- #
#  Módulo 2 — Classifier ML
# --------------------------------------------------------------------------- #
def _mock_device(**overrides):
    """Dispositivo mínimo con campos del Módulo 1, sobrescribible en tests."""
    base = {
        "ip": "10.0.0.1",
        "hostname": "host-test",
        "os_detected": "Ubuntu Linux",
        "os_version": "22.04 LTS",
        "device_type": "server",
        "vendor": "Dell",
        "open_ports": [22, 443],
        "ipv6_address": "2001:db8::1",
        "ttl": 64,
        "snmp_available": True,
        "firmware_version": None,
        "ipv6_score": 70,
        "os_detection_method": "fingerprint",
    }
    base.update(overrides)
    return base


def test_feature_extraction_shape():
    """extract_features devuelve exactamente 11 floats en rango razonable."""
    extractor = FeatureExtractor()
    features = extractor.extract_features(_mock_device())

    assert features.shape == (11,)
    assert len(extractor.get_feature_names()) == 11
    # Todas las features de este proyecto están acotadas a [0, 5].
    assert all(0.0 <= float(v) <= 5.0 for v in features)


def test_feature_extraction_batch():
    """extract_batch sobre 3 dispositivos devuelve una matriz (3, 11)."""
    extractor = FeatureExtractor()
    devices = [
        _mock_device(ip="10.0.0.1"),
        _mock_device(ip="10.0.0.2", device_type="router"),
        _mock_device(ip="10.0.0.3", os_detection_method="ninguno"),
    ]
    matrix = extractor.extract_batch(devices)

    assert matrix.shape == (3, 11)


def test_os_confidence_score_mapping():
    """os_confidence_score: 'ambiguo' produce valor bajo; 'fingerprint' alto."""
    extractor = FeatureExtractor()
    idx = extractor.get_feature_names().index("os_confidence_score")

    ambiguo = extractor.extract_features(_mock_device(os_detection_method="ambiguo"))
    fingerprint = extractor.extract_features(
        _mock_device(os_detection_method="fingerprint")
    )

    assert ambiguo[idx] <= 0.3
    assert fingerprint[idx] == 1.0


def test_train_and_classify_roundtrip(tmp_path):
    """Entrena con el dataset real y clasifica un dispositivo de mock_devices."""
    pytest.importorskip("sklearn")
    model_dir = str(tmp_path / "model")

    trainer = ModelTrainer(model_dir=model_dir)
    metrics = trainer.train(TRAINING_PATH)
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert metrics["train_size"] + metrics["test_size"] == 50

    device = NetworkScanner().load_mock_data(MOCK_PATH)[0]
    classifier = DeviceClassifier(model_dir=model_dir)
    result = classifier.classify_device(device)

    assert result["ml_classification"] in {
        "LISTO", "ACTUALIZABLE", "REEMPLAZAR", "EVALUAR"
    }
    assert 0.0 <= result["ml_confidence"] <= 1.0
    assert set(result["ml_probabilities"].keys()) == {
        "LISTO", "ACTUALIZABLE", "REEMPLAZAR", "EVALUAR"
    }


def test_classify_batch_ordering(tmp_path):
    """classify_batch ordena por priority_score ascendente (lo urgente arriba)."""
    pytest.importorskip("sklearn")
    model_dir = str(tmp_path / "model")
    ModelTrainer(model_dir=model_dir).train(TRAINING_PATH)

    devices = NetworkScanner().load_mock_data(MOCK_PATH)
    classifier = DeviceClassifier(model_dir=model_dir)
    ordered = classifier.classify_batch(devices)

    priorities = [d["priority_score"] for d in ordered]
    assert priorities == sorted(priorities)
