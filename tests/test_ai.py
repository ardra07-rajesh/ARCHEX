import os
import tempfile

import numpy as np
import pytest

from app.ai import pipeline
from app.ai.feature_extraction import FEATURES, extract_features
from app.ai.preprocessing import TraceValidationError, to_matrix, validate_trace
from app.simulation.timing.trace_generator import SCENARIOS, generate_trace

_CACHE: dict = {}


def bundle():
    if "b" not in _CACHE:
        _CACHE["b"] = pipeline.train_all(n_per_class=60, n_test_per_class=30, seed=1, save=False)
        pipeline.reset_cache()  # train_all caches globally; keep tests isolated
    return _CACHE["b"]


def test_traces_are_deterministic_and_features_finite():
    for sc in SCENARIOS:
        t = generate_trace(sc, 5)
        assert t == generate_trace(sc, 5) and t != generate_trace(sc, 6)
        f = extract_features(t)
        assert list(f) == FEATURES and all(np.isfinite(v) for v in f.values())
        assert 0 <= f["cache_hit_ratio"] <= 1 and 0 <= f["access_pattern_irregularity"] <= 1


def test_trace_validation_rejects_bad_input():
    with pytest.raises(TraceValidationError):
        validate_trace({"addresses": [], "branches": [(4, True)]})
    with pytest.raises(TraceValidationError):
        validate_trace({"addresses": [-1], "branches": [(4, True)]})


def test_no_train_test_leakage():
    b = bundle()
    tr, te = b["config"]["train_seed_range"], b["config"]["test_seed_range"]
    assert tr[1] < te[0]  # disjoint, independently generated seed ranges
    feats, _ = pipeline._dataset(60, tr[0])
    X = to_matrix(feats)
    assert np.allclose(b["scaler"].mean_, X.mean(axis=0))  # scaler fitted on training data only


def test_metrics_are_consistent_and_sensible():
    m = bundle()["metrics"]
    iso = m["isolation_forest"]
    cm = iso["confusion_matrix"]["matrix"]
    assert sum(sum(r) for r in cm) == iso["n_test"] == 120
    assert iso["roc_auc"] > 0.8 and 0 <= iso["false_positive_rate"] <= 1
    for k in ("random_forest", "logistic_regression"):
        mc = m[k]["multiclass"]
        assert sum(sum(r) for r in mc["confusion_matrix"]["matrix"]) == mc["n_test"]
        assert mc["accuracy"] > 0.7 and 0 <= m[k]["binary"]["f1"] <= 1


def test_detector_threshold_targets_false_positive_rate_on_normal_training_data():
    b = bundle()
    det = b["detector"]
    assert 0.03 <= (det.train_scores_sorted > det.threshold).mean() <= 0.08


def test_save_load_roundtrip_and_deterministic_analysis():
    old = os.environ.get("ARCHEX_MODEL_DIR")
    with tempfile.TemporaryDirectory() as d:
        os.environ["ARCHEX_MODEL_DIR"] = d
        try:
            pipeline.reset_cache()
            with pytest.raises(pipeline.ModelsNotTrained):
                pipeline.analyze("normal", 1)
            assert pipeline.model_status()[0] == "unavailable"
            pipeline.train_all(n_per_class=40, n_test_per_class=20, seed=2, save=True)
            a = pipeline.analyze("cache_contention", 9)
            pipeline.reset_cache()
            b = pipeline.analyze("cache_contention", 9)
            assert a["detection"]["anomaly_score"] == b["detection"]["anomaly_score"]
            assert pipeline.model_status()[0] == "online"
        finally:
            if old is None:
                os.environ.pop("ARCHEX_MODEL_DIR", None)
            else:
                os.environ["ARCHEX_MODEL_DIR"] = old
            pipeline.reset_cache()


def test_analysis_result_structure_and_explanations():
    pipeline._BUNDLE = bundle()
    try:
        r = pipeline.analyze("timing_probe", 3)
    finally:
        pipeline.reset_cache()
    assert r["detection"]["classification"] in ("normal", "anomalous") and "Not a probability" in r["detection"]["score_note"]
    assert abs(sum(r["classification"]["class_probabilities"].values()) - 1) < 1e-3
    for part in ("detector", "classifier"):
        e = r["explanation"][part]
        assert e["method"] in ("occlusion", "shap_tree") and len(e["contributions"]) == 9
        mags = [abs(c["contribution"]) for c in e["contributions"]]
        assert mags == sorted(mags, reverse=True)
    assert r["risk"]["level"] in ("low", "moderate", "high")
