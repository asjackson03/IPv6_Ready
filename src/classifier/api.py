"""api.py — API HTTP del Módulo 2 (clasificador ML) con FastAPI.

Expone el clasificador entrenado como un servicio REST para que el resto del
sistema (y, en el futuro, el portal web del Módulo 4) no dependa del
filesystem ni de importar el código Python directamente. Es además el formato
estándar para servir predicciones de modelos scikit-learn ya entrenados.

El Módulo 1 (escaneo con nmap) NO vive aquí: corre nativo en el host y entrega
sus archivos `data/raw/*.json`, que se pasan a este servicio vía `/classify`.

Configuración por variables de entorno (útil para Docker y para tests):
  * ``MODEL_DIR``         — carpeta donde viven/persisten los artefactos del
                            modelo (por defecto ``data/processed``).
  * ``TRAINING_DATASET``  — dataset por defecto para ``/train``
                            (por defecto ``data/sample/training_dataset.json``).
"""
from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src import __version__
from src.classifier.model_trainer import MODEL_FILENAME, ModelTrainer
from src.classifier.predictor import DeviceClassifier

# Configuración (sobrescribible por entorno para contenedor/tests).
MODEL_DIR = os.getenv("MODEL_DIR", "data/processed")
DEFAULT_DATASET = os.getenv(
    "TRAINING_DATASET", "data/sample/training_dataset.json"
)

app = FastAPI(
    title="IPv6 Ready Analyzer — Módulo 2 (Classifier ML)",
    version=__version__,
    description=(
        "Clasifica dispositivos de red en LISTO/ACTUALIZABLE/REEMPLAZAR/"
        "EVALUAR según su madurez para migrar a IPv6, usando un modelo "
        "Random Forest entrenado sobre las características del Módulo 1."
    ),
)


class TrainRequest(BaseModel):
    """Cuerpo opcional de ``/train``: ruta a un dataset alternativo."""

    dataset_path: Optional[str] = None


def _model_path() -> str:
    """Ruta absoluta/relativa al artefacto del modelo entrenado."""
    return os.path.join(MODEL_DIR, MODEL_FILENAME)


@app.get("/")
def root() -> dict:
    """Información básica del servicio y endpoints disponibles."""
    return {
        "service": "IPv6 Ready Analyzer — Módulo 2 (Classifier ML)",
        "version": __version__,
        "description": (
            "Servicio de clasificación de madurez IPv6 de dispositivos de red."
        ),
        "endpoints": {
            "GET /": "Esta información.",
            "GET /health": "Estado del servicio y si el modelo está cargado.",
            "POST /train": "Entrena el modelo (body opcional: {dataset_path}).",
            "POST /classify": "Clasifica una lista de dispositivos del Módulo 1.",
        },
    }


@app.get("/health")
def health() -> dict:
    """Healthcheck simple: estado del servicio y disponibilidad del modelo."""
    return {"status": "ok", "model_loaded": os.path.exists(_model_path())}


@app.post("/train")
def train(req: Optional[TrainRequest] = None) -> dict:
    """Entrena el clasificador y devuelve las métricas de evaluación.

    Si no se envía cuerpo (o sin ``dataset_path``), usa el dataset por
    defecto. Persiste el modelo y un reporte de entrenamiento en
    ``MODEL_DIR``.
    """
    dataset = req.dataset_path if (req and req.dataset_path) else DEFAULT_DATASET
    if not os.path.exists(dataset):
        raise HTTPException(
            status_code=400,
            detail=f"Dataset de entrenamiento no encontrado: {dataset}",
        )

    trainer = ModelTrainer(model_dir=MODEL_DIR)
    metrics = trainer.train(dataset)
    trainer.generate_training_report(
        metrics, output_path=os.path.join(MODEL_DIR, "training_report.txt")
    )
    return metrics


@app.post("/classify")
def classify(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clasifica una lista de dispositivos del Módulo 1.

    Devuelve la misma lista enriquecida con ``ml_classification``,
    ``ml_confidence``, ``ml_probabilities`` y ``priority_score``, ordenada
    por prioridad de atención. Si el modelo no está entrenado, responde
    HTTP 503 (no un 500 genérico) indicando que hay que entrenar primero.
    """
    try:
        classifier = DeviceClassifier(model_dir=MODEL_DIR)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return classifier.classify_batch(devices)
