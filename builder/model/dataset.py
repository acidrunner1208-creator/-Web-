"""過去レース -> 学習サンプル (Xz, winner_idx) の変換と、学習データの蓄積。"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from builder.model.features import D, race_matrix, standardize
from builder.model.model import STATE_DIR
from builder.sim.horse_model import build_horse_model

log = logging.getLogger("dataset")

HISTORY_PATH = STATE_DIR / "history.npz"
MAX_RACES_KEPT = 6000


def race_to_sample(race_id: str) -> tuple[np.ndarray, int, str] | None:
    """確定レースを (Xz(H,D), winner_idx, iso_date) に変換 (過去戦績は開催日より前のみ)。"""
    from builder.scraping.netkeiba import fetch_horse_history, fetch_race_result

    race = fetch_race_result(race_id)
    if not race.kaisai_date or not race.distance:
        return None
    as_of = date.fromisoformat(race.kaisai_date)
    runners = [e for e in race.entries if e.result_finish_pos and not e.scratched]
    if len(runners) < 5:
        return None
    for e in runners:
        if e.horse_id:
            try:
                e.past_runs = fetch_horse_history(e.horse_id, before=as_of)
            except Exception as exc:  # noqa: BLE001
                log.warning("history %s: %s", e.horse_id, exc)
                e.past_runs = []
    models = [build_horse_model(e, race, as_of=as_of) for e in runners]
    Xz = standardize(race_matrix(models))
    winner_idx = min(range(len(runners)), key=lambda i: runners[i].result_finish_pos or 99)
    return Xz, winner_idx, race.kaisai_date


# --------------------------------------------------------------------- 蓄積
def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"X": np.zeros((0, D)), "ptr": [0], "winner": [], "date": [], "race_id": []}
    z = np.load(HISTORY_PATH, allow_pickle=True)
    return {
        "X": z["X"], "ptr": list(z["ptr"]), "winner": list(z["winner"]),
        "date": list(z["date"]), "race_id": list(z["race_id"]),
    }


def append_history(samples: list[tuple[str, str, np.ndarray, int]]) -> None:
    """samples: [(race_id, iso_date, Xz, winner_idx), ...]"""
    h = load_history()
    Xs = [h["X"]] if h["X"].shape[0] else []
    ptr, winner, dt, rid = h["ptr"], h["winner"], h["date"], h["race_id"]
    seen = set(rid)
    for race_id, iso, Xz, wi in samples:
        if race_id in seen:
            continue
        Xs.append(Xz)
        ptr.append(ptr[-1] + Xz.shape[0])
        winner.append(wi)
        dt.append(iso)
        rid.append(race_id)
    if not Xs:
        return
    X = np.vstack(Xs)
    # 直近 MAX_RACES_KEPT レースに制限
    if len(rid) > MAX_RACES_KEPT:
        cut = len(rid) - MAX_RACES_KEPT
        start_row = ptr[cut]
        X = X[start_row:]
        ptr = [p - start_row for p in ptr[cut:]]
        winner, dt, rid = winner[cut:], dt[cut:], rid[cut:]
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        HISTORY_PATH, X=X.astype(np.float32), ptr=np.array(ptr),
        winner=np.array(winner), date=np.array(dt), race_id=np.array(rid),
    )


def history_as_races(recency_halflife_days: int = 300) -> tuple[list[tuple[np.ndarray, int]], list[float]]:
    h = load_history()
    if not h["winner"]:
        return [], []
    X, ptr = h["X"], h["ptr"]
    today = date.today()
    races, weights = [], []
    for k in range(len(h["winner"])):
        Xz = np.asarray(X[ptr[k]:ptr[k + 1]], dtype=float)
        races.append((Xz, int(h["winner"][k])))
        try:
            age = (today - date.fromisoformat(str(h["date"][k]))).days
        except ValueError:
            age = 0
        weights.append(0.5 ** (max(age, 0) / recency_halflife_days))
    return races, weights
