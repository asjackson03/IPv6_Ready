"""rag_knowledge_base.py — Base de conocimiento RAG (Módulo 3c).

Recupera fragmentos de documentación técnica relevantes para enriquecer el
prompt del generador de roadmap. La recuperación es determinista y local: usa
TF-IDF (scikit-learn, ya presente por el Módulo 2) + similitud de coseno sobre
un corpus de fragmentos sintéticos escritos a mano.

NOTA DE ALCANCE (decisión explícita de Andrés): los fragmentos son sintéticos
pero técnicamente representativos (buenas prácticas de dominio público de
networking), NO datasheets reales de fabricantes. La integración con PDFs
reales de Cisco/Fortinet vía descarga y parseo queda como línea de trabajo
futuro; esta versión valida la ARQUITECTURA RAG, no la cobertura documental.
"""
from __future__ import annotations

import glob
import os

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Carpeta del corpus sintético (versionada en el repo, ver .gitignore).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KNOWLEDGE_BASE_DIR = os.path.join(_ROOT, "data", "sample", "knowledge_base")


class RAGKnowledgeBase:
    """Recuperador TF-IDF sobre el corpus de fragmentos técnicos."""

    def __init__(self, knowledge_dir: str | None = None):
        self.knowledge_dir = knowledge_dir or KNOWLEDGE_BASE_DIR
        self._nombres: list[str] = []
        self._documentos: list[str] = []
        self._vectorizer: TfidfVectorizer | None = None
        self._matriz = None
        self._cargar()

    def _cargar(self) -> None:
        """Lee los .txt del corpus y construye la matriz TF-IDF.

        Si la carpeta no existe o está vacía, deja el recuperador inerte
        (search() devolverá lista vacía): el roadmap aún puede generarse sin
        contexto RAG, solo con los datos de la BD.
        """
        if not os.path.isdir(self.knowledge_dir):
            return

        for filepath in sorted(glob.glob(os.path.join(self.knowledge_dir, "*.txt"))):
            if os.path.basename(filepath).startswith("._"):
                continue  # ignora AppleDouble del disco no-APFS
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    contenido = fh.read().strip()
            except OSError:
                continue
            if contenido:
                self._nombres.append(os.path.basename(filepath))
                self._documentos.append(contenido)

        if not self._documentos:
            return

        # Sin stop_words: el corpus mezcla español e inglés técnico. TF-IDF
        # con n-gramas de 1 y 2 palabras captura términos como "dual stack" o
        # "router advertisement" sin necesidad de embeddings.
        self._vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        self._matriz = self._vectorizer.fit_transform(self._documentos)

    @property
    def num_documentos(self) -> int:
        """Cantidad de fragmentos cargados en el corpus."""
        return len(self._documentos)

    def search(self, query: str, top_k: int = 3) -> list[str]:
        """Devuelve los ``top_k`` fragmentos más relevantes para ``query``.

        Args:
            query: texto de consulta (típicamente vendors/tecnologías reales
                detectados en los datos del cliente).
            top_k: número máximo de fragmentos a devolver.

        Returns:
            Lista de textos de fragmentos, ordenados por relevancia
            descendente. Vacía si no hay corpus o la query no tiene señal.
        """
        if not query or not query.strip() or self._vectorizer is None:
            return []

        consulta_vec = self._vectorizer.transform([query])
        similitudes = cosine_similarity(consulta_vec, self._matriz)[0]

        # Índices ordenados por similitud descendente, descartando los de
        # similitud nula (sin ninguna palabra en común con la query).
        ranking = sorted(
            range(len(similitudes)),
            key=lambda i: similitudes[i],
            reverse=True,
        )
        resultados = [
            self._documentos[i] for i in ranking[:top_k]
            if similitudes[i] > 0
        ]
        return resultados

    def search_con_nombres(self, query: str, top_k: int = 3) -> list[tuple]:
        """Como :meth:`search` pero devuelve ``(nombre_archivo, texto, score)``.

        Útil para depuración/transparencia (saber qué fragmento se recuperó y
        con qué puntuación), sin afectar la interfaz simple de ``search``.
        """
        if not query or not query.strip() or self._vectorizer is None:
            return []

        consulta_vec = self._vectorizer.transform([query])
        similitudes = cosine_similarity(consulta_vec, self._matriz)[0]
        ranking = sorted(
            range(len(similitudes)),
            key=lambda i: similitudes[i],
            reverse=True,
        )
        return [
            (self._nombres[i], self._documentos[i], float(similitudes[i]))
            for i in ranking[:top_k]
            if similitudes[i] > 0
        ]
