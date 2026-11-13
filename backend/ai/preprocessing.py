import math

import numpy as np
from sklearn.preprocessing import StandardScaler

from .feature_extraction import FEATURES


class TraceValidationError(ValueError):
    pass


def validate_trace(trace: dict) -> list[str]:
    """Raises TraceValidationError on a malformed trace; returns the list of checks that passed."""
    checks = []
    a, b = trace.get("addresses"), trace.get("branches")
    if not a or not isinstance(a, list) or len(a) > 20000:
        raise TraceValidationError("addresses must be a non-empty list (max 20000)")
    if any((not isinstance(x, int)) or x < 0 or x >= 2**32 for x in a):
        raise TraceValidationError("addresses must be integers in 0..2^32-1")
    checks.append(f"{len(a)} memory accesses in range")
    if not b or any(len(x) != 2 for x in b):
        raise TraceValidationError("branches must be a non-empty list of (pc, taken)")
    checks.append(f"{len(b)} branch outcomes well-formed")
    return checks


def validate_features(f: dict) -> None:
    for k in FEATURES:
        v = f.get(k)
        if v is None or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
            raise TraceValidationError(f"feature '{k}' is missing or not finite")


def to_matrix(rows: list[dict]) -> np.ndarray:
    return np.array([[r[k] for k in FEATURES] for r in rows], dtype=float)


def fit_scaler(X_train: np.ndarray) -> StandardScaler:
    """Fit on TRAINING data only (no leakage from the test set)."""
    return StandardScaler().fit(X_train)
