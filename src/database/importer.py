"""importer.py — Carga los JSON ya generados (Módulos 1 y 3a) a la BD.

Reutiliza los datos reales que el proyecto ya produjo (data/raw/*.json del
discovery, data/processed/topology_session_*.json del levantamiento) como
semilla de la base de datos, sin re-ejecutar escaneos ni levantamientos.
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime

from src.database.db import SessionLocal
from src.database.models import (
    Device,
    Scan,
    TopologyDevice,
    TopologySession,
    categoria_para_device_type,
    criticidad_para_categoria,
)

# Directorios estándar del proyecto (relativos a la raíz).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(_ROOT, "data", "raw")
PROCESSED_DIR = os.path.join(_ROOT, "data", "processed")


class DataImporter:
    """Importa scans del Módulo 1 y sesiones de topología del Módulo 3a."""

    def __init__(self, session=None):
        # Permite inyectar una sesión (tests con BD en memoria); si no, abre
        # una sesión sobre la BD real del proyecto.
        self._external_session = session is not None
        self.session = session or SessionLocal()

    # ------------------------------------------------------------------ #
    #  Import de un scan del Módulo 1
    # ------------------------------------------------------------------ #
    def import_scan_json(self, filepath: str) -> Scan:
        """Lee un data/raw/*.json (Módulo 1) y crea el Scan + sus Device.

        Mapea ``device_type`` a una de las 7 categorías con la heurística
        simplificada documentada en models.py, y deriva la criticidad.
        """
        with open(filepath, "r", encoding="utf-8") as fh:
            devices_raw = json.load(fh)

        if not isinstance(devices_raw, list):
            raise ValueError(
                f"Formato inesperado en {filepath}: se esperaba una lista de "
                f"dispositivos."
            )

        timestamp = self._timestamp_from_filename(filepath) or datetime.utcnow()
        modo = self._infer_modo(devices_raw)

        scan = Scan(
            timestamp=timestamp,
            target=self._infer_target(devices_raw),
            modo=modo,
            source_file=os.path.basename(filepath),
        )

        for dev in devices_raw:
            categoria = categoria_para_device_type(dev.get("device_type"))
            criticidad = criticidad_para_categoria(categoria)
            scan.devices.append(Device(
                ip=dev.get("ip"),
                mac=dev.get("mac"),
                hostname=dev.get("hostname"),
                device_type=dev.get("device_type"),
                vendor=dev.get("vendor"),
                os_detected=dev.get("os_detected"),
                ipv6_score=dev.get("ipv6_score"),
                ipv6_status=dev.get("ipv6_status"),
                ml_classification=dev.get("ml_classification"),
                ml_confidence=dev.get("ml_confidence"),
                categoria=categoria,
                criticidad=criticidad,
            ))

        self.session.add(scan)
        self.session.commit()
        return scan

    # ------------------------------------------------------------------ #
    #  Import de una sesión de topología del Módulo 3a
    # ------------------------------------------------------------------ #
    def import_topology_json(self, filepath: str) -> TopologySession:
        """Lee un topology_session_*.json (Módulo 3a) y crea sesión + equipos."""
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        info = data.get("sesion_levantamiento", {}) if isinstance(data, dict) else {}
        dispositivos = data.get("dispositivos", []) if isinstance(data, dict) else []

        session_row = TopologySession(
            tipo_cliente=info.get("tipo_cliente"),
            cantidad_sedes=info.get("cantidad_sedes"),
            timestamp_inicio=info.get("timestamp_inicio"),
            timestamp_fin=info.get("timestamp_fin"),
            source_file=os.path.basename(filepath),
        )

        for dev in dispositivos:
            session_row.devices.append(TopologyDevice(
                nombre_asignado=dev.get("nombre_asignado")
                or dev.get("_entrada_usuario"),
                rol_logico=dev.get("rol_logico"),
                vendor_declarado=dev.get("vendor_declarado")
                or dev.get("_vendor_declarado"),
                modelo=dev.get("modelo"),
                version_so=dev.get("version_so"),
                licencias_adicionales_json=self._dumps(
                    dev.get("licencias_adicionales")
                ),
                interfaces_json=self._dumps(dev.get("interfaces")),
                vlans_json=self._dumps(dev.get("vlans_detectadas")),
                dhcp_json=self._dumps(dev.get("dhcp")),
                enrutamiento_json=self._dumps(dev.get("enrutamiento")),
                politicas_json=self._dumps(dev.get("politicas")),
                notas_ambiguedad_json=self._dumps(dev.get("notas_ambiguedad")),
                ipv6_configurado=dev.get("ipv6_configurado_en_algo"),
                confianza_extraccion=dev.get("confianza_extraccion"),
                es_firewall_sin_capa3=bool(dev.get("_es_firewall_sin_capa3", False)),
            ))

        self.session.add(session_row)
        self.session.commit()
        return session_row

    # ------------------------------------------------------------------ #
    #  Import masivo de todo lo existente
    # ------------------------------------------------------------------ #
    def import_all_existing_data(self) -> dict:
        """Importa TODOS los *.json existentes en data/raw y data/processed.

        Maneja errores por archivo sin abortar el resto: acumula una lista de
        ``(archivo, error)`` para reportar al final.

        Returns:
            Dict con conteos y errores:
            ``{"scans": int, "topology_sessions": int, "devices": int,
               "topology_devices": int, "errores": [(archivo, msg), ...]}``
        """
        resumen = {
            "scans": 0,
            "topology_sessions": 0,
            "devices": 0,
            "topology_devices": 0,
            "errores": [],
        }

        # Scans del Módulo 1 (ignora los AppleDouble ._* del disco no-APFS).
        for filepath in sorted(glob.glob(os.path.join(RAW_DIR, "*.json"))):
            if os.path.basename(filepath).startswith("._"):
                continue
            try:
                scan = self.import_scan_json(filepath)
                resumen["scans"] += 1
                resumen["devices"] += len(scan.devices)
            except Exception as exc:  # noqa: BLE001 — robustez por archivo
                resumen["errores"].append((os.path.basename(filepath), str(exc)))

        # Sesiones de topología del Módulo 3a.
        patron = os.path.join(PROCESSED_DIR, "topology_session_*.json")
        for filepath in sorted(glob.glob(patron)):
            if os.path.basename(filepath).startswith("._"):
                continue
            try:
                session_row = self.import_topology_json(filepath)
                resumen["topology_sessions"] += 1
                resumen["topology_devices"] += len(session_row.devices)
            except Exception as exc:  # noqa: BLE001 — robustez por archivo
                resumen["errores"].append((os.path.basename(filepath), str(exc)))

        return resumen

    def close(self) -> None:
        """Cierra la sesión si la abrió este importador (no la inyectada)."""
        if not self._external_session:
            self.session.close()

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _dumps(value) -> str | None:
        """Serializa a JSON (None si value es None)."""
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _timestamp_from_filename(filepath: str) -> datetime | None:
        """Extrae el timestamp del nombre (ipv6_scan_YYYYMMDD_HHMMSS.json)."""
        match = re.search(r"(\d{8})_(\d{6})", os.path.basename(filepath))
        if not match:
            return None
        try:
            return datetime.strptime(
                match.group(1) + match.group(2), "%Y%m%d%H%M%S"
            )
        except ValueError:
            return None

    @staticmethod
    def _infer_modo(devices_raw: list) -> str:
        """Infiere el modo del scan a partir del campo source del primer device."""
        if devices_raw and isinstance(devices_raw[0], dict):
            source = devices_raw[0].get("source", "")
            if source == "mock_data":
                return "demo"
        return "target"

    @staticmethod
    def _infer_target(devices_raw: list) -> str | None:
        """Aproxima el target como el prefijo /24 común de las IPs del scan."""
        ips = [
            d.get("ip") for d in devices_raw
            if isinstance(d, dict) and d.get("ip")
        ]
        if not ips:
            return None
        first = ips[0]
        partes = first.split(".")
        if len(partes) == 4:
            return f"{partes[0]}.{partes[1]}.{partes[2]}.0/24"
        return first
