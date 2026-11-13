import numpy as np
from sklearn.ensemble import IsolationForest


class AnomalyDetector:
    """Isolation Forest trained on normal traces only. Score = -score_samples (higher = more anomalous).

    The decision threshold is the `quantile` of scores of the (training) normal traces, so it targets a false-positive
    rate of roughly 1 - quantile on normal data. The score is NOT a probability.
    """

    def __init__(self, seed: int = 0, quantile: float = 0.95):
        self.model = IsolationForest(n_estimators=200, contamination="auto", random_state=seed)
        self.quantile = quantile
        self.threshold = 0.0
        self.train_scores_sorted: np.ndarray = np.array([])

    def fit(self, X_normal_scaled: np.ndarray) -> "AnomalyDetector":
        self.model.fit(X_normal_scaled)
        s = self.score(X_normal_scaled)
        self.train_scores_sorted = np.sort(s)
        self.threshold = float(np.quantile(s, self.quantile))
        return self

    def score(self, X_scaled: np.ndarray) -> np.ndarray:
        return -self.model.score_samples(X_scaled)

    def predict(self, X_scaled: np.ndarray) -> np.ndarray:
        return self.score(X_scaled) > self.threshold

    def percentile_vs_normal(self, score: float) -> float:
        """Share of normal training traces with a score at or below this one."""
        return float(np.searchsorted(self.train_scores_sorted, score, side="right") / len(self.train_scores_sorted))
