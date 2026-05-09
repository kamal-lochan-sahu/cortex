"""
CORTEX — LSTM Autoencoder Inference Module
==========================================
Responsibility: Load trained model once at startup,
run inference on 20-step sensor windows, return
reconstruction error + anomaly flag.

RAM strategy: Model loaded ONCE as module-level singleton.
Every call to predict() reuses the same loaded model.
No reload per request — critical for 3.3GB RAM budget.
"""

import os
import json
import logging
import numpy as np
import joblib
import tensorflow as tf

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
MODEL_DIR      = os.path.join(BASE_DIR, 'models', 'sentinel_lstm_ae')
MODEL_PATH     = os.path.join(MODEL_DIR, 'model.keras')
SCALER_PATH    = os.path.join(MODEL_DIR, 'sentinel_scaler.pkl')
THRESHOLD_PATH = os.path.join(MODEL_DIR, 'sentinel_threshold.json')


class LSTMAutoencoder:
    """
    Singleton-style inference wrapper for SENTINEL's LSTM Autoencoder.

    Why a class and not bare functions?
    Model + scaler + threshold are state that must be loaded once
    and reused across hundreds of inference calls. A class holds
    this state cleanly. Instantiate once at module level → import
    anywhere in the backend.
    """

    def __init__(self):
        self.model      = None
        self.scaler     = None
        self.threshold  = None
        self.window_size = 20
        self.is_loaded  = False

    def load(self):
        """
        Load model, scaler, threshold from disk.
        Called once at FastAPI startup — not per request.
        """
        if self.is_loaded:
            logger.info("LSTM AE already loaded — skipping.")
            return

        # ── Validate files exist ─────────────────────────────────
        for path, name in [
            (MODEL_PATH,     'model.keras'),
            (SCALER_PATH,    'sentinel_scaler.pkl'),
            (THRESHOLD_PATH, 'sentinel_threshold.json'),
        ]:
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"LSTM AE: {name} not found at {path}\n"
                    f"Run Colab notebook first and extract to models/sentinel_lstm_ae/"
                )

        # ── Load model ───────────────────────────────────────────
        # suppress_logs=True → TF keeps quiet at inference time
        logger.info("Loading LSTM Autoencoder model...")
        self.model = tf.keras.models.load_model(MODEL_PATH)
        logger.info(f"Model loaded — parameters: {self.model.count_params():,}")

        # ── Load scaler ──────────────────────────────────────────
        # MUST be the same scaler fitted during training
        # Different scaler = wrong normalization = garbage predictions
        self.scaler = joblib.load(SCALER_PATH)
        logger.info("Scaler loaded.")

        # ── Load threshold ───────────────────────────────────────
        with open(THRESHOLD_PATH, 'r') as f:
            meta = json.load(f)

        self.threshold   = meta['threshold']
        self.window_size = meta['window_size']

        logger.info(
            f"Threshold loaded: {self.threshold:.6f} "
            f"(window_size={self.window_size})"
        )

        self.is_loaded = True
        logger.info("LSTM Autoencoder ready.")

    def predict(self, window: list[float]) -> dict:
        if not self.is_loaded:
            raise RuntimeError(
                "LSTM AE not loaded. Call lstm_ae.load() at startup."
            )
        if len(window) != self.window_size:
            raise ValueError(
                f"Window must be {self.window_size} values, got {len(window)}"
            )

        arr = np.array(window, dtype=np.float32)

        # Window-level normalization — scale-independent pattern detection.
        # One global scaler (trained on temp_01 60-70C) would map rpm_01
        # (1500 RPM) to ~142 — completely out of distribution.
        # Per-window min/max normalization: LSTM learns temporal patterns
        # regardless of sensor units or absolute value ranges.
        w_min   = arr.min()
        w_max   = arr.max()
        w_range = w_max - w_min

        if w_range < 1e-6:
            # Flat line = sensor freeze — flag directly as anomaly
            return {
                'reconstruction_error': float(self.threshold * 2),
                'threshold':            0.008,
                'is_anomaly':           True,
                'anomaly_score':        2.0,
                'confidence':           1.0,
                'note':                 'freeze_detected',
            }

        arr_scaled = (arr - w_min) / w_range
        arr_input  = arr_scaled.reshape(1, self.window_size, 1)

        reconstructed = self.model.predict(arr_input, verbose=0)
        error = float(
            np.mean(np.power(arr_input - reconstructed, 2), axis=(1, 2))[0]
        )

        effective_threshold = 0.05
        is_anomaly    = error > effective_threshold
        anomaly_score = error / effective_threshold
        confidence    = min(1.0, max(0.0, (error - effective_threshold) / effective_threshold))

        return {
            'reconstruction_error': round(error, 8),
            'threshold':            effective_threshold,
            'is_anomaly':           is_anomaly,
            'anomaly_score':        round(anomaly_score, 4),
            'confidence':           round(confidence, 4),
        }

    def predict_batch(self, windows: list[list[float]]) -> list[dict]:
        if not self.is_loaded:
            raise RuntimeError("LSTM AE not loaded.")
        results = []
        for window in windows:
            results.append(self.predict(window))
        return results


# ── Module-level singleton ───────────────────────────────────────
# Import this instance anywhere in the backend:
#   from backend.ml.lstm_autoencoder import lstm_ae
#   lstm_ae.load()   ← once at startup
#   lstm_ae.predict(window)  ← per reading
lstm_ae = LSTMAutoencoder()