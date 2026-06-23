"""feature_extractor.py — Ingeniería de características para el Módulo 2.

Convierte el diccionario de un dispositivo (tal como lo produce el Módulo 1
tras :class:`IPv6Checker.evaluate_device`) en un vector numérico de 11
características que alimenta al clasificador Random Forest.

Cada característica está documentada explícitamente porque el criterio de
diseño del proyecto es la transparencia: igual que el scoring heurístico del
Módulo 1, aquí debe poder explicarse en la memoria del TFM POR QUÉ el modelo
ve lo que ve. El modelo es una caja gris, no negra: los datos de entrada son
auditables aunque la decisión final del bosque no lo sea por completo.

Conexión Módulo 1 ↔ Módulo 2: dos características (``os_score`` e
``ipv6_score_normalized``) se derivan directamente de la lógica experta del
Módulo 1, de modo que ambos módulos comparten el mismo criterio técnico y no
son sistemas aislados.
"""
from __future__ import annotations

import re

import numpy as np

from src.discovery.ipv6_checker import IPv6Checker


# Orden canónico de las 11 características. Debe coincidir exactamente con el
# orden en que extract_features rellena el vector — get_feature_names() es la
# fuente de verdad para interpretar feature_importances_ del modelo.
FEATURE_NAMES = [
    "os_score",
    "has_ipv6",
    "device_type_code",
    "port_count_normalized",
    "has_ssh",
    "has_https",
    "snmp_available",
    "firmware_modern",
    "ipv6_score_normalized",
    "ttl_normalized",
    "os_confidence_score",
]

# Mapeo tipo de dispositivo → código numérico (criticidad/relevancia de red).
DEVICE_TYPE_CODE = {
    "router": 5.0,
    "firewall": 5.0,
    "switch": 4.0,
    "server": 4.0,
    "printer": 2.0,
    "iot": 1.0,
}
DEVICE_TYPE_DEFAULT = 2.0  # "desconocido" u otro

# Mapeo de la confianza de la detección de SO (campo os_detection_method del
# Módulo 1) a un escalar 0-1. Ver docstring de la característica #11.
OS_CONFIDENCE = {
    "fingerprint": 1.0,
    "fingerprint_generico": 0.6,
    "service_info": 0.5,
    "ambiguo": 0.2,
    "ninguno": 0.1,
}
OS_CONFIDENCE_DEFAULT = 0.5  # valor no reconocido


class FeatureExtractor:
    """Transforma dispositivos en vectores de características numéricas."""

    def __init__(self):
        # Reutiliza las heurísticas del Módulo 1 (mismo criterio experto) para
        # clasificar el SO. No se duplica la lógica: se invoca la del checker.
        self._checker = IPv6Checker()

    def extract_features(self, device: dict) -> np.ndarray:
        """Devuelve el vector de 11 floats que describe un dispositivo.

        El orden de las posiciones es fijo y coincide con
        :data:`FEATURE_NAMES`. Cada característica está acotada a un rango
        conocido para que ninguna domine al modelo solo por su escala.

        Args:
            device: dispositivo (campos del Módulo 1).

        Returns:
            ``np.ndarray`` de shape ``(11,)`` y dtype float.
        """
        ports = set(device.get("open_ports") or [])

        features = [
            # 1. os_score (1-5): madurez del SO según el MISMO criterio experto
            #    del Módulo 1 (IPv6Checker._base_score), re-escalado a 1-5.
            self._os_score(device),
            # 2. has_ipv6: el dispositivo ya tiene una dirección IPv6 asignada.
            1.0 if device.get("ipv6_address") else 0.0,
            # 3. device_type_code (1-5): relevancia de red del tipo de equipo.
            DEVICE_TYPE_CODE.get(
                (device.get("device_type") or "").lower(), DEVICE_TYPE_DEFAULT
            ),
            # 4. port_count_normalized: nº de puertos abiertos / 10, tope 1.0.
            min(len(ports) / 10.0, 1.0),
            # 5. has_ssh: puerto 22 abierto (gestión moderna).
            1.0 if 22 in ports else 0.0,
            # 6. has_https: puerto 443 abierto (gestión web/TLS).
            1.0 if 443 in ports else 0.0,
            # 7. snmp_available: el dispositivo respondió SNMP.
            1.0 if device.get("snmp_available") else 0.0,
            # 8. firmware_modern: heurística sobre la versión de firmware.
            self._firmware_modern(device.get("firmware_version")),
            # 9. ipv6_score_normalized: el ipv6_score (0-100) del Módulo 1
            #    re-escalado a 0-1. CONEXIÓN CLAVE Módulo 1 → Módulo 2: el
            #    veredicto heurístico del módulo previo entra como feature.
            float(device.get("ipv6_score", 0)) / 100.0,
            # 10. ttl_normalized: ttl / 255 (pista débil de la familia de SO).
            (float(device["ttl"]) / 255.0) if device.get("ttl") is not None else 0.5,
            # 11. os_confidence_score: confianza del dato os_detected (ver abajo).
            OS_CONFIDENCE.get(
                device.get("os_detection_method"), OS_CONFIDENCE_DEFAULT
            ),
        ]
        return np.array(features, dtype=float)

    def get_feature_names(self) -> list[str]:
        """Devuelve los 11 nombres de característica en orden canónico."""
        return list(FEATURE_NAMES)

    def extract_batch(self, devices: list[dict]) -> np.ndarray:
        """Aplica :meth:`extract_features` a una lista de dispositivos.

        Args:
            devices: lista de N dispositivos.

        Returns:
            Matriz ``np.ndarray`` de shape ``(N, 11)``.
        """
        if not devices:
            return np.empty((0, len(FEATURE_NAMES)), dtype=float)
        return np.vstack([self.extract_features(d) for d in devices])

    # ------------------------------------------------------------------ #
    #  Características derivadas
    # ------------------------------------------------------------------ #
    def _os_score(self, device: dict) -> float:
        """Madurez del SO en escala 1-5.

        Reutiliza las heurísticas del Módulo 1
        (``IPv6Checker._is_modern_linux`` y ``IPv6Checker._extract_year``)
        para no divergir del criterio experto ya validado y documentado en
        el TFM. La escala 0-100 del Módulo 1 se condensa aquí a 1-5 porque
        el modelo solo necesita una señal ordinal de "qué tan moderno es el
        SO", no el puntaje completo (ese ya entra por la feature #9).
        """
        os_text = (
            f"{device.get('os_detected', '')} {device.get('os_version', '')}".lower()
        )

        # Linux moderno (Ubuntu 20+, CentOS 8+, Debian 10+): mismo criterio M1.
        if IPv6Checker._is_modern_linux(os_text):
            return 5.0
        # Linux legacy (cualquier otra variante Linux/embebida).
        if any(k in os_text for k in ("linux", "ubuntu", "centos", "debian", "busybox")):
            return 3.0
        # Windows: reutiliza el extractor de año del Módulo 1.
        if "windows" in os_text:
            year = IPv6Checker._extract_year(os_text)
            if year is not None and year >= 2016:
                return 4.0
            if year == 2012:
                return 2.0
            if year == 2008:
                return 1.0
            return 2.0
        # Cisco IOS-XE / NX-OS (soporte IPv6 sólido).
        if "ios-xe" in os_text or "nx-os" in os_text or "nxos" in os_text:
            return 4.0
        # Cisco IOS 15.x (legacy con soporte IPv6 razonable).
        if "ios" in os_text and re.search(r"\b15\.", os_text):
            return 3.0
        # Cisco IOS 12.x (legacy, soporte IPv6 pobre o nulo).
        if "ios" in os_text and re.search(r"\b12\.", os_text):
            return 1.0
        # Otros SO de equipos de red modernos.
        if any(k in os_text for k in ("junos", "fortios", "pan-os", "gaia", "arubaos")):
            return 4.0
        # SO desconocido: valor neutro.
        return 2.0

    @staticmethod
    def _firmware_modern(firmware) -> float:
        """Heurística de modernidad del firmware.

        Devuelve 1.0 si la versión arranca con un número >= 15 o contiene un
        año >= 2018; 0.5 si el firmware es desconocido (None); 0.0 en el resto.
        Es deliberadamente simple: el firmware viene en formatos muy dispares
        entre fabricantes, así que se castiga lo claramente antiguo sin
        intentar parsear cada esquema de versionado.
        """
        if firmware is None:
            return 0.5
        s = str(firmware)
        m = re.match(r"\s*(\d+)", s)
        if m and int(m.group(1)) >= 15:
            return 1.0
        y = re.search(r"(20\d{2})", s)
        if y and int(y.group(1)) >= 2018:
            return 1.0
        return 0.0
