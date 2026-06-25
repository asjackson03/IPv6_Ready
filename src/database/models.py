"""models.py — Modelos SQLAlchemy de IPv6 Ready Analyzer (Bloque 1).

Esquema basado en el brainstorm de arquitectura BD/portal ya documentado en
CLAUDE.md: refleja las 7 categorías del inventario de campo real de Andrés
(no inventa una taxonomía nueva) y su criticidad asociada.

Decisión de diseño para los campos anidados de topología (interfaces, dhcp,
enrutamiento, etc.): se guardan como JSON serializado (columnas Text) en vez
de re-normalizarse en tablas/columnas separadas. Esos campos ya vienen
estructurados y validados por OllamaClient (Módulo 3a) con un esquema fijo;
re-normalizarlos no aporta valor para un dashboard de solo lectura y sí
multiplica el riesgo. Para una versión multi-cliente post-LACNIC podría
valer la pena normalizar; hoy no.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.db import Base

# ---------------------------------------------------------------------------
#  Reglas de categoría y criticidad (definidas en CLAUDE.md, no inventadas)
# ---------------------------------------------------------------------------

# Heurística SIMPLIFICADA device_type (Módulo 1) -> categoría del inventario.
# No es exhaustiva: es la asignación pragmática para esta entrega, reutilizando
# los mismos tipos que produce _infer_device_type() del scanner. Una taxonomía
# más fina (ej. distinguir 'segmentos_de_red' por subred) queda como mejora.
DEVICE_TYPE_TO_CATEGORIA = {
    "router": "equipos_red_seguridad",
    "switch": "equipos_red_seguridad",
    "firewall": "equipos_red_seguridad",
    "server": "servidores",
    "printer": "perifericos",
    "iot": "perifericos",
}
# Cualquier device_type no listado arriba cae en esta categoría por defecto.
CATEGORIA_POR_DEFECTO = "equipos_finales"

# Criticidad por categoría (ajustada por Andrés en CLAUDE.md):
#   ALTA: segmentos_de_red, servidores, equipos_red_seguridad
#   BAJA: perifericos, equipos_finales
CATEGORIA_CRITICIDAD = {
    "segmentos_de_red": "alta",
    "servidores": "alta",
    "equipos_red_seguridad": "alta",
    "perifericos": "baja",
    "equipos_finales": "baja",
    "sedes": "alta",          # declaradas vía chat; relevantes para el negocio
    "aplicaciones": "alta",   # declaradas vía chat; relevantes para el negocio
}


def categoria_para_device_type(device_type: str | None) -> str:
    """Mapea un device_type del Módulo 1 a una de las 7 categorías."""
    return DEVICE_TYPE_TO_CATEGORIA.get(
        (device_type or "").lower(), CATEGORIA_POR_DEFECTO
    )


def criticidad_para_categoria(categoria: str | None) -> str:
    """Devuelve 'alta' o 'baja' según la categoría (fallback 'baja')."""
    return CATEGORIA_CRITICIDAD.get(categoria or "", "baja")


# ---------------------------------------------------------------------------
#  Tablas
# ---------------------------------------------------------------------------


class Scan(Base):
    """Una ejecución del Módulo 1 (discovery): metadatos + dispositivos."""

    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(512), nullable=True)

    devices: Mapped[list["Device"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )


class Device(Base):
    """Estado de un dispositivo descubierto por el Módulo 1 en un scan dado."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    os_detected: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Resultado del Módulo 1 (heurística IPv6).
    ipv6_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ipv6_status: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Resultado del Módulo 2 (clasificación ML), si se ejecutó.
    ml_classification: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    ml_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Taxonomía del inventario de campo (7 categorías) + criticidad.
    categoria: Mapped[str | None] = mapped_column(String(64), nullable=True)
    criticidad: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id"))
    scan: Mapped["Scan"] = relationship(back_populates="devices")


class TopologySession(Base):
    """Una sesión de levantamiento de topología (Módulo 3a)."""

    __tablename__ = "topology_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo_cliente: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cantidad_sedes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timestamp_inicio: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    timestamp_fin: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(512), nullable=True)

    devices: Mapped[list["TopologyDevice"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    roadmaps: Mapped[list["Roadmap"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class TopologyDevice(Base):
    """Un equipo de capa 3/seguridad estructurado por el Módulo 3a.

    Los campos anidados del esquema de OllamaClient se guardan como JSON
    serializado (ver propiedades ``*_dict`` para leerlos deserializados).
    """

    __tablename__ = "topology_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre_asignado: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    rol_logico: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vendor_declarado: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    modelo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version_so: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Campos anidados (JSON serializado en columnas Text).
    licencias_adicionales_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    interfaces_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    vlans_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    dhcp_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    enrutamiento_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    politicas_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notas_ambiguedad_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    ipv6_configurado: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    confianza_extraccion: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    es_firewall_sin_capa3: Mapped[bool] = mapped_column(
        Boolean, default=False
    )

    session_id: Mapped[int] = mapped_column(
        ForeignKey("topology_sessions.id")
    )
    session: Mapped["TopologySession"] = relationship(
        back_populates="devices"
    )

    # --- Helpers de (de)serialización de los campos JSON ----------------- #
    @staticmethod
    def _loads(raw: str | None):
        """Deserializa un campo JSON, devolviendo None si está vacío/ inválido."""
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None

    @property
    def interfaces(self) -> list:
        return self._loads(self.interfaces_json) or []

    @property
    def vlans_detectadas(self) -> list:
        return self._loads(self.vlans_json) or []

    @property
    def dhcp(self) -> dict:
        return self._loads(self.dhcp_json) or {}

    @property
    def enrutamiento(self) -> dict:
        return self._loads(self.enrutamiento_json) or {}

    @property
    def politicas(self) -> dict:
        return self._loads(self.politicas_json) or {}

    @property
    def licencias_adicionales(self) -> dict:
        return self._loads(self.licencias_adicionales_json) or {}

    @property
    def notas_ambiguedad(self) -> list:
        return self._loads(self.notas_ambiguedad_json) or []


class Roadmap(Base):
    """Un roadmap de migración generado por el Módulo 3c (Bloque 2)."""

    __tablename__ = "roadmaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contenido_markdown: Mapped[str] = mapped_column(Text)
    fecha_generacion: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    # Un roadmap puede asociarse a una sesión de topología y/o a un scan.
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("topology_sessions.id"), nullable=True
    )
    scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("scans.id"), nullable=True
    )
    session: Mapped["TopologySession | None"] = relationship(
        back_populates="roadmaps"
    )
