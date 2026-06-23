"""model_trainer.py — Entrenamiento del clasificador Random Forest (Módulo 2).

Contiene :class:`ModelTrainer`, que toma el dataset de entrenamiento
etiquetado, extrae características con :class:`FeatureExtractor`, entrena un
``RandomForestClassifier`` y persiste tanto el modelo como el codificador de
etiquetas con ``joblib``. Genera además un reporte de texto en español que
sirve de evidencia académica directa para la memoria del TFM.

Random Forest se eligió (sobre, p.ej., un único árbol o una red neuronal)
porque ofrece un equilibrio entre exactitud y trazabilidad: expone
``feature_importances_``, lo que permite explicar QUÉ señales pesaron en la
clasificación — coherente con el principio de transparencia del proyecto.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from tabulate import tabulate

from src.classifier.feature_extractor import FeatureExtractor

# Nombres de archivo de los artefactos persistidos.
MODEL_FILENAME = "classifier_model.joblib"
ENCODER_FILENAME = "label_encoder.joblib"

# Orden de clases para mostrar de forma estable en reportes.
CLASS_ORDER = ["LISTO", "ACTUALIZABLE", "REEMPLAZAR", "EVALUAR"]


class ModelTrainer:
    """Entrena y persiste el clasificador de madurez IPv6."""

    def __init__(self, model_dir: str = "data/processed"):
        self.model_dir = model_dir
        os.makedirs(self.model_dir, exist_ok=True)
        self.extractor = FeatureExtractor()

    def train(
        self,
        dataset_path: str,
        test_size: float = 0.2,
        random_state: int = 42,
    ) -> dict:
        """Entrena el modelo y devuelve métricas de evaluación.

        Args:
            dataset_path: ruta al JSON de entrenamiento etiquetado.
            test_size: proporción reservada para test (estratificada).
            random_state: semilla para reproducibilidad.

        Returns:
            Diccionario con accuracy, classification_report (dict),
            confusion_matrix, feature_importances (orden descendente),
            train_size, test_size y class_distribution.
        """
        with open(dataset_path, encoding="utf-8") as fh:
            devices = json.load(fh)

        # Características (X) y etiquetas (y) -------------------------------
        X = self.extractor.extract_batch(devices)
        y_text = [d["ipv6_readiness_label"] for d in devices]

        label_encoder = LabelEncoder()
        y = label_encoder.fit_transform(y_text)

        # Partición estratificada (conserva la proporción de clases) -------
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y
        )

        # Entrenamiento ----------------------------------------------------
        # class_weight='balanced' compensa el desbalance del dataset (hay más
        # ACTUALIZABLE que EVALUAR), evitando que el modelo ignore las clases
        # minoritarias.
        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=random_state,
            class_weight="balanced",
        )
        model.fit(X_train, y_train)

        # Evaluación -------------------------------------------------------
        y_pred = model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        report = classification_report(
            y_test,
            y_pred,
            labels=list(range(len(label_encoder.classes_))),
            target_names=list(label_encoder.classes_),
            output_dict=True,
            zero_division=0,
        )
        cm = confusion_matrix(
            y_test, y_pred, labels=list(range(len(label_encoder.classes_)))
        )

        # Importancia de características (orden descendente) ----------------
        feature_names = self.extractor.get_feature_names()
        importances = sorted(
            zip(feature_names, model.feature_importances_),
            key=lambda pair: pair[1],
            reverse=True,
        )
        feature_importances = [(name, float(val)) for name, val in importances]

        # Distribución de clases del dataset completo ----------------------
        class_distribution = {
            cls: int(np.sum(y == idx))
            for idx, cls in enumerate(label_encoder.classes_)
        }

        # Persistencia de artefactos ---------------------------------------
        joblib.dump(model, os.path.join(self.model_dir, MODEL_FILENAME))
        joblib.dump(label_encoder, os.path.join(self.model_dir, ENCODER_FILENAME))

        return {
            "accuracy": float(accuracy),
            "classification_report": report,
            "confusion_matrix": cm.tolist(),
            "confusion_matrix_labels": list(label_encoder.classes_),
            "feature_importances": feature_importances,
            "train_size": int(len(X_train)),
            "test_size": int(len(X_test)),
            "class_distribution": class_distribution,
        }

    def generate_training_report(
        self,
        metrics: dict,
        output_path: str = "data/processed/training_report.txt",
    ) -> None:
        """Escribe un reporte de entrenamiento legible en español.

        El reporte es evidencia académica directa para la memoria del TFM:
        documenta dataset, accuracy, métricas por clase, matriz de confusión
        e importancia de características, con una sección final dedicada a
        cuánto pesó la confianza de la detección de SO.

        Args:
            metrics: dict devuelto por :meth:`train`.
            output_path: ruta del archivo de texto a generar.
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        lines: list[str] = []

        def add(text: str = "") -> None:
            lines.append(text)

        add("=" * 70)
        add("  REPORTE DE ENTRENAMIENTO — MÓDULO 2: CLASIFICADOR IPv6 (ML)")
        add("=" * 70)
        add(f"Fecha/hora de entrenamiento: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        add("Algoritmo: RandomForestClassifier "
            "(n_estimators=100, max_depth=10, class_weight='balanced')")
        add()

        # --- Dataset ------------------------------------------------------
        total = metrics["train_size"] + metrics["test_size"]
        add("-" * 70)
        add("DATASET")
        add("-" * 70)
        add(f"Dispositivos totales : {total}")
        add(f"Conjunto de entrenamiento : {metrics['train_size']}")
        add(f"Conjunto de prueba (test) : {metrics['test_size']}")
        add()
        dist_rows = [[cls, n] for cls, n in metrics["class_distribution"].items()]
        add("Distribución de clases (dataset completo):")
        add(tabulate(dist_rows, headers=["Clase", "Dispositivos"],
                     tablefmt="grid"))
        add()

        # --- Accuracy global ---------------------------------------------
        add("-" * 70)
        add("EXACTITUD GLOBAL (accuracy)")
        add("-" * 70)
        add(f"Accuracy sobre el conjunto de prueba: "
            f"{metrics['accuracy'] * 100:.1f}%")
        add()

        # --- Classification report ---------------------------------------
        add("-" * 70)
        add("MÉTRICAS POR CLASE (precision / recall / f1)")
        add("-" * 70)
        report = metrics["classification_report"]
        report_rows = []
        for cls in metrics["confusion_matrix_labels"]:
            if cls in report:
                r = report[cls]
                report_rows.append([
                    cls,
                    f"{r['precision']:.2f}",
                    f"{r['recall']:.2f}",
                    f"{r['f1-score']:.2f}",
                    int(r["support"]),
                ])
        add(tabulate(
            report_rows,
            headers=["Clase", "Precision", "Recall", "F1", "Soporte"],
            tablefmt="grid",
        ))
        add()

        # --- Matriz de confusión -----------------------------------------
        add("-" * 70)
        add("MATRIZ DE CONFUSIÓN (filas=real, columnas=predicho)")
        add("-" * 70)
        labels = metrics["confusion_matrix_labels"]
        cm = metrics["confusion_matrix"]
        cm_rows = [
            [f"real:{labels[i]}"] + cm[i]
            for i in range(len(labels))
        ]
        add(tabulate(
            cm_rows,
            headers=[""] + [f"pred:{c}" for c in labels],
            tablefmt="grid",
        ))
        add()

        # --- Importancia de características -------------------------------
        add("-" * 70)
        add("IMPORTANCIA DE CARACTERÍSTICAS")
        add("-" * 70)
        importances = metrics["feature_importances"]
        max_imp = max((val for _, val in importances), default=1.0) or 1.0
        for name, val in importances:
            bar = "#" * int(round((val / max_imp) * 40))
            add(f"{name:<24} {val:6.3f}  {bar}")
        add()

        # --- Sección específica: confianza de detección de OS ------------
        add("-" * 70)
        add("IMPORTANCIA DE LA CONFIANZA DE DETECCIÓN DE OS "
            "(os_confidence_score)")
        add("-" * 70)
        ranking = [name for name, _ in importances]
        pos = ranking.index("os_confidence_score") + 1
        total_feats = len(ranking)
        os_conf_val = dict(importances)["os_confidence_score"]
        add(f"Posición en el ranking de importancia: "
            f"{pos} de {total_feats}")
        add(f"Importancia: {os_conf_val:.3f}")
        add()
        if pos <= total_feats / 2:
            add("Interpretación: el modelo SÍ encontró útil la confianza de la")
            add("detección de SO. Aprendió a desconfiar del os_score cuando el")
            add("dato proviene de un fingerprint dudoso ('ambiguo'/'ninguno'),")
            add("en vez de tratar todo dato de OS con la misma confianza ciega")
            add("que causó el falso positivo 'Sony Blu-Ray Player' en el Módulo 1.")
        else:
            add("Interpretación: con este dataset el modelo le dio importancia")
            add("baja a la confianza de detección de SO. Probablemente otras")
            add("señales (ipv6_score, tipo de dispositivo, puertos) ya bastan")
            add("para clasificar, y la calidad del dato de OS fue redundante.")
            add("Es un hallazgo válido a documentar: la utilidad de esta señal")
            add("dependerá de datasets de campo más grandes y variados.")
        add()
        add("NOTA METODOLÓGICA: este reporte se genera sobre un dataset")
        add("sintético de 50 dispositivos. Las cifras son ilustrativas del")
        add("comportamiento del pipeline, no una validación estadística sobre")
        add("datos de campo a gran escala — una limitación conocida del")
        add("prototipo, a documentar en la memoria del TFM.")
        add()
        add("=" * 70)

        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
