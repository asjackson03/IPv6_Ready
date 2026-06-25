"""Pruebas del Módulo 3c: RAG + generador de roadmap (Bloque 2).

Mockean Ollama (mismo patrón que test_ollama_client.py): NO llaman al servicio
real. Usan una BD SQLite en memoria sembrada con datos de fixture.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
from src.database.models import Device, Roadmap, Scan
from src.roadmap.rag_knowledge_base import RAGKnowledgeBase
from src.roadmap.roadmap_generator import RoadmapGenerator


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture
def scan_sembrado(session):
    """Crea un scan con un equipo crítico y uno no crítico."""
    scan = Scan(target="192.168.1.0/24", modo="demo")
    scan.devices.append(Device(
        ip="192.168.1.1", hostname="rtr-core-bogota", device_type="router",
        vendor="Cisco", os_detected="Cisco IOS-XE Software",
        ipv6_score=95, ipv6_status="COMPATIBLE",
        ml_classification="LISTO", ml_confidence=0.9,
        categoria="equipos_red_seguridad", criticidad="alta",
    ))
    scan.devices.append(Device(
        ip="192.168.1.20", hostname="impresora-rrhh", device_type="printer",
        vendor="HP", os_detected="HP Embedded Web Server",
        ipv6_score=5, ipv6_status="INCOMPATIBLE",
        categoria="perifericos", criticidad="baja",
    ))
    session.add(scan)
    session.commit()
    return scan


class FakeOllama:
    """Doble de OllamaClient: devuelve un texto fijo y registra el prompt."""

    def __init__(self, respuesta: str):
        self.respuesta = respuesta
        self.ultimo_prompt = None

    def generate_text(self, prompt: str, temperature: float = 0.2) -> str:
        self.ultimo_prompt = prompt
        return self.respuesta


def test_rag_search_devuelve_fragmento_relevante():
    """search('FortiOS IPv6 policy') recupera el fragmento de Fortinet."""
    kb = RAGKnowledgeBase()
    assert kb.num_documentos >= 8  # corpus de 8-10 fragmentos
    resultados = kb.search("FortiOS IPv6 policy", top_k=1)
    assert resultados
    assert "fortios" in resultados[0].lower() or "fortigate" in resultados[0].lower()


def test_rag_search_query_vacia_devuelve_vacio():
    """Una query vacía no rompe ni inventa resultados."""
    kb = RAGKnowledgeBase()
    assert kb.search("", top_k=3) == []


def test_rag_search_respeta_top_k():
    """search() nunca devuelve más fragmentos que top_k."""
    kb = RAGKnowledgeBase()
    resultados = kb.search("IPv6 dual-stack Cisco Fortinet switch router", top_k=2)
    assert len(resultados) <= 2


def test_generate_guarda_roadmap_en_bd(session, scan_sembrado):
    """El roadmap generado se persiste en la tabla roadmaps, asociado al scan."""
    fake = FakeOllama(
        "# Roadmap de migración a IPv6\n\n"
        "## 3. Equipos críticos\n"
        "El router rtr-core-bogota (192.168.1.1) está LISTO para dual-stack."
    )
    gen = RoadmapGenerator(session=session, ollama=fake)

    roadmap = gen.generate()

    assert session.query(Roadmap).count() == 1
    assert roadmap.scan_id == scan_sembrado.id
    assert "rtr-core-bogota" in roadmap.contenido_markdown
    # El prompt debe haber incluido el contexto del equipo crítico real.
    assert "rtr-core-bogota" in fake.ultimo_prompt
    assert "192.168.1.1" in fake.ultimo_prompt


def test_generate_anexa_criticos_omitidos(session, scan_sembrado):
    """Si el modelo no nombra un equipo crítico, se añade un anexo automático."""
    # La respuesta NO menciona el router crítico por nombre ni IP.
    fake = FakeOllama(
        "# Roadmap de migración a IPv6\n\n"
        "## 1. Resumen ejecutivo\n"
        "La red está mayormente lista para IPv6."
    )
    gen = RoadmapGenerator(session=session, ollama=fake)

    roadmap = gen.generate()

    assert "Anexo automático" in roadmap.contenido_markdown
    assert "rtr-core-bogota" in roadmap.contenido_markdown
    assert "192.168.1.1" in roadmap.contenido_markdown


def test_generate_sin_datos_lanza_error(session):
    """Sin scan ni topología en la BD, generate() lanza un RuntimeError claro."""
    fake = FakeOllama("no debería llamarse")
    gen = RoadmapGenerator(session=session, ollama=fake)

    with pytest.raises(RuntimeError, match="No hay datos"):
        gen.generate()
