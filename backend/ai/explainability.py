"""Per-record explanations computed from the actual trained models.

- occlusion (always available): contribution_f = model_output(x) - model_output(x with feature f replaced by the
  normal-training mean). Positive pushes the output up. For the detector the output is the anomaly score; for the
  classifier it is the model's estimated probability of the predicted class.
- shap_tree (only if the optional `shap` package is installed): TreeExplainer values for the random forest.
Raw-value z-scores against the normal training distribution are always reported alongside.
"""
import numpy as np

from .feature_extraction import FEATURES, FEATURE_UNITS


def occlusion(predict, x_scaled: np.ndarray, baseline_scaled: np.ndarray) -> np.ndarray:
    n = x_scaled.shape[1]
    base = float(predict(x_scaled)[0])
    X = np.repeat(x_scaled, n, axis=0)
    for j in range(n):
        X[j, j] = baseline_scaled[j]
    return base - np.asarray(predict(X), dtype=float)


def shap_contributions(rf, x_scaled: np.ndarray, class_idx: int) -> np.ndarray | None:
    try:
        import shap  # optional dependency

        sv = shap.TreeExplainer(rf).shap_values(x_scaled)
        if isinstance(sv, list):
            return np.asarray(sv[class_idx])[0]
        arr = np.asarray(sv)
        return arr[0, :, class_idx] if arr.ndim == 3 else arr[0]
    except Exception:  # noqa: BLE001 - any failure falls back to occlusion
        return None


def _rows(features: dict, contrib: np.ndarray, normal_stats: dict) -> list[dict]:
    out = []
    for f, c in zip(FEATURES, contrib):
        m, s = normal_stats[f]["mean"], normal_stats[f]["std"]
        out.append({"feature": f, "unit": FEATURE_UNITS[f], "value": round(float(features[f]), 6), "contribution": round(float(c), 6),
                    "normal_mean": round(m, 6), "normal_std": round(s, 6), "z_score": round((features[f] - m) / s if s > 1e-12 else 0.0, 3)})
    return sorted(out, key=lambda r: abs(r["contribution"]), reverse=True)


def explain_detector(bundle: dict, features: dict, x_scaled: np.ndarray) -> dict:
    baseline = bundle["scaler"].transform(np.array([[bundle["normal_stats"][f]["mean"] for f in FEATURES]]))[0]
    contrib = occlusion(bundle["detector"].score, x_scaled, baseline)
    return {"model": "isolation_forest", "method": "occlusion", "target": "anomaly score (higher = more anomalous)",
            "reference": "contribution = score(x) - score(x with the feature set to the normal-training mean)",
            "contributions": _rows(features, contrib, bundle["normal_stats"])}


def explain_classifier(bundle: dict, features: dict, x_scaled: np.ndarray, kind: str = "random_forest") -> dict:
    model = bundle["rf" if kind == "random_forest" else "lr"]
    pred = model.predict(x_scaled)[0]
    idx = int(list(model.classes_).index(pred))
    baseline = bundle["scaler"].transform(np.array([[bundle["normal_stats"][f]["mean"] for f in FEATURES]]))[0]
    contrib = shap_contributions(model, x_scaled, idx) if kind == "random_forest" else None
    method = "shap_tree" if contrib is not None else "occlusion"
    if contrib is None:
        contrib = occlusion(lambda X: model.predict_proba(X)[:, idx], x_scaled, baseline)
    return {"model": kind, "method": method, "target": f"model-estimated probability of '{pred}'",
            "reference": ("SHAP TreeExplainer values" if method == "shap_tree" else
                          "contribution = P(pred | x) - P(pred | x with the feature set to the normal-training mean)"),
            "contributions": _rows(features, contrib, bundle["normal_stats"])}
