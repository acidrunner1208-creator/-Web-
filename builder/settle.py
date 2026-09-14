"""確定レースの結果を取得し、推奨買い目の実績を ledger に記録 + モデルを逐次学習する。

    python -m builder.settle

- `public/data/recommended/*.json` のうち、まだ処理していない過去レースを処理
- 結果が取得できたレースは (成績に載せるかに関わらず) すべて学習モデルに逐次反映
  (`builder.model.update`)
- 成績 (ledger.entries) に反映するのは (1) その日の注目レース TOP3 だったレースのみ・
  かつ (2) 軸馬(単勝)の確定オッズでの期待値がプラスと判定できたレースのみ。
  それ以外は「除外」として `ledger.excluded` に理由つきで記録し、損益には含めない
- 対象レースは単勝／3連複／3連単 を各100円単位で購入したと仮定し、実際の払戻から
  損益を計算して `public/data/ledger.json` を更新
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


def _axis_final_ev(rec: dict, race) -> tuple[float | None, float | None]:
    """軸馬(単勝)の確定オッズと、そのオッズでの期待値 (的中率×オッズ−1) を返す。

    3連複・3連単の個々の組合せの確定オッズはレース後には取得できないため、
    レース全体を「買うか見送るか」の判定には単勝の確定オッズを用いる
    (＝アプリが最終的に推した軸馬が、市場の最終オッズでも妙味があったか)。
    取得できない場合は (None, None)。
    """
    tansho = next((b for b in rec.get("recommended", []) if b.get("key") == "tansho"), None)
    if not tansho or tansho.get("hit_prob") is None:
        return None, None
    axis = (tansho.get("axis") or tansho.get("nums") or [None])[0]
    if axis is None:
        return None, None
    entry = next((e for e in race.entries if e.horse_number == axis), None)
    if entry is None or entry.result_odds is None:
        return None, None
    return entry.result_odds, tansho["hit_prob"] * entry.result_odds - 1.0


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

    if key == "sanrentan":
        combos = [list(c) for c in bet.get("combos", [])]
        if not combos and bet.get("nums"):          # 旧形式(単点)フォールバック
            combos = [list(bet["nums"])]
        res["stake"] = len(combos) * UNIT
        rows = payouts.get("trifecta", [])
        actual = list(top3)                          # [1着, 2着, 3着]
        if any(c == actual for c in combos):
            res["hit"] = True
            res["ret"] = rows[0]["yen"] if rows else 0
        return res

    if key in ("sanrenpuku", "sanrenpuku_formation", "sanrenpuku_nagashi"):
        if bet.get("combos"):
            combos = {frozenset(c) for c in bet["combos"]}
        elif bet.get("partners"):                    # 旧・軸1頭ながし形式
            axis, partners = bet["axis"][0], bet["partners"]
            combos = {frozenset((axis, a, b))
                      for i, a in enumerate(partners) for b in partners[i + 1:]}
        else:
            combos = set()
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
    ledger = _load_json(ledger_path, {"entries": [], "excluded": []})
    excluded = ledger.get("excluded", [])
    excluded_ids = {x["race_id"] for x in excluded}
    processed_ids = {e["race_id"] for e in ledger["entries"]} | excluded_ids
    today = date.today()

    # モデルの学習データは注目レース以外も含めて全レースぶん取り込む
    # (成績=ledger に載せるかどうかとは別の話)。ledger に載せるのは
    # 「注目レース TOP3」かつ「軸馬の確定オッズでの期待値がプラス」の
    # レースのみ。
    new_entries, new_excluded, model_ids = [], [], []
    candidates = 0
    for f in sorted(rec_dir.glob("*.json")) if rec_dir.exists() else []:
        rec = _load_json(f, None)
        if not rec or rec["race_id"] in processed_ids:
            continue
        try:
            rdate = date.fromisoformat(rec["kaisai_date"])
        except (ValueError, KeyError):
            continue
        if rdate > today:
            continue
        candidates += 1
        try:
            race = fetch_race_result(rec["race_id"])
            top3 = _actual_top3(race)
            if len(top3) < 3:
                # キャッシュされた不完全なページの可能性があるのでキャッシュを
                # 無視して1度だけ取り直す (自己修復)。
                race = fetch_race_result(rec["race_id"], use_cache=False)
                top3 = _actual_top3(race)
            if len(top3) < 3:
                log.warning("result %s: 着順3頭未満 (entries=%d)", rec["race_id"], len(race.entries))
                continue
            payouts = fetch_payouts(rec["race_id"])
            if not payouts:
                payouts = fetch_payouts(rec["race_id"], use_cache=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("result %s: %s: %s", rec["race_id"], type(exc).__name__, exc)
            continue
        if not payouts:
            log.warning("result %s: 払戻が取得できませんでした", rec["race_id"])
            continue

        # 結果が取れたレースは (成績に載るかに関わらず) モデルの学習対象にする。
        model_ids.append(rec["race_id"])

        # 注目レース (その日の自信度 TOP3、最終更新時点) でなければ成績には載せない。
        # 古い形式 (attention キーが無い) は判定できないため対象外扱い。
        if not rec.get("attention"):
            new_excluded.append({"race_id": rec["race_id"], "reason": "not_attention"})
            continue

        final_odds, ev = _axis_final_ev(rec, race)
        if ev is None or ev <= 0:
            log.info("見送り %s %s: 軸馬の最終オッズでの期待値がマイナス (odds=%s, ev=%s)",
                      rec["race_id"], rec.get("race_name", ""), final_odds,
                      None if ev is None else round(ev, 3))
            new_excluded.append({"race_id": rec["race_id"], "reason": "negative_ev",
                                  "final_odds": final_odds, "ev": None if ev is None else round(ev, 3)})
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
        log.info("settled %s %s: stake=%d ret=%d profit=%+d",
                 rec["race_id"], rec.get("race_name", ""), stake, ret, ret - stake)

    if new_entries or new_excluded:
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
            "excluded": excluded + new_excluded,
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

    not_attn = sum(1 for x in new_excluded if x["reason"] == "not_attention")
    neg_ev = sum(1 for x in new_excluded if x["reason"] == "negative_ev")
    log.info("完了: 結果取得%d件・学習%d件 / 成績反映=%d (注目レース対象外%d件・最終オッズ期待値マイナス%d件を除外)",
              candidates, len(model_ids), len(new_entries), not_attn, neg_ev)
    return {"settled": len(new_entries), "model": updated, "candidates": candidates,
            "model_updates": len(model_ids), "excluded_not_attention": not_attn,
            "excluded_negative_ev": neg_ev}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    r = settle(Path(args.out) if args.out else None)
    log.info("完了: %s", r)


if __name__ == "__main__":
    main()
