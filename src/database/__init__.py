"""Paquete de persistencia (Bloque 1 — Base de datos).

Expone los modelos SQLAlchemy, el engine/sessionmaker y el importador de los
datos ya generados por los Módulos 1 (discovery) y 3a (topología). La capa de
base de datos formaliza las 7 categorías del inventario de campo de Andrés y
soporta el portal web de solo lectura (Bloque 3).
"""
from src.database.db import (
    Base,
    SessionLocal,
    engine,
    init_db,
)
from src.database.models import (
    Device,
    Roadmap,
    Scan,
    TopologyDevice,
    TopologySession,
)

__all__ = [
    "Base",
    "SessionLocal",
    "engine",
    "init_db",
    "Device",
    "Scan",
    "TopologyDevice",
    "TopologySession",
    "Roadmap",
]
