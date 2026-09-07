"""確定レースの結果を取得し、推奨買い目の実績を ledger に記録 + モデルを逐次学習する。

    python -m builder.settle

- `public/data/recommended/*.json` のうち、まだ清算していない過去レースを処理
- 単勝／3連複フォーメーション／3連複軸1頭ながし を各100円単位で購入したと仮定し、
  実際の払戻から損益を計算して `public/data/ledger.json` を更新
- 清算できたレースは学習モデルに逐次反映 (`builder.model.update`)
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from builder.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("settle")

UNIT = 100  # 1点あたりの購入額(円)


def _load_json(p: Path, default):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return default
    return default


def _actual_top3(race) -> list[int]:
    finishers = sorted(
        (e for e in race.entries if e.result_finish_pos and not e.scratched),
        key=lambda e: e.result_finish_pos,
    )
    return [e.horse_number for e in finishers[:3] if e.horse_number]


def _settle_bet(bet: dict, top3: list[int], payouts: dict) -> dict:
    key = bet["key"]
    top3_set = frozenset(top3)
    res = {"key": key, "type": bet["type"], "hit": False, "stake": 0, "ret": 0}

    if key == "tansho":
        res["stake"] = UNIT
        axis = (bet.get("axis") or bet.get("nums") or [None])[0]
        for row in payouts.get("win", []):
            if row["combo"] and row["combo"][0] == axis:
                res["hit"] = True
                res["ret"] = row["yen"]
        return res

    if key in ("sanrenpuku_formation", "sanrenpuku_nagashi"):
        if key == "sanrenpuku_formation":
            combos = {frozenset(c) for c in bet["combos"]}
        else:
            axis, partners = bet["axis"][0], bet["partners"]
            combos = {frozenset((axis, a, b))
                      for i, a in enumerate(partners) for b in partners[i + 1:]}
        res["stake"] = len(combos) * UNIT
        rows = payouts.get("trio", [])
        if len(top3_set) == 3 and frozenset(top3_set) in combos:
            res["hit"] = True
            res["ret"] = rows[0]["yen"] if rows else 0
        return res
    return res


def settle(out_dir: Path | None = None) -> dict:
    from builder.scraping.netkeiba import fetch_payouts, fetch_race_result

    out_dir = out_dir or get_settings().out_path
    rec_dir = out_dir / "data" / "recommended"
    ledger_path = out_dir / "data" / "ledger.json"
    ledger = _load_json(ledger_path, {"entries": []})
    settled_ids = {e["race_id"] for e in ledger["entries"]}
    today = date.today()

    new_entries, model_ids = [], []
    for f in sorted(rec_dir.glob("*.json")) if rec_dir.exists() else []:
        rec = _load_json(f, None)
        if not rec or rec["race_id"] in settled_ids:
            continue
        try:
            rdate = date.fromisoformat(rec["kaisai_date"])
        except (ValueError, KeyError):
            continue
        if rdate > today:
            continue
        try:
            race = fetch_race_result(rec["race_id"])
            top3 = _actual_top3(race)
            if len(top3) < 3:
                continue
            payouts = fetch_payouts(rec["race_id"])
        except Exception as exc:  # noqa: BLE001
            log.warning("result %s: %s", rec["race_id"], exc)
            continue
        if not payouts:
            continue

        bets = [_settle_bet(b, top3, payouts) for b in rec["recommended"]]
        stake = sum(b["stake"] for b in bets)
        ret = sum(b["ret"] for b in bets)
        new_entries.append({
            "race_id": rec["race_id"], "date": rec["kaisai_date"], "venue": rec.get("venue"),
            "race_number": rec.get("race_number"), "name": rec.get("race_name"),
            "top3": top3, "bets": bets,
            "stake": stake, "ret": ret, "profit": ret - stake,
        })
        model_ids.append(rec["race_id"])
        log.info("settled %s %s: stake=%d ret=%d profit=%+d",
                 rec["race_id"], rec.get("race_name", ""), stake, ret, ret - stake)

    if new_entries:
        alle = ledger["entries"] + new_entries
        alle.sort(key=lambda e: (e["date"], e["race_id"]))
        cum_s = cum_r = 0
        for e in alle:
            cum_s += e["stake"]
            cum_r += e["ret"]
            e["cum_stake"] = cum_s
            e["cum_ret"] = cum_r
            e["cum_profit"] = cum_r - cum_s
        hit = sum(1 for e in alle if e["profit"] > 0)
        ledger = {
            "updated": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "races": len(alle), "stake": cum_s, "ret": cum_r, "profit": cum_r - cum_s,
                "roi": round(cum_r / cum_s, 4) if cum_s else 0.0, "hit_races": hit,
            },
            "entries": alle,
        }
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")

    updated = {}
    if model_ids:
        try:
            from builder.model.update import update_from_races

            updated = update_from_races(model_ids)
        except Exception as exc:  # noqa: BLE001
            log.warning("model update failed: %s", exc)

    return {"settled": len(new_entries), "model": updated}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    r = settle(Path(args.out) if args.out else None)
    log.info("完了: %s", r)


if __name__ == "__main__":
    main()
