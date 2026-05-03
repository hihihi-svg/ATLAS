"""
ATLAS Meta-Trainer (Step 3: Neural Network)
Trains a Multi-Layer Perceptron (NN) to predict trade success probability.
"""

import pandas as pd
import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
import joblib
from pathlib import Path
from loguru import logger
import json

DATA_PATH    = Path("memory/meta_training_data.csv")
MODEL_PATH   = Path("memory/meta_nn_model.pkl")
SCALER_PATH  = Path("memory/meta_scaler.pkl")
CONFIG_PATH  = Path("memory/meta_nn_config.json")

def train_nn_model():
    if not DATA_PATH.exists():
        logger.warning("No training data found.")
        return

    df = pd.read_csv(DATA_PATH)
    
    if 'outcome' not in df.columns:
        logger.info("Generating synthetic labels for demo...")
        df['outcome'] = (df['tech'] > 6.0).astype(int) 

    # Features: Scores + Indicators (if added to CSV)
    # Current CSV columns: rl,tech,anl,rsk,penalty,regime,vote,timestamp
    X = df[['rl', 'tech', 'anl', 'rsk', 'penalty']]
    y = df['outcome']

    if len(df) < 20:
        logger.warning("Not enough data for NN. Need at least 20 samples.")
        return

    # NN works best with scaled data
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Simple MLP: 16 -> 8 -> 1
    model = MLPClassifier(
        hidden_layer_sizes=(16, 8),
        activation='relu',
        solver='adam',
        max_iter=1000,
        random_state=42
    )
    
    model.fit(X_scaled, y)

    # Save artifacts
    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    
    config = {
        "features": list(X.columns),
        "classes": model.classes_.tolist(),
        "iterations": model.n_iter_
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2))

    logger.success("Step 3 Complete: Neural Network Meta-Model trained.")
    logger.info(f"NN Config: {config}")

if __name__ == "__main__":
    train_nn_model()
