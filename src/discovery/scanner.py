"""scanner.py — Descubrimiento de hosts en la red.

Contiene :class:`NetworkScanner`, responsable de:
  * Escanear una red real mediante nmap (``scan_network``).
  * Cargar un inventario simulado para el modo demo (``load_mock_data``).

La dependencia ``python-nmap`` se importa de forma perezosa (dentro del
método que la usa) para que el modo demo funcione aunque la librería o el
binario ``nmap`` no estén instalados.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Optional

# Campos mínimos que debe contener cada dispositivo del mock para considerarse válido.
REQUIRED_MOCK_FIELDS = {
    "ip", "mac", "hostname", "os_detected", "os_version",
    "device_type", "vendor", "open_ports", "ipv6_address",
    "ttl", "snmp_available", "firmware_version",
}


class NetworkScanner:
    """Escáner de red basado en nmap con soporte de datos simulados."""

    def __init__(self, timeout: int = 30, verbose: bool = False):
        self.timeout = timeout
        self.verbose = verbose

    # ------------------------------------------------------------------ #
    #  Escaneo de red real
    # ------------------------------------------------------------------ #
    def scan_network(self, target: str) -> list[dict]:
        """Escanea ``target`` (IP, CIDR o lista separada por comas) con nmap.

        Args:
            target: por ejemplo ``"192.168.1.0/24"`` o ``"192.168.1.1,192.168.1.2"``.

        Returns:
            Lista de diccionarios, uno por host activo, con ``source='nmap_scan'``.

        Raises:
            RuntimeError: si nmap (binario o librería) no está disponible.
        """
        nm = self._build_port_scanner()

        # nmap suele necesitar privilegios de root para -O (detección de SO).
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            print(
                "[AVISO] La detección de sistema operativo (-O) normalmente "
                "requiere privilegios de root. Ejecuta con 'sudo' si los "
                "resultados de SO aparecen vacíos."
            )

        arguments = "-sV -O --version-intensity 5"
        if self.verbose:
            print(f"[INFO] Ejecutando nmap sobre '{target}' con: {arguments}")

        try:
            nm.scan(hosts=target, arguments=arguments, timeout=self.timeout)
        except Exception as exc:  # PortScannerError, timeouts, etc.
            # Importamos aquí el tipo concreto solo para el mensaje.
            raise RuntimeError(
                f"Error durante el escaneo nmap de '{target}': {exc}"
            ) from exc

        hosts = nm.all_hosts()
        if not hosts:
            print("[AVISO] El escaneo no encontró hosts activos.")
            return []

        devices: list[dict] = []
        for host in hosts:
            if nm[host].state() != "up":
                continue
            devices.append(self._parse_host(nm, host))

        if self.verbose:
            print(f"[INFO] {len(devices)} host(s) activo(s) procesado(s).")
        return devices

    def _build_port_scanner(self):
        """Comprueba dependencias y devuelve una instancia de ``nmap.PortScanner``."""
        if shutil.which("nmap") is None:
            raise RuntimeError(
                "El binario 'nmap' no está instalado o no está en el PATH. "
                "Instálalo (macOS: 'brew install nmap', Debian/Ubuntu: "
                "'sudo apt install nmap') y vuelve a intentarlo. "
                "Para probar sin red real usa la opción --demo."
            )
        try:
            import nmap  # python-nmap; import perezoso
        except ImportError as exc:
            raise RuntimeError(
                "La librería 'python-nmap' no está instalada. "
                "Ejecuta 'pip install python-nmap'. "
                "Para probar sin red real usa la opción --demo."
            ) from exc

        try:
            return nmap.PortScanner()
        except Exception as exc:  # nmap.PortScannerError
            raise RuntimeError(
                f"No se pudo inicializar nmap.PortScanner: {exc}"
            ) from exc

    def _parse_host(self, nm, host: str) -> dict:
        """Extrae los campos relevantes de un host del resultado de nmap."""
        host_data = nm[host]

        # Hostname
        hostname = host_data.hostname() or "desconocido"

        # MAC y vendor (nmap los expone en 'addresses' y 'vendor')
        mac = host_data["addresses"].get("mac", "desconocida")
        vendor_map = host_data.get("vendor", {})
        vendor = vendor_map.get(mac, "desconocido")

        # IPv6
        ipv6_address = host_data["addresses"].get("ipv6")

        # Detección de SO
        os_detected, os_version = "desconocido", "desconocido"
        osmatches = host_data.get("osmatch", [])
        if osmatches:
            best = osmatches[0]
            os_detected = best.get("name", "desconocido")
            classes = best.get("osclass", [])
            if classes:
                os_version = classes[0].get("osgen", "desconocido") or "desconocido"

        # Puertos abiertos y TTL
        open_ports: list[int] = []
        ttl: Optional[int] = None
        for proto in host_data.all_protocols():
            for port in sorted(host_data[proto].keys()):
                port_info = host_data[proto][port]
                if port_info.get("state") == "open":
                    open_ports.append(int(port))
        # Algunos resultados exponen TTL en la sección 'status'
        ttl = host_data.get("status", {}).get("ttl")
        if ttl is not None:
            try:
                ttl = int(ttl)
            except (TypeError, ValueError):
                ttl = None

        return {
            "ip": host,
            "mac": mac,
            "hostname": hostname,
            "os_detected": os_detected,
            "os_version": os_version,
            "device_type": self._infer_device_type(os_detected, open_ports),
            "vendor": vendor,
            "open_ports": open_ports,
            "ipv6_address": ipv6_address,
            "ttl": ttl,
            "scan_timestamp": datetime.now().isoformat(timespec="seconds"),
            "source": "nmap_scan",
        }

    @staticmethod
    def _infer_device_type(os_detected: str, open_ports: list[int]) -> str:
        """Infiere el tipo de dispositivo a partir del SO y los puertos abiertos."""
        os_lower = (os_detected or "").lower()
        ports = set(open_ports)

        if any(k in os_lower for k in ("ios", "nx-os", "routeros", "junos")):
            return "router"
        if "arubaos" in os_lower or "switch" in os_lower:
            return "switch"
        if any(k in os_lower for k in ("fortios", "fortinet", "palo alto", "asa")):
            return "firewall"
        if 9100 in ports:  # puerto de impresión RAW
            return "printer"
        if any(k in os_lower for k in ("windows", "ubuntu", "centos", "debian", "linux")):
            return "server"
        return "iot"

    # ------------------------------------------------------------------ #
    #  Datos simulados (modo demo)
    # ------------------------------------------------------------------ #
    def load_mock_data(self, json_path: str) -> list[dict]:
        """Carga dispositivos simulados desde un JSON para el modo demo.

        Args:
            json_path: ruta al archivo ``mock_devices.json``.

        Returns:
            Lista de dispositivos con ``source='mock_data'`` añadido.

        Raises:
            FileNotFoundError: si el archivo no existe.
            ValueError: si el JSON no tiene el formato esperado.
        """
        if not os.path.isfile(json_path):
            raise FileNotFoundError(
                f"No se encontró el archivo de datos simulados: {json_path}"
            )

        with open(json_path, "r", encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"El archivo '{json_path}' no es un JSON válido: {exc}"
                ) from exc

        if not isinstance(data, list) or not data:
            raise ValueError(
                "El JSON de datos simulados debe ser una lista no vacía de dispositivos."
            )

        for idx, device in enumerate(data):
            if not isinstance(device, dict):
                raise ValueError(
                    f"El elemento #{idx} del mock no es un objeto JSON válido."
                )
            missing = REQUIRED_MOCK_FIELDS - device.keys()
            if missing:
                raise ValueError(
                    f"El dispositivo #{idx} ({device.get('ip', '?')}) carece de "
                    f"los campos obligatorios: {sorted(missing)}"
                )
            device["source"] = "mock_data"

        if self.verbose:
            print(f"[INFO] {len(data)} dispositivo(s) simulado(s) cargado(s).")
        return data
