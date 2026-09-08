from pathlib import Path

import numpy as np

from builder.build_site import build_race_payload, run
from builder.render import render_site
from builder.scraping.demo import demo_race_card
from builder.sim.engine import simulate
from builder.sim.horse_model import build_horse_model


def test_horse_model_features():
    race = demo_race_card("202605010111")
    m = build_horse_model(race.entries[0], race)
    assert m.style in ("逃げ", "先行", "差し", "追込")
    assert 0.0 <= m.early_ratio <= 1.0
    assert m.sigma >= 6.0
    from builder.model.features import FEATURE_ORDER

    assert set(m.features) == set(FEATURE_ORDER)


def test_simulate_probabilities():
    race = demo_race_card("202605010111")
    res = simulate(race, n_sims=3000)
    active = [e for e in race.entries if not e.scratched]
    assert len(res["horses"]) == len(active)
    assert abs(sum(h["win_prob"] for h in res["horses"]) - 1.0) < 0.05
    assert abs(sum(h["place_prob"] for h in res["horses"]) - 3.0) < 0.2
    assert res["horses"][0]["rank"] == 1
    assert res["horses"][0]["fair_win_odds"] > 1.0
    assert len(res["podium"]) == 3 * res["podium_n"]

    # 表示する数値の整合性: 各馬 勝率 <= 連対率 <= 複勝率、適正オッズ = 1/確率
    for h in res["horses"]:
        assert h["win_prob"] <= h["top2_prob"] + 1e-9 <= h["place_prob"] + 2e-9
        if h["win_prob"] > 0.01:
            assert abs(h["fair_win_odds"] * h["win_prob"] - 1.0) < 0.05   # 適正オッズ ≒ 1/勝率
    assert abs(sum(h["top2_prob"] for h in res["horses"]) - 2.0) < 0.05
    # はっきり度は勝率・複勝率とは別物の段階ラベル
    assert res["confidence_tier"] in ("高", "中", "低")
    assert 0.0 <= res["confidence"] <= 1.0


def test_recommended_bets_and_checker_data():
    race = demo_race_card("202605010107")
    p = build_race_payload(race, n_sims=4000)
    keys = {b["key"] for b in p["recommended"]}
    assert {"tansho", "sanrenpuku", "sanrentan"} <= keys
    assert "sanrenpuku_nagashi" not in keys      # 3連複軸流しは廃止
    for b in p["recommended"]:
        assert 0.0 <= b["hit_prob"] <= 1.0
        assert b["fair_odds"] >= 1.0
    tracked = {b["key"] for b in p["recommended"] if b.get("tracked")}
    assert tracked == {"tansho", "sanrenpuku", "sanrentan"}
    for key in ("sanrenpuku", "sanrentan"):
        b = next(x for x in p["recommended"] if x["key"] == key)
        assert b["method"] in ("流し", "フォーメーション")
        assert b["unit"] == len(b["combos"]) >= 4
        assert all(len(set(c)) == 3 for c in b["combos"])
    # 単勝の推定的中率 == 軸馬の勝率
    tan = next(b for b in p["recommended"] if b["key"] == "tansho")
    assert abs(tan["hit_prob"] - p["horses"][0]["win_prob"]) < 1e-6
    # podium で複勝率を再現できる
    pod = np.array(p["podium"]).reshape(-1, 3)
    top = p["horses"][0]["num"]
    place_from_pod = (pod == top).any(axis=1).mean()
    assert abs(place_from_pod - p["horses"][0]["place_prob"]) < 0.05


def test_animation_course():
    race = demo_race_card("202605010109")
    p = build_race_payload(race, n_sims=3000)
    a = p["animation"]
    assert a["venue"] in ("東京", "中山", "阪神")
    for h in a["horses"]:
        assert len(h["rank_track"]) == a["ticks"] + 1
        assert len(h["pos_track"]) == a["ticks"] + 1
        assert h["rank_track"][-1] == h["finish"]
        # 各馬の進捗はほぼ単調増加 (隊列変化による小さな戻りは許容)、ゴール付近で 1.0 近辺
        assert all(b >= a_ - 0.03 for a_, b in zip(h["pos_track"], h["pos_track"][1:]))
        assert h["pos_track"][-1] >= h["pos_track"][0]
        assert 0.82 <= h["pos_track"][-1] <= 1.02
    assert sorted(h["rank_track"][-1] for h in a["horses"]) == list(range(1, len(a["horses"]) + 1))
    # ゴール時の進捗の並び == 着順
    by_pos = sorted(a["horses"], key=lambda h: h["pos_track"][-1], reverse=True)
    assert [h["finish"] for h in by_pos] == list(range(1, len(a["horses"]) + 1))


def test_full_build_and_render(tmp_path: Path):
    payload = run(["20260912", "20260913"], limit=5, out_dir=tmp_path)
    assert 1 <= len(payload["races"]) <= 5
    assert len(payload["attention"]) == 3
    render_site(tmp_path, payload)
    assert (tmp_path / "index.html").exists()
    rid = payload["races"][0]["race_id"]
    html = (tmp_path / "races" / f"{rid}.html").read_text(encoding="utf-8")
    assert "レース展開シミュレーション" in html
    assert "推奨買い目" in html
    assert "買い目チェッカー" in html
    assert "適正" in html
    assert "予測手法" not in html
    assert (tmp_path / "assets" / "bet-check.js").exists()
    assert (tmp_path / "data" / "recommended" / f"{rid}.json").exists()


def test_target_dates():
    from datetime import date

    from builder.build_site import resolve_target_dates

    d = resolve_target_dates(date(2026, 9, 8))
    assert d[0] == "20260908" and len(d) == 9
