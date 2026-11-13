import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score


def binary_metrics(y_true_anom: np.ndarray, y_pred_anom: np.ndarray, scores: np.ndarray) -> dict:
    """Positive class = anomalous. Matrix layout: [[TN, FP], [FN, TP]]."""
    tn, fp, fn, tp = confusion_matrix(y_true_anom, y_pred_anom, labels=[False, True]).ravel()
    return {
        "accuracy": round(float(accuracy_score(y_true_anom, y_pred_anom)), 4),
        "precision": round(float(precision_score(y_true_anom, y_pred_anom, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true_anom, y_pred_anom, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true_anom, y_pred_anom, zero_division=0)), 4),
        "false_positive_rate": round(float(fp / (fp + tn)) if (fp + tn) else 0.0, 4),
        "roc_auc": round(float(roc_auc_score(y_true_anom, scores)), 4),
        "confusion_matrix": {"labels": ["normal", "anomalous"], "matrix": [[int(tn), int(fp)], [int(fn), int(tp)]]},
        "n_test": int(len(y_true_anom)),
    }


def multiclass_metrics(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict:
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_precision": round(float(precision_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
        "macro_recall": round(float(recall_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
        "macro_f1": round(float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
        "confusion_matrix": {"labels": labels, "matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist()},
        "n_test": len(y_true),
    }
