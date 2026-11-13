from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression


def build_random_forest(seed: int = 0) -> RandomForestClassifier:
    return RandomForestClassifier(n_estimators=200, min_samples_leaf=2, random_state=seed, n_jobs=1)


def build_logistic_regression(seed: int = 0) -> LogisticRegression:
    return LogisticRegression(max_iter=3000, random_state=seed)
