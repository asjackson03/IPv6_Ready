"""Pruebas de la capa de base de datos (Bloque 1).

Usan una BD SQLite en memoria (sin tocar el archivo real del proyecto) y
fixtures basados en la estructura real de data/raw/*.json y
data/processed/topology_session_*.json.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
from src.database.importer import DataImporter
from src.database.models import (
    Device,
    Scan,
    TopologyDevice,
    TopologySession,
    categoria_para_device_type,
    criticidad_para_categoria,
)


@pytest.fixture
def session():
    """Sesión sobre una BD SQLite en memoria, con tablas creadas."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


# Fixture de un scan del Módulo 1 (subconjunto real de data/raw/).
SCAN_FIXTURE = [
    {
        "ip": "192.168.1.1", "mac": "00:1A:2B:3C:4D:01",
        "hostname": "rtr-core-bogota", "device_type": "router",
        "vendor": "Cisco", "os_detected": "Cisco IOS-XE Software",
        "ipv6_score": 95, "ipv6_status": "COMPATIBLE", "source": "mock_data",
    },
    {
        "ip": "192.168.1.10", "mac": "00:50:56:AA:01:06",
        "hostname": "srv-web", "device_type": "server",
        "vendor": "Dell", "os_detected": "Ubuntu Linux",
        "ipv6_score": 100, "ipv6_status": "COMPATIBLE", "source": "mock_data",
    },
    {
        "ip": "192.168.1.20", "mac": "00:1B:78:EE:FF:09",
        "hostname": "impresora-rrhh", "device_type": "printer",
        "vendor": "HP", "os_detected": "HP Embedded Web Server",
        "ipv6_score": 5, "ipv6_status": "INCOMPATIBLE", "source": "mock_data",
    },
    {
        "ip": "192.168.1.50", "mac": "AA:BB:CC:DD:EE:50",
        "hostname": "pc-usuario", "device_type": "desconocido",
        "vendor": "Generic", "os_detected": "Windows 11",
        "ipv6_score": 70, "ipv6_status": "PARCIAL", "source": "mock_data",
    },
]

# Fixture de una sesión de topología del Módulo 3a (estructura real).
TOPOLOGY_FIXTURE = {
    "sesion_levantamiento": {
        "tipo_cliente": "cliente_final",
        "cantidad_sedes": 2,
        "timestamp_inicio": "2026-06-24T14:19:28",
        "timestamp_fin": "2026-06-24T14:34:56",
        "total_dispositivos": 2,
    },
    "dispositivos": [
        {
            "rol_logico": "capa3_solo", "modelo": "cisco nexus 9400",
            "version_so": None,
            "licencias_adicionales": {"detectadas": False, "notas": ""},
            "interfaces": [{"nombre": "Vlan10", "ip_v4": "192.168.10.1/24",
                            "ip_v6": None, "vlan_id": 10, "estado": "up"}],
            "vlans_detectadas": [10, 20, 30],
            "dhcp": {"es_servidor_dhcp": False, "tiene_dhcp_relay": True,
                     "ip_relay_destino": "192.168.10.50"},
            "enrutamiento": {"protocolos_detectados": ["OSPF", "BGP"],
                             "rutas_estaticas": [], "bgp_detalle": {}},
            "politicas": {"cantidad_total_declaradas": 0,
                          "cantidad_activas": 0,
                          "cantidad_inactivas_o_deshabilitadas": 0},
            "ipv6_configurado_en_algo": True,
            "confianza_extraccion": "alta", "notas_ambiguedad": [],
            "_vendor_declarado": "cisco_ios", "_entrada_usuario": "cisco nexus 9400",
        },
        {
            "rol_logico": "seguridad_solo", "modelo": "fortinet",
            "version_so": None,
            "licencias_adicionales": {"detectadas": False, "notas": ""},
            "interfaces": [{"nombre": "port1", "ip_v4": "192.168.1.1",
                            "ip_v6": None, "vlan_id": None, "estado": None}],
            "vlans_detectadas": [],
            "dhcp": {"es_servidor_dhcp": False, "tiene_dhcp_relay": False,
                     "ip_relay_destino": None},
            "enrutamiento": {"protocolos_detectados": ["static"],
                             "rutas_estaticas": [], "bgp_detalle": {}},
            "politicas": {"cantidad_total_declaradas": 2,
                          "cantidad_activas": 1,
                          "cantidad_inactivas_o_deshabilitadas": 1},
            "ipv6_configurado_en_algo": False,
            "confianza_extraccion": "alta", "notas_ambiguedad": [],
            "_vendor_declarado": "fortinet", "_entrada_usuario": "fortinet",
            "_es_firewall_sin_capa3": True,
        },
    ],
}


def test_init_creates_tables(session):
    """Las tablas se crean y se puede insertar/consultar un Scan vacío."""
    scan = Scan(target="192.168.1.0/24", modo="demo")
    session.add(scan)
    session.commit()
    assert session.query(Scan).count() == 1


def test_categoria_y_criticidad_mapping():
    """device_type -> categoría -> criticidad según las reglas de CLAUDE.md."""
    # equipos_red_seguridad (alta).
    assert categoria_para_device_type("router") == "equipos_red_seguridad"
    assert categoria_para_device_type("switch") == "equipos_red_seguridad"
    assert categoria_para_device_type("firewall") == "equipos_red_seguridad"
    assert criticidad_para_categoria("equipos_red_seguridad") == "alta"
    # servidores (alta).
    assert categoria_para_device_type("server") == "servidores"
    assert criticidad_para_categoria("servidores") == "alta"
    # perifericos (baja).
    assert categoria_para_device_type("printer") == "perifericos"
    assert categoria_para_device_type("iot") == "perifericos"
    assert criticidad_para_categoria("perifericos") == "baja"
    # default -> equipos_finales (baja).
    assert categoria_para_device_type("desconocido") == "equipos_finales"
    assert criticidad_para_categoria("equipos_finales") == "baja"


def test_import_scan_json(tmp_path, session):
    """Importar un JSON de scan crea el Scan y sus Device con categoría correcta."""
    filepath = tmp_path / "ipv6_scan_20260623_152507.json"
    filepath.write_text(json.dumps(SCAN_FIXTURE), encoding="utf-8")

    importer = DataImporter(session=session)
    scan = importer.import_scan_json(str(filepath))

    assert scan.modo == "demo"  # source == mock_data
    assert session.query(Device).count() == 4

    router = session.query(Device).filter_by(device_type="router").one()
    assert router.categoria == "equipos_red_seguridad"
    assert router.criticidad == "alta"

    printer = session.query(Device).filter_by(device_type="printer").one()
    assert printer.categoria == "perifericos"
    assert printer.criticidad == "baja"

    desconocido = session.query(Device).filter_by(
        device_type="desconocido").one()
    assert desconocido.categoria == "equipos_finales"
    assert desconocido.criticidad == "baja"


def test_import_topology_json(tmp_path, session):
    """Importar una sesión de topología crea la sesión y sus TopologyDevice."""
    filepath = tmp_path / "topology_session_20260624_143456.json"
    filepath.write_text(json.dumps(TOPOLOGY_FIXTURE), encoding="utf-8")

    importer = DataImporter(session=session)
    sess = importer.import_topology_json(str(filepath))

    assert sess.cantidad_sedes == 2
    assert sess.tipo_cliente == "cliente_final"
    assert session.query(TopologyDevice).count() == 2

    # El firewall complementario quedó marcado y sus campos JSON deserializan.
    fw = session.query(TopologyDevice).filter_by(
        es_firewall_sin_capa3=True).one()
    assert fw.rol_logico == "seguridad_solo"
    assert fw.politicas["cantidad_total_declaradas"] == 2

    switch = session.query(TopologyDevice).filter_by(
        es_firewall_sin_capa3=False).one()
    assert switch.vlans_detectadas == [10, 20, 30]
    assert "OSPF" in switch.enrutamiento["protocolos_detectados"]


def test_topology_device_json_properties_defaults(session):
    """Las propiedades JSON devuelven defaults vacíos si la columna es None."""
    ses = TopologySession(tipo_cliente="cliente_final", cantidad_sedes=1)
    # Equipo sin ningún campo JSON poblado (columnas None).
    ses.devices.append(TopologyDevice(rol_logico="desconocido"))
    session.add(ses)
    session.commit()

    d = session.query(TopologyDevice).one()
    assert d.interfaces == []
    assert d.vlans_detectadas == []
    assert d.dhcp == {}
    assert d.politicas == {}
    assert d.notas_ambiguedad == []
    assert d.es_firewall_sin_capa3 is False  # default de columna


def test_import_scan_modo_target_y_timestamp(tmp_path, session):
    """Un scan sin source=mock_data se marca modo='target' y parsea timestamp."""
    devices = [{
        "ip": "10.0.0.1", "hostname": "real-host", "device_type": "router",
        "vendor": "Cisco", "os_detected": "IOS-XE", "ipv6_score": 90,
        "ipv6_status": "COMPATIBLE", "source": "nmap_scan",
    }]
    filepath = tmp_path / "ipv6_scan_20260622_121932.json"
    filepath.write_text(json.dumps(devices), encoding="utf-8")

    importer = DataImporter(session=session)
    scan = importer.import_scan_json(str(filepath))

    assert scan.modo == "target"  # source != mock_data
    assert scan.timestamp.year == 2026 and scan.timestamp.month == 6
    assert scan.timestamp.day == 22
    assert scan.target == "10.0.0.0/24"  # /24 inferido de la primera IP


def test_import_all_handles_bad_file(tmp_path, session, monkeypatch):
    """Un archivo corrupto no aborta el import del resto; queda en errores."""
    import src.database.importer as importer_mod

    raw_dir = tmp_path / "raw"
    proc_dir = tmp_path / "processed"
    raw_dir.mkdir()
    proc_dir.mkdir()

    # Un scan válido y un archivo corrupto en el mismo directorio.
    (raw_dir / "ipv6_scan_20260101_000000.json").write_text(
        json.dumps(SCAN_FIXTURE), encoding="utf-8")
    (raw_dir / "ipv6_scan_corrupto.json").write_text(
        "{ esto no es json válido", encoding="utf-8")

    monkeypatch.setattr(importer_mod, "RAW_DIR", str(raw_dir))
    monkeypatch.setattr(importer_mod, "PROCESSED_DIR", str(proc_dir))

    importer = DataImporter(session=session)
    resumen = importer.import_all_existing_data()

    assert resumen["scans"] == 1
    assert resumen["devices"] == 4
    assert len(resumen["errores"]) == 1
    assert "corrupto" in resumen["errores"][0][0]
