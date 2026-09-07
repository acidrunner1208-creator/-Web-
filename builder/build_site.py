"""レースを収集 → シミュレーション → 静的サイト生成。

    python -m builder.build_site                 # 今日から9日先までの開催
    python -m builder.build_site --dates 20260912 20260913
    python -m builder.build_site --limit 6       # レース数を制限 (試験)
    DEMO_MODE=true python -m builder.build_site  # 合成データ
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from builder.config import get_settings
from builder.render import render_site
from builder.scraping.models import Race
from builder.sim.engine import simulate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("build")

_PAST_KEYS = ("date", "venue", "race_name", "field_size", "finish_pos", "popularity",
              "passing", "pace", "last_3f", "time_sec", "distance", "surface",
              "track_condition", "body_weight", "body_weight_diff", "margin", "weight_carried")

TARGET_DAYS_AHEAD = 8


def resolve_target_dates(today: date | None = None) -> list[str]:
    """今日から TARGET_DAYS_AHEAD 日先までの全日 (開催が無い日は自動でスキップされる)。"""
    today = today or date.today()
    return [(today + timedelta(days=i)).strftime("%Y%m%d") for i in range(TARGET_DAYS_AHEAD + 1)]


def _race_list(ymd: str):
    if get_settings().demo_mode:
        from builder.scraping.demo import demo_race_list

        return demo_race_list(ymd)
    from builder.scraping.netkeiba import fetch_race_list

    return fetch_race_list(ymd)


def _race_card(race_id: str, store=None) -> Race:
    s = get_settings()
    if s.demo_mode:
        from builder.scraping.demo import demo_race_card

        return demo_race_card(race_id)
    from builder.scraping.netkeiba import fetch_race_card

    return fetch_race_card(race_id, history_limit=s.history_limit, store=store)


def _workouts(race_id: str) -> dict:
    if get_settings().demo_mode:
        return {}
    from builder.scraping.netkeiba import fetch_workouts

    try:
        return fetch_workouts(race_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("workouts %s: %s", race_id, exc)
        return {}


def _past_summary(entry) -> list[dict]:
    out = []
    for r in entry.past_runs[:6]:
        d = r.model_dump()
        out.append({k: d.get(k) for k in _PAST_KEYS})
    return out


def build_race_payload(race: Race, n_sims: int, workouts: dict | None = None) -> dict:
    sim = simulate(race, n_sims=n_sims, workouts=workouts)
    past_by_num = {e.horse_number: _past_summary(e) for e in race.entries}
    id_by_num = {e.horse_number: e.horse_id for e in race.entries}
    for h in sim["horses"]:
        h["past"] = past_by_num.get(h["num"], [])
        h["horse_id"] = h.get("horse_id") or id_by_num.get(h["num"])
        h["netkeiba_url"] = (
            f"https://db.netkeiba.com/horse/{h['horse_id']}/" if h.get("horse_id") else None
        )
    return {
        "race_id": race.race_id, "kaisai_date": race.kaisai_date, "venue": race.venue,
        "race_number": race.race_number, "race_name": race.race_name,
        "start_time": race.start_time, "surface": race.surface, "distance": race.distance,
        "direction": race.direction, "weather": race.weather,
        "track_condition": race.track_condition, "race_class": race.race_class,
        "field_size": race.field_size,
        **sim,
    }


def _archive_recommended(out_dir: Path, r: dict) -> None:
    """settle 用に推奨買い目を恒久保存 (レース詳細JSONが window から外れても残す)。"""
    d = out_dir / "data" / "recommended"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{r['race_id']}.json").write_text(
        json.dumps({
            "race_id": r["race_id"], "kaisai_date": r["kaisai_date"], "venue": r["venue"],
            "race_number": r["race_number"], "race_name": r["race_name"],
            "recommended": [b for b in r["recommended"] if b.get("tracked")],
        }, ensure_ascii=False), encoding="utf-8",
    )


def run(dates: list[str], limit: int | None = None, out_dir: Path | None = None) -> dict:
    s = get_settings()
    out_dir = out_dir or s.out_path
    races_out: list[dict] = []
    done = 0

    store = None
    if not s.demo_mode:
        from builder.store import HorseStore

        store = HorseStore()
    active_ids: set[str] = set()

    for ymd in dates:
        iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
        try:
            items = _race_list(ymd)
        except Exception as exc:  # noqa: BLE001
            log.warning("race list %s failed: %s", ymd, exc)
            continue
        if items:
            log.info("[%s] %d races", ymd, len(items))
        for it in items:
            if limit and done >= limit:
                break
            try:
                race = _race_card(it.race_id, store=store)
                race.kaisai_date = iso
                race.race_name = race.race_name or it.race_name
                race.start_time = race.start_time or it.start_time
                if len([e for e in race.entries if not e.scratched]) < 4:
                    continue
                active_ids.update(e.horse_id for e in race.entries if e.horse_id)
                payload = build_race_payload(race, s.n_sims, _workouts(it.race_id))
                if not payload["horses"]:
                    continue
                races_out.append(payload)
                _archive_recommended(out_dir, payload)
                done += 1
                log.info("  %s%sR %s ✓ (conf=%.2f, %s)", race.venue or "", race.race_number or "",
                         race.race_name or "", payload["confidence"], payload["model"])
            except Exception as exc:  # noqa: BLE001
                log.warning("  %s failed: %s", it.race_id, exc)

    if store is not None and active_ids:
        removed = store.gc(active_ids)
        store.save_if_dirty()
        st = store.stats()
        log.info("horse store: %d頭 / %d走 / %skB (引退・長期不出走 %d頭を削除)",
                 st["horses"], st["runs"], st["kb"], len(removed))

    races_out.sort(key=lambda r: (r["kaisai_date"] or "", r["venue"] or "", r["race_number"] or 0))
    attention = sorted(races_out, key=lambda r: r["confidence"], reverse=True)[:3]

    groups: dict[tuple, list] = {}
    for r in races_out:
        groups.setdefault((r["kaisai_date"], r["venue"]), []).append(r)
    group_list = [{"date": k[0], "venue": k[1], "races": v} for k, v in sorted(groups.items())]

    model_state = _model_state()
    return {
        "dates": sorted({r["kaisai_date"] for r in races_out}) or
                 [f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in dates[:1]],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "demo_mode": s.demo_mode,
        "n_sims": s.n_sims,
        "model_state": model_state,
        "note": "単勝オッズはリアルタイム取得していません。各買い目には「適正オッズ」を掲載しています。",
        "races": races_out,
        "attention": attention,
        "groups": group_list,
    }


def _model_state() -> dict:
    try:
        from builder.model.model import RankModel

        m = RankModel.load()
        if m:
            return {"trained": True, "n_races": m.n_races, "updated": m.updated[:10]}
    except Exception:  # noqa: BLE001
        pass
    return {"trained": False, "n_races": 0, "updated": None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*", help="YYYYMMDD")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    s = get_settings()

    out = Path(args.out) if args.out else s.out_path
    dates = args.dates or resolve_target_dates()
    payload = run(dates, limit=args.limit or s.max_races, out_dir=out)
    render_site(out, payload)
    log.info("生成完了: %d レース -> %s", len(payload["races"]), out)


if __name__ == "__main__":
    main()
