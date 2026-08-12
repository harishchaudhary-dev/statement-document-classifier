"""
Statement document classification service.

Responsibilities:
- Load a persisted scikit-learn model.
- Bootstrap a small fallback model when no valid model exists.
- Classify extracted document text.
- Provide prediction confidence.
- Keep model-loading failures explicit and observable.

Production note:
The bootstrap dataset is intended only as a development fallback.
For production classification, replace it with a properly trained,
validated dataset/model.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

import joblib
from sklearn.exceptions import InconsistentVersionWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

from src.config import settings


logger = logging.getLogger("StatementClassifier")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UNKNOWN_STATEMENT = "unknown_statement"

BOOTSTRAP_DATASET = [
    (
        (
            "Account Statement Opening Balance Closing Balance "
            "Account Number Interest Earned Total Credits Debits"
        ),
        "bank_statement",
    ),
    (
        (
            "Credit Card Account Summary Minimum Amount Due "
            "Payment Due Date Credit Limit Total Outstanding APR"
        ),
        "credit_card_statement",
    ),
    (
        (
            "Tax Return Form W-2 Wage and Tax Statement Gross Pay "
            "Tax Withheld Social Security Medicare"
        ),
        "tax_document",
    ),
    (
        (
            "INVOICE Invoice Number Bill To Due Date Total Amount "
            "Payable Tax Identification Subtotal"
        ),
        "invoice",
    ),
    (
        (
            "Utility Bill Water Electricity Gas Usage KWh "
            "Account Balance Consumption Reading Due Date"
        ),
        "utility_bill",
    ),
]


class StatementClassifier:
    """
    ML service responsible for statement/document classification.

    The classifier uses:

        TF-IDF -> Multinomial Naive Bayes

    The persisted model is expected to be a scikit-learn Pipeline.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
    ) -> None:
        """
        Initialize the classifier.

        Args:
            model_path:
                Optional path to a persisted model. If omitted,
                settings.MODEL_PATH is used.
        """

        configured_path = (
            model_path
            if model_path is not None
            else settings.MODEL_PATH
        )

        self.model_path = Path(configured_path)
        self.pipeline: Pipeline | None = None

        self._load_or_train_model()

    # -----------------------------------------------------------------------
    # Model loading
    # -----------------------------------------------------------------------

    def _load_or_train_model(self) -> None:
        """
        Load an existing model.

        If the model does not exist or cannot be loaded, create the
        development bootstrap model.
        """

        self._ensure_model_directory()

        if self.model_path.exists():
            try:
                self._load_model()
                return

            except Exception:
                logger.exception(
                    "Existing classifier model could not be loaded: %s",
                    self.model_path,
                )

                logger.warning(
                    "Falling back to bootstrap classifier model."
                )

        self._train_bootstrap_model()

    def _load_model(self) -> None:
        """
        Load the persisted scikit-learn pipeline.

        Raises:
            RuntimeError:
                If the loaded object is not a valid classifier pipeline.
        """

        logger.info(
            "Loading classifier model from %s",
            self.model_path,
        )

        # Do not globally suppress sklearn version warnings.
        # They can be important when debugging model compatibility.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "default",
                category=InconsistentVersionWarning,
            )

            loaded_model = joblib.load(self.model_path)

        if not isinstance(loaded_model, Pipeline):
            raise RuntimeError(
                "Invalid classifier model. "
                "Expected sklearn.pipeline.Pipeline, "
                f"received {type(loaded_model).__name__}."
            )

        if len(loaded_model.steps) < 2:
            raise RuntimeError(
                "Invalid classifier pipeline. "
                "Expected at least a vectorizer and classifier."
            )

        self.pipeline = loaded_model

        logger.info(
            "Successfully loaded classifier model from %s",
            self.model_path,
        )

    # -----------------------------------------------------------------------
    # Bootstrap model
    # -----------------------------------------------------------------------

    def _train_bootstrap_model(self) -> None:
        """
        Train a small development fallback model.

        This model is intentionally lightweight so the application can
        start even when model.pkl has not yet been generated.

        IMPORTANT:
        This is not a production-quality training dataset.
        """

        logger.warning(
            "Training bootstrap statement classifier. "
            "Use a properly trained production model for real workloads."
        )

        texts = [text for text, _ in BOOTSTRAP_DATASET]
        labels = [label for _, label in BOOTSTRAP_DATASET]

        pipeline = Pipeline(
            steps=[
                (
                    "tfidf",
                    TfidfVectorizer(
                        lowercase=True,
                        strip_accents="unicode",
                        ngram_range=(1, 2),
                        stop_words="english",
                        sublinear_tf=True,
                    ),
                ),
                (
                    "classifier",
                    MultinomialNB(
                        alpha=0.1,
                    ),
                ),
            ]
        )

        pipeline.fit(texts, labels)

        self.pipeline = pipeline

        self._save_model()

        logger.info(
            "Bootstrap classifier trained successfully. "
            "Model saved to %s",
            self.model_path,
        )

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _save_model(self) -> None:
        """
        Persist the trained pipeline to disk.
        """

        if self.pipeline is None:
            raise RuntimeError(
                "Cannot save classifier because the pipeline is not initialized."
            )

        self._ensure_model_directory()

        temporary_path = self.model_path.with_suffix(
            self.model_path.suffix + ".tmp"
        )

        try:
            # Write to a temporary file first.
            # This prevents a partially-written model from becoming the
            # active model if the process crashes during serialization.
            joblib.dump(
                self.pipeline,
                temporary_path,
                compress=3,
            )

            temporary_path.replace(self.model_path)

        except Exception:
            if temporary_path.exists():
                temporary_path.unlink(missing_ok=True)

            logger.exception(
                "Failed to save classifier model to %s",
                self.model_path,
            )

            raise

    def _ensure_model_directory(self) -> None:
        """
        Ensure the directory containing model.pkl exists.
        """

        self.model_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    # -----------------------------------------------------------------------
    # Prediction
    # -----------------------------------------------------------------------

    def predict(self, text: str) -> str:
        """
        Predict the document type.

        Args:
            text:
                Extracted text from a document.

        Returns:
            Predicted document class.
        """

        if not isinstance(text, str):
            logger.warning(
                "Classifier received non-string input: %s",
                type(text).__name__,
            )
            return UNKNOWN_STATEMENT

        cleaned_text = text.strip()

        if not cleaned_text:
            return UNKNOWN_STATEMENT

        self._ensure_pipeline()

        try:
            prediction = self.pipeline.predict(
                [cleaned_text]
            )[0]

            result = str(prediction)

            logger.info(
                "Document classified as: %s",
                result,
            )

            return result

        except Exception:
            logger.exception(
                "Document classification failed."
            )

            return UNKNOWN_STATEMENT

    # -----------------------------------------------------------------------
    # Prediction with confidence
    # -----------------------------------------------------------------------

    def predict_with_confidence(
        self,
        text: str,
    ) -> dict[str, Any]:
        """
        Predict the document class and return confidence information.

        Returns:
            {
                "doc_type": "...",
                "confidence": 0.95,
                "probabilities": {
                    "invoice": 0.95,
                    "utility_bill": 0.02,
                    ...
                }
            }
        """

        if not isinstance(text, str):
            return {
                "doc_type": UNKNOWN_STATEMENT,
                "confidence": 0.0,
                "probabilities": {},
            }

        cleaned_text = text.strip()

        if not cleaned_text:
            return {
                "doc_type": UNKNOWN_STATEMENT,
                "confidence": 0.0,
                "probabilities": {},
            }

        self._ensure_pipeline()

        try:
            prediction = str(
                self.pipeline.predict([cleaned_text])[0]
            )

            probabilities: dict[str, float] = {}

            if hasattr(self.pipeline, "predict_proba"):
                raw_probabilities = (
                    self.pipeline.predict_proba(
                        [cleaned_text]
                    )[0]
                )

                classes = self.pipeline.classes_

                probabilities = {
                    str(label): round(
                        float(probability),
                        4,
                    )
                    for label, probability in zip(
                        classes,
                        raw_probabilities,
                    )
                }

            confidence = probabilities.get(
                prediction,
                0.0,
            )

            return {
                "doc_type": prediction,
                "confidence": round(
                    float(confidence),
                    4,
                ),
                "probabilities": probabilities,
            }

        except Exception:
            logger.exception(
                "Classification with confidence failed."
            )

            return {
                "doc_type": UNKNOWN_STATEMENT,
                "confidence": 0.0,
                "probabilities": {},
            }

    # -----------------------------------------------------------------------
    # Internal validation
    # -----------------------------------------------------------------------

    def _ensure_pipeline(self) -> None:
        """
        Ensure a classifier pipeline is available.
        """

        if self.pipeline is None:
            raise RuntimeError(
                "Statement classifier pipeline is not initialized."
            )