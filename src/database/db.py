"""db.py — Engine, sessionmaker e inicialización de la base de datos.

SQLite por archivo único (decisión documentada en CLAUDE.md): sin servidor
separado, suficiente para el volumen de un diagnóstico puntual. SQLAlchemy
como ORM desde el principio para que migrar a PostgreSQL en una versión
multi-cliente sea cambio de configuración, no reescritura.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# La BD vive junto al resto de datos del proyecto (data/), un archivo único.
DB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
DB_PATH = os.path.join(DB_DIR, "ipv6_analyzer.db")
DB_URL = f"sqlite:///{DB_PATH}"

# check_same_thread=False permite que Streamlit (Bloque 3), que puede usar
# varios hilos, lea la misma conexión SQLite sin error.
engine = create_engine(
    DB_URL, echo=False, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Base declarativa de todos los modelos ORM."""


def init_db() -> str:
    """Crea el directorio de datos y todas las tablas si no existen.

    Returns:
        La ruta absoluta del archivo de base de datos.
    """
    os.makedirs(DB_DIR, exist_ok=True)
    # Importa los modelos para que queden registrados en Base.metadata antes
    # de create_all (import dentro de la función para evitar import circular).
    from src.database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    return DB_PATH
