"""ブートストラップ学習: 過去レースを収集して RankModel を一から学習する。

    python -m builder.model.train --from 2023-01-01 --to 2025-12-31
    python -m builder.model.train --from 2020-01-01 --to 2020-06-30 --max-races 800

- レース数が多いと数時間かかる。日付範囲を分けて複数回に分けて実行してよい
  (各回で history に追記し、全 history から学習し直す)。
- 一度ブートストラップした後の日々の改良は `builder.model.update` が自動で行う。
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from builder.model.dataset import append_history, history_as_races, race_to_sample
from builder.model.features import FEATURE_ORDER
from builder.model.model import RankModel, append_trained_ids, load_trained_ids

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("train")


def enumerate_race_ids(d0: date, d1: date) -> list[str]:
    from builder.scraping.netkeiba import fetch_race_list

    ids: list[str] = []
    d = d0
    while d <= d1:
        try:
            items = fetch_race_list(d.strftime("%Y%m%d"))
            ids.extend(it.race_id for it in items)
        except Exception as exc:  # noqa: BLE001
            log.warning("race list %s: %s", d, exc)
        d += timedelta(days=1)
    return ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--max-races", type=int, default=None, help="この実行で新規に取り込む上限")
    ap.add_argument("--epochs", type=int, default=60)
    args = ap.parse_args()

    d0, d1 = date.fromisoformat(args.d_from), date.fromisoformat(args.d_to)
    trained = load_trained_ids()
    ids = [i for i in dict.fromkeys(enumerate_race_ids(d0, d1)) if i not in trained]
    if args.max_races:
        ids = ids[: args.max_races]
    log.info("新規対象レース: %d", len(ids))

    new_samples, done = [], []
    for n, rid in enumerate(ids, 1):
        try:
            s = race_to_sample(rid)
        except Exception as exc:  # noqa: BLE001
            log.warning("skip %s: %s", rid, exc)
            continue
        if s:
            Xz, wi, iso = s
            new_samples.append((rid, iso, Xz, wi))
            done.append(rid)
        if n % 25 == 0:
            log.info("  %d/%d 収集", n, len(ids))

    if new_samples:
        append_history(new_samples)
        append_trained_ids(done)
    log.info("history に %d レース追記", len(new_samples))

    races, weights = history_as_races()
    if len(races) < 50:
        log.warning("学習データ不足 (%d レース)。範囲を広げて再実行してください。", len(races))
        return
    model = RankModel()
    losses = model.fit(races, epochs=args.epochs, weights=weights)
    model.n_races = len(races)
    model.save()
    log.info("学習完了: %d レース / 初期loss=%.3f -> 最終loss=%.3f", len(races), losses[0], losses[-1])
    log.info("theta: %s", {f: round(float(t), 3) for f, t in zip(FEATURE_ORDER, model.theta)})


if __name__ == "__main__":
    main()
