"""data_access.py — Capa de lectura de la BD para el portal (Bloque 3).

Devuelve estructuras planas (DataFrames, dicts, listas de dicts) en vez de
objetos ORM, para que sean cacheables por Streamlit y desacoplen el frontend
del esquema de SQLAlchemy.
"""
from __future__ import annotations

import os

import pandas as pd
from sqlalchemy import select

from src.database.db import DB_PATH, SessionLocal
from src.database.models import (
    Device,
    Roadmap,
    Scan,
    TopologyDevice,
    TopologySession,
)


def db_existe() -> bool:
    """¿Existe el archivo de base de datos? (para avisar si falta --init-db)."""
    return os.path.isfile(DB_PATH)


def listar_scans() -> list[dict]:
    """Lista los scans (id, etiqueta legible, target, modo, nº dispositivos)."""
    with SessionLocal() as s:
        scans = s.scalars(
            select(Scan).order_by(Scan.timestamp.desc(), Scan.id.desc())
        ).all()
        salida = []
        for sc in scans:
            ts = sc.timestamp.strftime("%Y-%m-%d %H:%M") if sc.timestamp else "?"
            salida.append({
                "id": sc.id,
                "etiqueta": f"#{sc.id} · {ts} · {sc.target or 's/target'} "
                            f"({sc.modo or '?'})",
                "target": sc.target,
                "modo": sc.modo,
                "n_dispositivos": len(sc.devices),
            })
        return salida


def devices_de_scan(scan_id: int) -> pd.DataFrame:
    """DataFrame de los dispositivos de un scan."""
    with SessionLocal() as s:
        scan = s.get(Scan, scan_id)
        if scan is None:
            return pd.DataFrame()
        filas = [{
            "IP": d.ip,
            "Hostname": d.hostname,
            "Tipo": d.device_type,
            "Vendor": d.vendor,
            "SO detectado": d.os_detected,
            "Score IPv6": d.ipv6_score,
            "Estado IPv6": d.ipv6_status,
            "Clasificación ML": d.ml_classification,
            "Confianza ML": d.ml_confidence,
            "Categoría": d.categoria,
            "Criticidad": d.criticidad,
        } for d in scan.devices]
        return pd.DataFrame(filas)


def listar_topology_sessions() -> list[dict]:
    """Lista las sesiones de topología (id, etiqueta, perfil, nº equipos)."""
    with SessionLocal() as s:
        sesiones = s.scalars(
            select(TopologySession).order_by(TopologySession.id.desc())
        ).all()
        salida = []
        for ses in sesiones:
            inicio = ses.timestamp_inicio or "?"
            salida.append({
                "id": ses.id,
                "etiqueta": f"#{ses.id} · {inicio} · {ses.tipo_cliente or '?'} "
                            f"({len(ses.devices)} equipos)",
                "tipo_cliente": ses.tipo_cliente,
                "cantidad_sedes": ses.cantidad_sedes,
                "n_equipos": len(ses.devices),
            })
        return salida


def equipos_de_topology_session(session_id: int) -> list[dict]:
    """Equipos de una sesión de topología, ordenados para agrupar firewall+core.

    Mantiene el orden de inserción (que ya agrupa el firewall complementario
    justo tras su switch core) y expone es_firewall_sin_capa3 para que la UI
    pueda indentar/agrupar visualmente igual que el CLI.
    """
    with SessionLocal() as s:
        ses = s.get(TopologySession, session_id)
        if ses is None:
            return []
        salida = []
        for d in ses.devices:
            salida.append({
                "id": d.id,
                "nombre": d.nombre_asignado or d.modelo or "equipo",
                "rol_logico": d.rol_logico,
                "modelo": d.modelo,
                "version_so": d.version_so,
                "vendor": d.vendor_declarado,
                "interfaces": d.interfaces,
                "vlans": d.vlans_detectadas,
                "dhcp": d.dhcp,
                "enrutamiento": d.enrutamiento,
                "politicas": d.politicas,
                "licencias": d.licencias_adicionales,
                "ipv6_configurado": d.ipv6_configurado,
                "confianza": d.confianza_extraccion,
                "notas": d.notas_ambiguedad,
                "es_firewall_sin_capa3": d.es_firewall_sin_capa3,
            })
        return salida


def info_topology_session(session_id: int) -> dict:
    """Metadatos de cabecera de una sesión de topología."""
    with SessionLocal() as s:
        ses = s.get(TopologySession, session_id)
        if ses is None:
            return {}
        return {
            "tipo_cliente": ses.tipo_cliente,
            "cantidad_sedes": ses.cantidad_sedes,
            "timestamp_inicio": ses.timestamp_inicio,
            "timestamp_fin": ses.timestamp_fin,
        }


def ultimo_roadmap() -> dict | None:
    """Devuelve el roadmap más reciente (contenido + fecha) o None."""
    with SessionLocal() as s:
        rm = s.scalars(
            select(Roadmap).order_by(
                Roadmap.fecha_generacion.desc(), Roadmap.id.desc()
            )
        ).first()
        if rm is None:
            return None
        return {
            "id": rm.id,
            "contenido_markdown": rm.contenido_markdown,
            "fecha_generacion": rm.fecha_generacion,
        }


def resumen_para_chat() -> str:
    """Resumen compacto de la BD para anclar el chat a datos reales."""
    with SessionLocal() as s:
        scan = s.scalars(
            select(Scan).order_by(Scan.timestamp.desc(), Scan.id.desc())
        ).first()
        if scan is None:
            return "No hay datos de descubrimiento en la base de datos."
        por_estado: dict[str, int] = {}
        criticos = []
        for d in scan.devices:
            por_estado[d.ipv6_status or "?"] = por_estado.get(d.ipv6_status or "?", 0) + 1
            if d.criticidad == "alta":
                criticos.append(f"{d.hostname or 's/n'} ({d.ip}, {d.ipv6_status})")
        lineas = [
            f"Dispositivos en el último scan: {len(scan.devices)}.",
            "Estado IPv6: " + ", ".join(f"{k}={v}" for k, v in sorted(por_estado.items())),
        ]
        if criticos:
            lineas.append("Equipos críticos: " + "; ".join(criticos))
        return "\n".join(lineas)
