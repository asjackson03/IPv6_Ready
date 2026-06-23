"""scanner.py — Descubrimiento de hosts en la red.

Contiene :class:`NetworkScanner`, responsable de:
  * Escanear una red real mediante nmap (``scan_network``).
  * Cargar un inventario simulado para el modo demo (``load_mock_data``).

La dependencia ``python-nmap`` se importa de forma perezosa (dentro del
método que la usa) para que el modo demo funcione aunque la librería o el
binario ``nmap`` no estén instalados.
"""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

# Campos mínimos que debe contener cada dispositivo del mock para considerarse válido.
REQUIRED_MOCK_FIELDS = {
    "ip", "mac", "hostname", "os_detected", "os_version",
    "device_type", "vendor", "open_ports", "ipv6_address",
    "ttl", "snmp_available", "firmware_version",
}

# Tope máximo de timeout dinámico (segundos) para evitar esperas infinitas
# en rangos absurdamente grandes.
MAX_DYNAMIC_TIMEOUT = 1800

# Segundos estimados por host candidato, usados para el cálculo de timeout
# dinámico. Calibrados con evidencia real: "sudo nmap -sV -O
# --version-intensity 5 -n 192.168.68.0/24" (256 direcciones candidatas, 5
# hosts activos) tardó 815s ≈ 3.18s/host candidato. Se redondea al alza para
# dejar margen. Sin -O (--fast) el costo baja sustancialmente, ya que -O es
# la fase más lenta del escaneo.
SECONDS_PER_HOST_FULL = 4
SECONDS_PER_HOST_FAST = 1

# Precisión mínima (atributo 'accuracy' de <osmatch>) para confiar en el
# fingerprint de SO de nmap. nmap reporta "OS details" solo con accuracy=100
# y "Aggressive OS guesses" con valores menores. Por debajo de este umbral
# se descarta directamente y se recurre al fallback de 'Service Info'.
OSMATCH_MIN_ACCURACY = 80

# Margen de puntos de 'accuracy' bajo el mejor match dentro del cual otro
# osmatch se considera "candidato igualmente plausible" (no solo ruido).
#
# Evidencia real que motivó esto: un router TP-Link con firmware OpenWrt
# (192.168.68.1) devolvió 10 osmatches con el mejor en 88% — "Sony Blu-Ray
# Player" — pero con OTROS 9 candidatos a solo 1-3 puntos de distancia
# (Linux 5.10-5.15: 87%, MikroTik RouterOS: 86%, Linux 2.6.18/5.15/5.4/6.12:
# 86%, Sonos ZonePlayer: 85%, Linux 2.6.16 (fli4l): 85%, Dish Network
# Hopper: 85%). Tomar ciegamente osmatches[0] -aunque supere
# OSMATCH_MIN_ACCURACY- ignora que el "mejor" resultado está empatado
# dentro del ruido de medición con candidatos de dispositivos sin relación
# alguna entre sí: la precisión por sí sola no basta, hace falta mirar la
# dispersión del conjunto completo.
#
# OSMATCH_MIN_ACCURACY=80 y este margen de 5 puntos son heurísticas
# razonables basadas en ESTE caso de evidencia real, no en un análisis
# estadístico amplio sobre muchos dispositivos — es una limitación conocida
# del prototipo, documentada aquí y a trasladar a la memoria del TFM.
OSMATCH_ACCURACY_MARGIN = 5


class NetworkScanner:
    """Escáner de red basado en nmap con soporte de datos simulados."""

    def __init__(self, timeout: int = 30, verbose: bool = False, fast: bool = False):
        self.timeout = timeout
        self.verbose = verbose
        self.fast = fast

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

        num_hosts_estimados = self._estimate_host_count(target)

        # nmap suele necesitar privilegios de root para -O (detección de SO).
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            sudo_hint = (
                "[AVISO] La detección de sistema operativo (-O) normalmente "
                "requiere privilegios de root. Ejecuta con 'sudo' si los "
                "resultados de SO aparecen vacíos."
            )
            if num_hosts_estimados > 256 and not self.fast:
                sudo_hint += (
                    f" El rango objetivo tiene ~{num_hosts_estimados} hosts: "
                    "considera usar --fast para acelerar el escaneo (sacrifica "
                    "detección de SO)."
                )
            print(sudo_hint)

        # '-n' desactiva la resolución DNS inversa: con ella activa, un /24
        # con -O tardó 815s; sin ella, un /22 no llegó a completar tras 20+
        # minutos. Se aplica siempre, independientemente de --fast.
        arguments = (
            "-sV --version-intensity 2 -n" if self.fast else "-sV -O --version-intensity 5 -n"
        )

        effective_timeout = self._calculate_timeout(target, self.timeout, fast=self.fast)
        print(
            f"[INFO] Timeout efectivo para este escaneo: {effective_timeout}s "
            f"(base={self.timeout}s, hosts estimados={num_hosts_estimados})."
        )

        if self.verbose:
            print(f"[INFO] Ejecutando nmap sobre '{target}' con: {arguments}")

        try:
            nm.scan(hosts=target, arguments=arguments, timeout=effective_timeout)
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

    @staticmethod
    def _estimate_host_count(target: str) -> int:
        """Estima el número de hosts de ``target`` (CIDR, IP única o lista por comas)."""
        target = target.strip()
        if "," in target:
            return sum(NetworkScanner._estimate_host_count(t) for t in target.split(","))
        try:
            if "/" in target:
                return ipaddress.ip_network(target, strict=False).num_addresses
            ipaddress.ip_address(target)
            return 1
        except ValueError:
            # Target no parseable como IP/CIDR (p.ej. hostname): se asume un solo host.
            return 1

    @classmethod
    def _calculate_timeout(cls, target: str, base_timeout: int, fast: bool = False) -> int:
        """Calcula el timeout efectivo según el tamaño estimado del rango objetivo.

        Fórmula: timeout_efectivo = max(base_timeout, num_hosts_estimados *
        segundos_por_host), acotado a ``MAX_DYNAMIC_TIMEOUT`` segundos para
        evitar esperas infinitas en rangos absurdamente grandes. El
        multiplicador (``SECONDS_PER_HOST_FULL``/``SECONDS_PER_HOST_FAST``)
        está calibrado con evidencia real de escaneo (ver definición de las
        constantes). Para una IP única el timeout no cambia respecto al base
        (num_hosts_estimados == 1).
        """
        num_hosts = cls._estimate_host_count(target)
        seconds_per_host = SECONDS_PER_HOST_FAST if fast else SECONDS_PER_HOST_FULL
        return min(max(base_timeout, num_hosts * seconds_per_host), MAX_DYNAMIC_TIMEOUT)

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

        # MAC y vendor (nmap los expone en 'addresses' y 'vendor').
        # python-nmap (0.7.1) construye ambos a partir del mismo atributo XML
        # <address addrtype="mac" addr="..." vendor="..."/>, así que la clave
        # de 'vendor' coincide exactamente con 'addresses["mac"]' (confirmado
        # parseando una salida XML real de ejemplo). Aun así, se normaliza a
        # mayúsculas como salvaguarda ante binarios/versiones de nmap que
        # formateen la MAC en distinto cuerpo de letra.
        mac = host_data["addresses"].get("mac", "desconocida")
        vendor_map = host_data.get("vendor", {})
        vendor_map_norm = {k.upper(): v for k, v in vendor_map.items()}
        vendor = vendor_map_norm.get(mac.upper(), "desconocido")

        # IPv6
        ipv6_address = host_data["addresses"].get("ipv6")

        # Detección de SO: 1) fingerprint de nmap (-O), resuelto considerando
        # la dispersión entre TODOS los osmatch candidatos (ver
        # _resolve_os_match y el comentario de OSMATCH_ACCURACY_MARGIN);
        # 2) si no hubo ningún match, 'Service Info' (ostype del <service>
        # detectado por -sV, no expuesto por python-nmap: se relee del XML
        # crudo); 3) si tampoco hay nada, queda explícitamente "desconocido".
        osmatches = host_data.get("osmatch", [])
        os_detected, os_version, os_detection_method = self._resolve_os_match(osmatches)
        if os_detection_method == "ninguno":
            service_hint = self._extract_service_os_hint(nm, host)
            if service_hint:
                os_detected = service_hint
                os_detection_method = "service_info"

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
            "os_detection_method": os_detection_method,
            "device_type": self._infer_device_type(os_detected, open_ports),
            "vendor": vendor,
            "open_ports": open_ports,
            "ipv6_address": ipv6_address,
            "ttl": ttl,
            "scan_timestamp": datetime.now().isoformat(timespec="seconds"),
            "source": "nmap_scan",
        }

    @staticmethod
    def _osmatch_accuracy(osmatch: dict) -> int:
        """Parsea 'accuracy' de un osmatch de forma segura (0 si falta/inválido)."""
        try:
            return int(osmatch.get("accuracy", 0))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _resolve_os_match(cls, osmatches: list) -> tuple[str, str, str]:
        """Resuelve el SO a partir de TODOS los osmatch, no solo el mejor.

        Devuelve ``(os_detected, os_version, os_detection_method)`` con
        ``os_detection_method`` en {"ninguno", "ambiguo", "fingerprint",
        "fingerprint_generico"}. Ver el comentario de
        ``OSMATCH_ACCURACY_MARGIN`` para la evidencia real que motiva esta
        lógica: confiar ciegamente en ``osmatches[0]`` no basta cuando hay
        otros candidatos casi igual de "buenos" pero sin relación entre sí.
        """
        if not osmatches:
            return "desconocido", "desconocido", "ninguno"

        sorted_matches = sorted(osmatches, key=cls._osmatch_accuracy, reverse=True)
        best = sorted_matches[0]
        best_accuracy = cls._osmatch_accuracy(best)

        if best_accuracy < OSMATCH_MIN_ACCURACY:
            return "desconocido", "desconocido", "ninguno"

        # Candidatos "casi igual de buenos" que el mejor: si hay más de uno,
        # el mejor accuracy por sí solo no es prueba suficiente.
        close_matches = [
            m for m in sorted_matches
            if cls._osmatch_accuracy(m) >= best_accuracy - OSMATCH_ACCURACY_MARGIN
        ]

        if len(close_matches) == 1:
            os_version = "desconocido"
            classes = best.get("osclass", [])
            if classes:
                os_version = classes[0].get("osgen", "desconocido") or "desconocido"
            return best.get("name", "desconocido"), os_version, "fingerprint"

        names = [m.get("name", "") or "" for m in close_matches]
        if all("linux" in name.lower() for name in names):
            return "Linux", "desconocido", "fingerprint_generico"

        # Candidatos cercanos pero heterogéneos (p.ej. Blu-Ray + MikroTik +
        # Sonos + Dish Network): ningún nombre individual es confiable.
        return "desconocido", "desconocido", "ambiguo"

    @staticmethod
    def _extract_service_os_hint(nm, host: str) -> Optional[str]:
        """Extrae el 'ostype' de 'Service Info' leyendo el XML crudo de nmap.

        python-nmap no expone el atributo 'ostype'/'devicetype' del elemento
        <service> (solo name/product/version/extrainfo/conf/cpe), así que se
        relee ``nm.get_nmap_last_output()`` con ElementTree para recuperarlo.
        """
        raw_xml = nm.get_nmap_last_output()
        if not raw_xml:
            return None
        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError:
            return None

        for dhost in root.findall("host"):
            is_target = any(
                addr.get("addrtype") == "ipv4" and addr.get("addr") == host
                for addr in dhost.findall("address")
            )
            if not is_target:
                continue
            for service in dhost.findall("ports/port/service"):
                ostype = service.get("ostype")
                if ostype:
                    return ostype
            break
        return None

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
            # En el mock el SO viene declarado directamente (no detectado),
            # se trata como el caso de mayor confianza para que el resumen
            # de calidad de identificación no penalice los datos simulados.
            device["os_detection_method"] = "fingerprint"

        if self.verbose:
            print(f"[INFO] {len(data)} dispositivo(s) simulado(s) cargado(s).")
        return data
