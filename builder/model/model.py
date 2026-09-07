"""条件付きロジット (レース内 softmax) の勝ち馬モデル。

- 線形: strength_i = theta . x_i  (x はレース内で標準化済み)
- 損失: 勝ち馬の負の対数尤度
- 勾配: X^T (p - y)   -> SGD で逐次更新できる (オンライン学習向き)

一度ブートストラップ学習したあとは、アプリが予想したレースの結果が出るたびに
`partial_fit` を 1 回ずつ呼んでモデルを少しずつ改良する。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from builder.model.features import D, FEATURE_ORDER

STATE_DIR = Path(__file__).parent / "state"
MODEL_PATH = STATE_DIR / "model.json"
TRAINED_IDS_PATH = STATE_DIR / "trained_races.txt"


class RankModel:
    def __init__(self, lr: float = 0.05, l2: float = 2e-4, spread: float = 11.0) -> None:
        self.theta = np.zeros(D)
        self.lr = lr
        self.l2 = l2
        self.spread = spread            # sim に渡す strength のポイント尺度
        self.n_updates = 0
        self.n_races = 0
        self.created = datetime.now(timezone.utc).isoformat()
        self.updated = self.created

    # ------------------------------------------------------------------
    def strength(self, Xz: np.ndarray) -> np.ndarray:
        return Xz @ self.theta

    def win_probs(self, Xz: np.ndarray) -> np.ndarray:
        s = self.strength(Xz)
        e = np.exp(s - s.max())
        return e / e.sum()

    def partial_fit(self, Xz: np.ndarray, winner_idx: int, weight: float = 1.0,
                    lr: float | None = None) -> float:
        if Xz.shape[0] < 2 or not (0 <= winner_idx < Xz.shape[0]):
            return 0.0
        p = self.win_probs(Xz)
        y = np.zeros(len(p))
        y[winner_idx] = 1.0
        grad = Xz.T @ (p - y) + self.l2 * self.theta
        self.theta -= (lr if lr is not None else self.lr) * weight * grad
        self.n_updates += 1
        self.n_races += 1
        self.updated = datetime.now(timezone.utc).isoformat()
        return float(-np.log(max(p[winner_idx], 1e-12)))

    def fit(self, races: list[tuple[np.ndarray, int]], epochs: int = 40,
            weights: list[float] | None = None) -> list[float]:
        """ブートストラップ学習。races=[(Xz, winner_idx), ...]"""
        weights = weights or [1.0] * len(races)
        losses = []
        rng = np.random.default_rng(0)
        for ep in range(epochs):
            lr = self.lr * (0.5 ** (ep / max(epochs / 3, 1)))
            order = rng.permutation(len(races))
            tot = 0.0
            for i in order:
                Xz, wi = races[i]
                tot += self.partial_fit(Xz, wi, weight=weights[i], lr=lr)
            losses.append(tot / max(len(races), 1))
        self.n_races = len(races)
        return losses

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "theta": self.theta.tolist(),
            "feature_order": FEATURE_ORDER,
            "lr": self.lr, "l2": self.l2, "spread": self.spread,
            "n_updates": self.n_updates, "n_races": self.n_races,
            "created": self.created, "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RankModel":
        m = cls(lr=d.get("lr", 0.05), l2=d.get("l2", 2e-4), spread=d.get("spread", 11.0))
        theta = np.array(d.get("theta", []), dtype=float)
        if theta.shape == (D,) and d.get("feature_order") == FEATURE_ORDER:
            m.theta = theta
        m.n_updates = int(d.get("n_updates", 0))
        m.n_races = int(d.get("n_races", 0))
        m.created = d.get("created", m.created)
        m.updated = d.get("updated", m.updated)
        return m

    def save(self, path: Path = MODEL_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "RankModel | None":
        if not path.exists():
            return None
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return None

    @property
    def trust(self) -> float:
        """学習量に応じて 0..1。sim でヒューリスティックとの混合比に使う。"""
        return float(min(1.0, self.n_races / 800.0))


def load_trained_ids(path: Path = TRAINED_IDS_PATH) -> set[str]:
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()}


def append_trained_ids(ids: list[str], path: Path = TRAINED_IDS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for i in ids:
            fh.write(i + "\n")
