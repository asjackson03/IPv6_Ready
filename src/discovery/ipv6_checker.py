"""ipv6_checker.py — Evaluación heurística de compatibilidad IPv6.

Contiene :class:`IPv6Checker`, que asigna a cada dispositivo un puntaje
``ipv6_score`` (0-100), un ``ipv6_status`` y una recomendación básica.

El modelo de puntuación es una heurística académica documentada y
totalmente transparente (ver método :meth:`evaluate_device`).
"""
from __future__ import annotations

import re
from datetime import datetime


# Umbrales de clasificación según el puntaje final.
STATUS_THRESHOLDS = [
    (80, "COMPATIBLE"),
    (50, "PARCIAL"),
    (20, "REQUIERE_UPGRADE"),
    (0, "INCOMPATIBLE"),
]

RECOMENDACIONES = {
    "COMPATIBLE": "Listo para IPv6: habilitar y monitorizar el doble stack.",
    "PARCIAL": "Soporta IPv6 parcialmente: revisar configuración y activar servicios faltantes.",
    "REQUIERE_UPGRADE": "Requiere actualización de SO/firmware antes de migrar a IPv6.",
    "INCOMPATIBLE": "Sin soporte viable de IPv6: planificar reemplazo del dispositivo.",
}


class IPv6Checker:
    """Calcula la madurez IPv6 de un dispositivo mediante una heurística."""

    def __init__(self):
        pass

    def evaluate_device(self, device: dict) -> dict:
        """Evalúa un dispositivo y le añade los campos de diagnóstico IPv6.

        Args:
            device: diccionario con la información del dispositivo.

        Returns:
            El mismo diccionario enriquecido con ``ipv6_score``,
            ``ipv6_status``, ``recomendacion_basica`` y ``evaluated_at``.
        """
        score = self._base_score(device)
        score += self._bonus(device)
        score += self._penalties(device)

        score = min(100, max(0, score))
        status = self._status_from_score(score)

        enriched = dict(device)
        enriched["ipv6_score"] = score
        enriched["ipv6_status"] = status
        enriched["recomendacion_basica"] = RECOMENDACIONES[status]
        enriched["evaluated_at"] = datetime.now().isoformat(timespec="seconds")
        return enriched

    # ------------------------------------------------------------------ #
    #  Componentes del puntaje
    # ------------------------------------------------------------------ #
    def _base_score(self, device: dict) -> int:
        """Puntaje base según el sistema operativo detectado."""
        os_text = f"{device.get('os_detected', '')} {device.get('os_version', '')}".lower()

        # --- Linux moderno: Ubuntu 20+, CentOS 8+, Debian 10+ -------------
        if self._is_modern_linux(os_text):
            return 50

        # --- Windows Server 2016+ ----------------------------------------
        if "windows" in os_text:
            year = self._extract_year(os_text)
            if year is not None and year >= 2016:
                return 45
            if year is not None and year in (2008, 2012):
                return 25
            # Windows sin año reconocible: tratado como desconocido.
            return 20

        # --- Cisco IOS-XE / NX-OS ----------------------------------------
        if "ios-xe" in os_text or "nx-os" in os_text or "nxos" in os_text:
            return 45

        # --- Cisco IOS 12.x (legacy) -------------------------------------
        if "ios" in os_text and re.search(r"\b12\.", os_text):
            return 15

        # --- Resto: SO desconocido ---------------------------------------
        return 20

    def _bonus(self, device: dict) -> int:
        """Bonificaciones por características favorables a IPv6."""
        bonus = 0
        ports = set(device.get("open_ports") or [])

        if device.get("ipv6_address"):
            bonus += 35
        if 443 in ports:
            bonus += 5
        if 22 in ports:
            bonus += 5
        if device.get("snmp_available"):
            bonus += 5
        return bonus

    def _penalties(self, device: dict) -> int:
        """Penalizaciones por tipo de dispositivo o firmware antiguo."""
        penalty = 0
        device_type = (device.get("device_type") or "").lower()
        firmware = str(device.get("firmware_version") or "")

        if device_type == "iot":
            penalty -= 20
        if device_type == "printer":
            penalty -= 15
        # Firmware muy antiguo (familia 12.x o anterior).
        if re.match(r"^(0?\d|1[0-2])\.", firmware):
            penalty -= 10
        return penalty

    # ------------------------------------------------------------------ #
    #  Utilidades
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_modern_linux(os_text: str) -> bool:
        """True si el SO es Ubuntu 20+, CentOS 8+ o Debian 10+."""
        # Ubuntu 20.04+ (año >= 20)
        m = re.search(r"ubuntu.*?(\d{2})\.\d{2}", os_text)
        if m and int(m.group(1)) >= 20:
            return True
        # CentOS 8+
        m = re.search(r"centos\D*(\d+)", os_text)
        if m and int(m.group(1)) >= 8:
            return True
        # Debian 10+
        m = re.search(r"debian\D*(\d+)", os_text)
        if m and int(m.group(1)) >= 10:
            return True
        return False

    @staticmethod
    def _extract_year(os_text: str) -> int | None:
        """Extrae un año de versión de Windows Server (2008-2025)."""
        m = re.search(r"\b(20\d{2})\b", os_text)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _status_from_score(score: int) -> str:
        """Traduce un puntaje numérico a una etiqueta de estado."""
        for threshold, label in STATUS_THRESHOLDS:
            if score >= threshold:
                return label
        return "INCOMPATIBLE"
