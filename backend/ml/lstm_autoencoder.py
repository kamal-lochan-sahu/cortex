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
        """
        Run inference on a single 20-step window.

        Args:
            window: list of 20 float values (raw sensor readings,
                    NOT normalized — this function normalizes internally)

        Returns:
            {
              'reconstruction_error': float,   # MSE vs reconstructed
              'threshold':            float,   # decision boundary
              'is_anomaly':           bool,    # error > threshold?
              'anomaly_score':        float,   # error / threshold (>1 = anomaly)
              'confidence':           float,   # how far above threshold (0-1 clamped)
            }

        Raises:
            RuntimeError: if model not loaded
            ValueError:   if window length != 20
        """
        if not self.is_loaded:
            raise RuntimeError(
                "LSTM AE not loaded. Call lstm_ae.load() at startup."
            )

        if len(window) != self.window_size:
            raise ValueError(
                f"Window must be {self.window_size} values, got {len(window)}"
            )

        # ── Step 1: Normalize ────────────────────────────────────
        # Convert raw sensor values → [0,1] using training scaler
        # reshape(-1,1) → scaler expects 2D input
        arr = np.array(window, dtype=np.float32).reshape(-1, 1)
        arr_scaled = self.scaler.transform(arr)

        # ── Step 2: Reshape for LSTM ─────────────────────────────
        # LSTM expects: (batch_size, timesteps, features)
        # We have 1 sample: (1, 20, 1)
        arr_input = arr_scaled.reshape(1, self.window_size, 1)

        # ── Step 3: Reconstruct ──────────────────────────────────
        # Model reconstructs the sequence
        # verbose=0 → no console output per prediction
        reconstructed = self.model.predict(arr_input, verbose=0)

        # ── Step 4: Compute MSE ──────────────────────────────────
        # Mean Squared Error between original and reconstructed
        # axis=(1,2) → mean over timesteps and features
        error = float(
            np.mean(np.power(arr_input - reconstructed, 2), axis=(1, 2))[0]
        )

        # ── Step 5: Anomaly decision ─────────────────────────────
        is_anomaly    = error > self.threshold

        # anomaly_score: ratio of error to threshold
        # 0.5 = half of threshold (clearly normal)
        # 1.0 = exactly at threshold
        # 2.0 = twice the threshold (strong anomaly)
        anomaly_score = error / self.threshold

        # confidence: how confident are we this is an anomaly?
        # clamped to [0, 1] — meaningful only when is_anomaly=True
        confidence = min(1.0, max(0.0, (error - self.threshold) / self.threshold))

        return {
            'reconstruction_error': round(error, 8),
            'threshold':            round(self.threshold, 8),
            'is_anomaly':           is_anomaly,
            'anomaly_score':        round(anomaly_score, 4),
            'confidence':           round(confidence, 4),
        }

    def predict_batch(self, windows: list[list[float]]) -> list[dict]:
        """
        Run inference on multiple windows at once.
        More efficient than calling predict() in a loop —
        single GPU/CPU call for all windows.

        Args:
            windows: list of N windows, each 20 floats

        Returns:
            list of N result dicts (same format as predict())
        """
        if not self.is_loaded:
            raise RuntimeError("LSTM AE not loaded.")

        n = len(windows)
        arr = np.array(windows, dtype=np.float32).reshape(-1, 1)
        arr_scaled = self.scaler.transform(arr).reshape(n, self.window_size, 1)

        reconstructed = self.model.predict(arr_scaled, verbose=0)
        errors = np.mean(np.power(arr_scaled - reconstructed, 2), axis=(1, 2))

        results = []
        for error in errors:
            error = float(error)
            is_anomaly    = error > self.threshold
            anomaly_score = error / self.threshold
            confidence    = min(1.0, max(0.0, (error - self.threshold) / self.threshold))
            results.append({
                'reconstruction_error': round(error, 8),
                'threshold':            round(self.threshold, 8),
                'is_anomaly':           is_anomaly,
                'anomaly_score':        round(anomaly_score, 4),
                'confidence':           round(confidence, 4),
            })
        return results


# ── Module-level singleton ───────────────────────────────────────
# Import this instance anywhere in the backend:
#   from backend.ml.lstm_autoencoder import lstm_ae
#   lstm_ae.load()   ← once at startup
#   lstm_ae.predict(window)  ← per reading
lstm_ae = LSTMAutoencoder()