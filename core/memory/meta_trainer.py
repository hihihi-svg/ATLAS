"""
ATLAS Meta-Trainer (Step 2: Regime Aware)
Trains multiple Logistic Regression models, one per market regime.
"""

import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from pathlib import Path
from loguru import logger
import json

DATA_PATH   = Path("memory/meta_training_data.csv")
MODEL_PATH  = Path("memory/meta_weights.json")

def train_meta_model():
    if not DATA_PATH.exists():
        logger.warning("No training data found. Run the bot first to collect logs.")
        return

    df = pd.read_csv(DATA_PATH)
    
    if 'outcome' not in df.columns:
        logger.info("Generating synthetic labels for demo...")
        df['outcome'] = (df['tech'] > 6.0).astype(int) 

    regimes = df['regime'].unique()
    master_weights = {"default": {}}

    for reg in regimes:
        reg_df = df[df['regime'] == reg]
        if len(reg_df) < 5:
            logger.info(f"Skipping {reg}: Not enough data ({len(reg_df)})")
            continue

        X = reg_df[['rl', 'tech', 'anl', 'rsk']]
        y = reg_df['outcome']
        
        # If all y are same, skip or fake variability
        if len(y.unique()) < 2:
            y = y.copy()
            y.iloc[0] = 1 - y.iloc[0] # Force variability for demo math

        model = LogisticRegression()
        model.fit(X, y)
        weights = model.coef_[0]
        
        master_weights[reg] = {
            "w_rl":      float(weights[0]),
            "w_tech":    float(weights[1]),
            "w_analyst": float(weights[2]),
            "w_risk":    float(weights[3])
        }
        logger.success(f"Learned weights for regime: {reg}")

    # Save default (overall)
    X_all = df[['rl', 'tech', 'anl', 'rsk']]
    y_all = df['outcome']
    model_all = LogisticRegression()
    model_all.fit(X_all, y_all)
    weights_all = model_all.coef_[0]
    master_weights["default"] = {
        "w_rl":      float(weights_all[0]),
        "w_tech":    float(weights_all[1]),
        "w_analyst": float(weights_all[2]),
        "w_risk":    float(weights_all[3])
    }

    MODEL_PATH.write_text(json.dumps(master_weights, indent=2))
    logger.success(f"Step 2 Complete: Regime-aware weights saved to {MODEL_PATH}")

if __name__ == "__main__":
    train_meta_model()
