"""HorseModel.features -> レース内で標準化した特徴量行列。"""
from __future__ import annotations

import numpy as np

from builder.sim.horse_model import HorseModel

FEATURE_ORDER: list[str] = [
    "rating", "form_recent", "win_rate", "top3_rate", "best_last3f", "speed_best",
    "surface_fit", "dist_fit", "cond_fit", "class_delta", "rotation", "weight",
    "draw", "early_ratio", "n_runs", "workout",
]
D = len(FEATURE_ORDER)


def race_matrix(models: list[HorseModel]) -> np.ndarray:
    """(H, D) 生の特徴量。"""
    return np.array(
        [[float(m.features.get(f, 0.0)) for f in FEATURE_ORDER] for m in models],
        dtype=float,
    )


def standardize(X: np.ndarray) -> np.ndarray:
    """列ごとにレース内 z-score。分散が無い列は 0。"""
    if X.ndim != 2 or X.shape[0] < 2:
        return np.zeros_like(X)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-9] = 1.0
    Z = (X - mean) / std
    return np.clip(Z, -4.0, 4.0)
