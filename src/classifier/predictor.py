"""predictor.py — Clasificación de dispositivos con el modelo entrenado.

Contiene :class:`DeviceClassifier`, que carga el modelo Random Forest y el
codificador de etiquetas persistidos por :class:`ModelTrainer` y los aplica a
dispositivos nuevos (los que produce el Módulo 1). Enriquece cada dispositivo
con la clase predicha, su confianza, las probabilidades por clase y un
``priority_score`` que ordena la cola de trabajo de migración.
"""
from __future__ import annotations

import os

import joblib

from src.classifier.feature_extractor import FeatureExtractor
from src.classifier.model_trainer import ENCODER_FILENAME, MODEL_FILENAME

# Prioridad de atención: 1 = más urgente. Un equipo a REEMPLAZAR exige acción
# antes que uno ACTUALIZABLE, y este antes que un EVALUAR; lo que ya está LISTO
# es lo último de la cola.
PRIORITY_SCORE = {
    "REEMPLAZAR": 1,
    "ACTUALIZABLE": 2,
    "EVALUAR": 3,
    "LISTO": 4,
}


class DeviceClassifier:
    """Aplica el clasificador entrenado a dispositivos del Módulo 1."""

    def __init__(self, model_dir: str = "data/processed"):
        model_path = os.path.join(model_dir, MODEL_FILENAME)
        encoder_path = os.path.join(model_dir, ENCODER_FILENAME)

        if not (os.path.exists(model_path) and os.path.exists(encoder_path)):
            raise RuntimeError(
                "Modelo no entrenado. Ejecuta primero: "
                "python main.py --demo --train"
            )

        self.model = joblib.load(model_path)
        self.label_encoder = joblib.load(encoder_path)
        self.extractor = FeatureExtractor()

    def classify_device(self, device: dict) -> dict:
        """Clasifica un dispositivo y lo devuelve enriquecido.

        Args:
            device: dispositivo del Módulo 1.

        Returns:
            Copia del dispositivo con ``ml_classification``,
            ``ml_confidence``, ``ml_probabilities`` (dict por clase) y
            ``priority_score``.
        """
        features = self.extractor.extract_features(device).reshape(1, -1)
        proba = self.model.predict_proba(features)[0]

        best_idx = int(proba.argmax())
        classification = self.label_encoder.inverse_transform([best_idx])[0]
        confidence = float(proba[best_idx])

        probabilities = {
            self.label_encoder.inverse_transform([idx])[0]: float(p)
            for idx, p in enumerate(proba)
        }

        enriched = dict(device)
        enriched["ml_classification"] = classification
        enriched["ml_confidence"] = confidence
        enriched["ml_probabilities"] = probabilities
        enriched["priority_score"] = PRIORITY_SCORE.get(classification, 99)
        return enriched

    def classify_batch(self, devices: list[dict]) -> list[dict]:
        """Clasifica una lista y la ordena por prioridad de atención.

        El orden es: primero ``priority_score`` ascendente (lo más urgente
        arriba) y, como desempate, ``ipv6_score`` ascendente (dentro de la
        misma clase, lo menos listo primero).

        Args:
            devices: lista de dispositivos del Módulo 1.

        Returns:
            Lista enriquecida y ordenada.
        """
        classified = [self.classify_device(d) for d in devices]
        classified.sort(
            key=lambda d: (d["priority_score"], d.get("ipv6_score", 0))
        )
        return classified
