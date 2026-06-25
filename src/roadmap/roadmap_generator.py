"""roadmap_generator.py — Generador de roadmap de migración (Módulo 3c).

Combina las cuatro fuentes del proyecto para producir el plan de migración:
  · Módulo 1 (discovery)  — dispositivos y su estado IPv6, desde la BD.
  · Módulo 2 (clasificación ML) — etiqueta LISTO/ACTUALIZABLE/... por equipo.
  · Módulo 3a (topología) — rol lógico real, VLANs, protocolos, políticas.
  · RAG — fragmentos de buenas prácticas relevantes a los vendors detectados.

Aplica el mismo principio de doble capa del resto del proyecto (ver los 6 bugs
del Módulo 3a en CLAUDE.md): (a) el prompt instruye explícitamente "no inventes
hallazgos fuera del contexto", y (b) una validación determinista posterior
verifica que el roadmap mencione por nombre/IP a los equipos críticos reales,
agregando un aviso transparente si el modelo los omitió.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from src.database.db import SessionLocal
from src.database.models import (
    Device,
    Roadmap,
    Scan,
    TopologyDevice,
    TopologySession,
)
from src.roadmap.ollama_client import OllamaClient
from src.roadmap.rag_knowledge_base import RAGKnowledgeBase


class RoadmapGenerator:
    """Genera y persiste un roadmap de migración IPv6 desde la BD + RAG + LLM."""

    def __init__(self, session=None, ollama: OllamaClient | None = None,
                 knowledge_base: RAGKnowledgeBase | None = None):
        self._external_session = session is not None
        self.session = session or SessionLocal()
        self.ollama = ollama or OllamaClient()
        self.kb = knowledge_base or RAGKnowledgeBase()

    # ------------------------------------------------------------------ #
    #  API principal
    # ------------------------------------------------------------------ #
    def generate(self, scan_id: int | None = None,
                 topology_session_id: int | None = None) -> Roadmap:
        """Genera el roadmap y lo guarda en la tabla ``roadmaps``.

        Args:
            scan_id: scan del Módulo 1 a usar (el más reciente si es None).
            topology_session_id: sesión de topología a usar (la más reciente
                si es None).

        Returns:
            El objeto :class:`Roadmap` ya persistido.

        Raises:
            RuntimeError: si no hay datos en la BD para generar el roadmap, o
                si el servicio Ollama no está disponible.
        """
        scan = self._resolver_scan(scan_id)
        topo = self._resolver_topologia(topology_session_id)

        if scan is None and topo is None:
            raise RuntimeError(
                "No hay datos en la base de datos para generar el roadmap. "
                "Ejecuta primero 'python main.py --init-db' (y, opcionalmente, "
                "un levantamiento de topología con --topology)."
            )

        devices = scan.devices if scan else []
        topo_devices = topo.devices if topo else []

        resumen_discovery = self._resumir_discovery(devices)
        resumen_topologia = self._resumir_topologia(topo, topo_devices)
        fragmentos = self._recuperar_contexto_rag(devices, topo_devices)

        prompt = self._construir_prompt(
            resumen_discovery, resumen_topologia, fragmentos
        )
        contenido = self.ollama.generate_text(prompt).strip()

        # Validación determinista posterior: ¿el roadmap nombra a los equipos
        # críticos reales? Si no, se añade un anexo transparente.
        contenido = self._anexar_criticos_omitidos(contenido, devices)

        roadmap = Roadmap(
            contenido_markdown=contenido,
            fecha_generacion=datetime.utcnow(),
            session_id=topo.id if topo else None,
            scan_id=scan.id if scan else None,
        )
        self.session.add(roadmap)
        self.session.commit()
        return roadmap

    def close(self) -> None:
        """Cierra la sesión si la abrió este generador (no la inyectada)."""
        if not self._external_session:
            self.session.close()

    # ------------------------------------------------------------------ #
    #  Resolución de fuentes en la BD
    # ------------------------------------------------------------------ #
    def _resolver_scan(self, scan_id: int | None) -> Scan | None:
        if scan_id is not None:
            return self.session.get(Scan, scan_id)
        return self.session.scalars(
            select(Scan).order_by(Scan.timestamp.desc(), Scan.id.desc())
        ).first()

    def _resolver_topologia(self, session_id: int | None) -> TopologySession | None:
        if session_id is not None:
            return self.session.get(TopologySession, session_id)
        return self.session.scalars(
            select(TopologySession).order_by(TopologySession.id.desc())
        ).first()

    # ------------------------------------------------------------------ #
    #  Resúmenes de contexto (texto determinista para el prompt)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resumir_discovery(devices: list[Device]) -> str:
        """Texto compacto del inventario por estado IPv6, categoría y ML."""
        if not devices:
            return "No hay datos de descubrimiento de red disponibles."

        por_estado: dict[str, int] = {}
        por_categoria: dict[str, int] = {}
        por_ml: dict[str, int] = {}
        for d in devices:
            por_estado[d.ipv6_status or "DESCONOCIDO"] = \
                por_estado.get(d.ipv6_status or "DESCONOCIDO", 0) + 1
            por_categoria[d.categoria or "sin_categoria"] = \
                por_categoria.get(d.categoria or "sin_categoria", 0) + 1
            if d.ml_classification:
                por_ml[d.ml_classification] = por_ml.get(d.ml_classification, 0) + 1

        lineas = [f"Total de dispositivos descubiertos: {len(devices)}."]
        lineas.append("Distribución por estado IPv6: " + ", ".join(
            f"{k}={v}" for k, v in sorted(por_estado.items())))
        lineas.append("Distribución por categoría de inventario: " + ", ".join(
            f"{k}={v}" for k, v in sorted(por_categoria.items())))
        if por_ml:
            lineas.append("Clasificación ML (Módulo 2): " + ", ".join(
                f"{k}={v}" for k, v in sorted(por_ml.items())))

        # Lista explícita de equipos críticos (alta criticidad) por nombre/IP:
        # son los que el roadmap DEBE nombrar.
        criticos = [d for d in devices if d.criticidad == "alta"]
        if criticos:
            lineas.append("\nEquipos CRÍTICOS (alta prioridad) — deben citarse "
                          "explícitamente en el roadmap:")
            for d in criticos:
                lineas.append(
                    f"  - {d.hostname or 'sin-nombre'} ({d.ip}) | "
                    f"{d.device_type} {d.vendor or ''} | "
                    f"estado IPv6: {d.ipv6_status} (score {d.ipv6_score})"
                    + (f" | ML: {d.ml_classification}" if d.ml_classification else "")
                )
        return "\n".join(lineas)

    @staticmethod
    def _resumir_topologia(topo: TopologySession | None,
                           topo_devices: list[TopologyDevice]) -> str:
        """Texto compacto del levantamiento de topología (rol, VLANs, etc.)."""
        if topo is None or not topo_devices:
            return "No hay datos de levantamiento de topología disponibles."

        lineas = [
            f"Perfil del cliente: {topo.tipo_cliente or 'desconocido'}, "
            f"cantidad de sedes: {topo.cantidad_sedes if topo.cantidad_sedes is not None else 'no declarada'}."
        ]
        for d in topo_devices:
            protocolos = ", ".join(
                d.enrutamiento.get("protocolos_detectados", []) or []) or "ninguno"
            politicas = d.politicas
            nota_fw = " (firewall complementario, sin capa 3)" \
                if d.es_firewall_sin_capa3 else ""
            lineas.append(
                f"  - {d.nombre_asignado or d.modelo or 'equipo'}{nota_fw}: "
                f"rol={d.rol_logico}, modelo={d.modelo or 'n/d'}, "
                f"VLANs={len(d.vlans_detectadas)}, protocolos=[{protocolos}], "
                f"políticas declaradas={politicas.get('cantidad_total_declaradas', 0)} "
                f"(activas={politicas.get('cantidad_activas', 0)}), "
                f"IPv6 ya configurado={'sí' if d.ipv6_configurado else 'no'}, "
                f"confianza={d.confianza_extraccion}"
            )
        return "\n".join(lineas)

    def _recuperar_contexto_rag(self, devices: list[Device],
                                topo_devices: list[TopologyDevice]) -> list[str]:
        """Construye queries con los vendors/tecnologías reales y consulta el RAG."""
        terminos: set[str] = set()
        for d in devices:
            if d.vendor:
                terminos.add(d.vendor)
            if d.os_detected:
                terminos.add(d.os_detected)
        for d in topo_devices:
            if d.vendor_declarado:
                terminos.add(d.vendor_declarado)
            for proto in (d.enrutamiento.get("protocolos_detectados") or []):
                terminos.add(proto)

        query = " ".join(sorted(terminos)) + " IPv6 migración dual-stack"
        fragmentos = self.kb.search(query, top_k=3)
        # Si la query combinada no recupera nada, intenta una genérica.
        if not fragmentos:
            fragmentos = self.kb.search("IPv6 dual-stack migración roadmap", top_k=3)
        return fragmentos

    # ------------------------------------------------------------------ #
    #  Prompt + validación posterior
    # ------------------------------------------------------------------ #
    @staticmethod
    def _construir_prompt(resumen_discovery: str, resumen_topologia: str,
                          fragmentos: list[str]) -> str:
        contexto_rag = "\n\n".join(
            f"[Fragmento de referencia {i + 1}]\n{frag}"
            for i, frag in enumerate(fragmentos)
        ) or "(sin fragmentos de referencia recuperados)"

        return (
            "Eres un consultor experto en redes especializado en migración a "
            "IPv6. Tu tarea es redactar un ROADMAP de migración a IPv6 para una "
            "organización, en español, en formato Markdown.\n\n"
            "REGLAS ESTRICTAS (obligatorias):\n"
            "- Basa el roadmap ÚNICAMENTE en los datos proporcionados abajo. "
            "NO inventes dispositivos, hallazgos, marcas, ni cantidades que no "
            "estén en el contexto. Si un dato no está, no lo afirmes.\n"
            "- Cita explícitamente por nombre o IP a los equipos marcados como "
            "CRÍTICOS en el contexto de descubrimiento.\n"
            "- Usa los fragmentos de referencia como apoyo de buenas prácticas, "
            "pero no copies especificaciones de producto que no estén en el "
            "contexto de datos del cliente.\n"
            "- Sé concreto y accionable; evita relleno genérico.\n\n"
            "ESTRUCTURA ESPERADA DEL ROADMAP (usa encabezados Markdown):\n"
            "# Roadmap de migración a IPv6\n"
            "## 1. Resumen ejecutivo\n"
            "## 2. Estado actual de la red (según el diagnóstico)\n"
            "## 3. Equipos críticos y su tratamiento\n"
            "## 4. Fases de migración (con prioridades)\n"
            "## 5. Riesgos y recomendaciones\n\n"
            "===== CONTEXTO: DESCUBRIMIENTO DE RED (Módulos 1 y 2) =====\n"
            f"{resumen_discovery}\n\n"
            "===== CONTEXTO: TOPOLOGÍA LEVANTADA (Módulo 3a) =====\n"
            f"{resumen_topologia}\n\n"
            "===== CONTEXTO: BUENAS PRÁCTICAS (RAG) =====\n"
            f"{contexto_rag}\n\n"
            "Redacta ahora el roadmap completo en Markdown, siguiendo las "
            "reglas estrictas anteriores."
        )

    @staticmethod
    def _anexar_criticos_omitidos(contenido: str, devices: list[Device]) -> str:
        """Verifica que el roadmap nombre a los equipos críticos reales.

        Segunda capa determinista (mismo patrón del Módulo 3a): si el modelo
        omitió equipos de alta criticidad, no se asume que estén cubiertos —
        se añade un anexo transparente listándolos para revisión manual, en
        vez de dejar un roadmap silenciosamente incompleto.
        """
        criticos = [d for d in devices if d.criticidad == "alta"]
        if not criticos:
            return contenido

        texto_lower = contenido.lower()
        omitidos = []
        for d in criticos:
            ip = (d.ip or "").lower()
            hostname = (d.hostname or "").lower()
            # Se considera "mencionado" si aparece su IP o su hostname.
            mencionado = (ip and ip in texto_lower) or \
                         (hostname and hostname in texto_lower)
            if not mencionado:
                omitidos.append(d)

        if not omitidos:
            return contenido

        anexo = [
            "\n\n---\n",
            "## Anexo automático — equipos críticos a verificar\n",
            "_Esta sección se añadió de forma determinista: los siguientes "
            "equipos de **alta criticidad** estaban en el diagnóstico pero no "
            "fueron citados explícitamente por el modelo en el roadmap. Se "
            "listan para asegurar su revisión manual (no se omiten en "
            "silencio):_\n",
        ]
        for d in omitidos:
            anexo.append(
                f"- **{d.hostname or 'sin-nombre'}** ({d.ip}) — "
                f"{d.device_type} {d.vendor or ''}, estado IPv6: "
                f"{d.ipv6_status} (score {d.ipv6_score})."
            )
        return contenido + "\n".join(anexo)
