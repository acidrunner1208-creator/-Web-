"""逐次学習: アプリが予想したレースの結果が出るたびに 1 レースずつ取り込む。

過去レースの再スクレイピング・全再学習はしない。
確定レースの (Xz, 勝ち馬) を partial_fit で 1 ステップ反映し、history にも追記する。
"""
from __future__ import annotations

import logging

from builder.model.dataset import append_history, race_to_sample
from builder.model.model import RankModel, append_trained_ids, load_trained_ids

log = logging.getLogger("model.update")


def update_from_races(race_ids: list[str], fresh_weight: float = 2.0) -> dict:
    trained = load_trained_ids()
    model = RankModel.load() or RankModel()
    new, done, losses = [], [], []
    for rid in race_ids:
        if rid in trained:
            continue
        try:
            s = race_to_sample(rid)
        except Exception as exc:  # noqa: BLE001
            log.warning("skip %s: %s", rid, exc)
            continue
        if not s:
            continue
        Xz, wi, iso = s
        # 新しいレースはやや強めに学習し、数エポック回す
        for _ in range(3):
            losses.append(model.partial_fit(Xz, wi, weight=fresh_weight))
        new.append((rid, iso, Xz, wi))
        done.append(rid)

    if new:
        append_history(new)
        append_trained_ids(done)
        model.save()
    log.info("逐次学習: %d レース反映 (累計 %d)", len(done), model.n_races)
    return {"updated": len(done), "avg_loss": (sum(losses) / len(losses)) if losses else None,
            "n_races_total": model.n_races}
