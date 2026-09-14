import json

import numpy as np

import builder.render as render
from builder.model.features import D
from builder.model.model import RankModel
from builder.render import roi_headline
from builder.scraping.models import Entry, Race
from builder.settle import _axis_final_ev, _settle_bet, settle


def _entry(date, stake, ret):
    return {"date": date, "stake": stake, "ret": ret, "profit": ret - stake}


def test_roi_headline_empty():
    h = roi_headline({"entries": []})
    assert h["races"] == 0 and h["profit"] == 0 and h["profit_rate"] == 0.0
    assert h["chart"] == ""


def test_roi_headline_computes_rate_and_filters_by_launch(monkeypatch):
    monkeypatch.setattr(render, "LAUNCH_DATE", "2026-09-08")
    ledger = {"entries": [
        _entry("2026-09-01", 1000, 5000),   # 運用開始前 → 無視
        _entry("2026-09-13", 1000, 1500),   # +500
        _entry("2026-09-14", 1000, 0),      # -1000
    ]}
    h = roi_headline(ledger)
    assert h["races"] == 2
    assert h["stake"] == 2000 and h["ret"] == 1500
    assert h["profit"] == -500
    assert h["profit_rate"] == -25.0          # -500 / 2000
    assert h["recovery_rate"] == 75.0
    assert h["hit_races"] == 1
    assert len(h["series"]) == 3 and h["series"][0] == 0.0


def test_roi_headline_by_bet_type(monkeypatch):
    monkeypatch.setattr(render, "LAUNCH_DATE", "2026-09-08")
    ledger = {"entries": [
        {"date": "2026-09-13", "stake": 300, "ret": 480, "profit": 180, "bets": [
            {"key": "tansho", "stake": 100, "ret": 480},
            {"key": "sanrenpuku", "stake": 100, "ret": 0},
            {"key": "sanrentan", "stake": 100, "ret": 0},
        ]},
        {"date": "2026-09-14", "stake": 300, "ret": 5000, "profit": 4700, "bets": [
            {"key": "tansho", "stake": 100, "ret": 0},
            {"key": "sanrenpuku", "stake": 100, "ret": 0},
            {"key": "sanrentan", "stake": 100, "ret": 5000},
        ]},
    ]}
    h = roi_headline(ledger)
    types = {t["key"]: t for t in h["by_type"]}
    assert [t["key"] for t in h["by_type"]] == ["tansho", "sanrenpuku", "sanrentan"]
    assert types["tansho"]["profit"] == 480 - 200
    assert types["sanrentan"]["profit"] == 5000 - 200
    assert types["sanrenpuku"]["profit"] == -200
    assert types["sanrentan"]["hit_races"] == 1
    assert len(types["tansho"]["series"]) == 3


def _fake_race(seed=0):
    """線形に分離可能なダミーレース: 特徴量1が高い馬が勝ちやすい。"""
    rng = np.random.default_rng(seed)
    H = rng.integers(8, 16)
    X = rng.normal(0, 1, (H, D))
    winner = int(np.argmax(X[:, 0] + rng.normal(0, 0.3, H)))
    return X, winner


def test_rankmodel_learns_signal():
    model = RankModel()
    races = [_fake_race(i) for i in range(200)]
    losses = model.fit(races, epochs=30)
    assert losses[-1] < losses[0]
    # 特徴量0 の重みが最大級に大きくなる
    assert model.theta[0] == max(model.theta)
    # 予測が winner を最上位にする率
    correct = 0
    for X, w in races[:50]:
        if int(np.argmax(model.win_probs(X))) == w:
            correct += 1
    assert correct >= 30


def test_rankmodel_partial_fit_and_roundtrip(tmp_path):
    m = RankModel()
    X, w = _fake_race(1)
    for _ in range(5):
        m.partial_fit(X, w, weight=2.0)
    assert m.n_updates == 5
    p = tmp_path / "model.json"
    m.save(p)
    m2 = RankModel.load(p)
    assert np.allclose(m.theta, m2.theta)
    assert m2.n_updates == 5


def test_settle_tansho_and_trio():
    payouts = {
        "win": [{"combo": [7], "yen": 480, "pop": 3}],
        "trio": [{"combo": [4, 7, 10], "yen": 2610, "pop": 7}],
    }
    top3 = [7, 4, 10]
    tan = _settle_bet({"key": "tansho", "type": "単勝", "axis": [7]}, top3, payouts)
    assert tan["hit"] and tan["ret"] == 480 and tan["stake"] == 100

    form = _settle_bet(
        {"key": "sanrenpuku_formation", "type": "3連複F", "combos": [[4, 7, 10], [4, 7, 12]]},
        top3, payouts,
    )
    assert form["hit"] and form["ret"] == 2610 and form["stake"] == 200

    nag = _settle_bet(
        {"key": "sanrenpuku_nagashi", "type": "3連複流し", "axis": [7], "partners": [4, 10, 12, 5, 6]},
        top3, payouts,
    )
    assert nag["hit"] and nag["ret"] == 2610

    miss = _settle_bet({"key": "tansho", "type": "単勝", "axis": [1]}, top3, payouts)
    assert not miss["hit"] and miss["ret"] == 0


def test_settle_sanrentan_and_sanrenpuku_combos():
    payouts = {
        "trifecta": [{"combo": [7, 4, 10], "yen": 18230, "pop": 42}],
        "trio": [{"combo": [4, 7, 10], "yen": 2610, "pop": 7}],
    }
    top3 = [7, 4, 10]  # 1着7 / 2着4 / 3着10

    tri = _settle_bet({"key": "sanrentan", "type": "3連単",
                       "combos": [[7, 4, 10], [7, 4, 5], [7, 10, 4]]}, top3, payouts)
    assert tri["hit"] and tri["ret"] == 18230 and tri["stake"] == 300

    tri_miss = _settle_bet({"key": "sanrentan", "type": "3連単",
                            "combos": [[4, 7, 10], [10, 7, 4]]}, top3, payouts)
    assert not tri_miss["hit"] and tri_miss["stake"] == 200

    puk = _settle_bet({"key": "sanrenpuku", "type": "3連複",
                       "combos": [[4, 7, 10], [4, 7, 12]]}, top3, payouts)
    assert puk["hit"] and puk["ret"] == 2610 and puk["stake"] == 200


def _race_with_odds(pairs):
    """pairs: [(horse_number, result_odds), ...]"""
    r = Race(race_id="202601010101", kaisai_date="2026-09-13")
    r.entries = [Entry(horse_name=f"馬{n}", horse_number=n, result_odds=o) for n, o in pairs]
    return r


def test_axis_final_ev_positive_and_negative():
    rec = {"recommended": [{"key": "tansho", "axis": [7], "hit_prob": 0.4}]}
    race = _race_with_odds([(7, 3.0), (4, 5.0)])
    odds, ev = _axis_final_ev(rec, race)
    assert odds == 3.0
    assert abs(ev - (0.4 * 3.0 - 1.0)) < 1e-9  # = +0.2 (プラス)

    rec_low = {"recommended": [{"key": "tansho", "axis": [7], "hit_prob": 0.1}]}
    _, ev_low = _axis_final_ev(rec_low, race)
    assert ev_low < 0


def test_axis_final_ev_missing_odds_returns_none():
    rec = {"recommended": [{"key": "tansho", "axis": [9], "hit_prob": 0.4}]}
    race = _race_with_odds([(7, 3.0)])  # 軸馬(9)がいない
    odds, ev = _axis_final_ev(rec, race)
    assert odds is None and ev is None


def _write_rec(d, race_id, *, attention, kaisai_date="2020-01-01"):
    (d / f"{race_id}.json").write_text(json.dumps({
        "race_id": race_id, "kaisai_date": kaisai_date, "venue": "中山", "race_number": 11,
        "race_name": "テストS", "attention": attention,
        "recommended": [
            {"key": "tansho", "type": "単勝", "tracked": True, "axis": [7], "nums": [7],
             "unit": 1, "hit_prob": 0.4},
            {"key": "sanrenpuku", "type": "3連複", "tracked": True, "method": "流し",
             "combos": [[4, 7, 10]], "unit": 1, "hit_prob": 0.1},
            {"key": "sanrentan", "type": "3連単", "tracked": True, "method": "流し",
             "combos": [[7, 4, 10]], "unit": 1, "hit_prob": 0.05},
        ],
    }, ensure_ascii=False), encoding="utf-8")


def test_settle_only_tracks_attention_races_with_positive_final_odds_ev(monkeypatch, tmp_path):
    rec_dir = tmp_path / "data" / "recommended"
    rec_dir.mkdir(parents=True)
    # A: 注目レース・軸馬の確定オッズで期待値プラス → 成績に反映
    _write_rec(rec_dir, "202601010301", attention=True)
    # B: 注目レース外 → 成績には反映しないが、モデル学習対象にはなる
    _write_rec(rec_dir, "202601010302", attention=False)
    # C: 注目レースだが軸馬の確定オッズで期待値マイナス → 成績には反映しない
    _write_rec(rec_dir, "202601010303", attention=True)

    payouts = {
        "win": [{"combo": [7], "yen": 300, "pop": 3}],
        "trio": [{"combo": [4, 7, 10], "yen": 2000, "pop": 5}],
        "trifecta": [{"combo": [7, 4, 10], "yen": 8000, "pop": 20}],
    }

    def fake_result(race_id, *, use_cache=True):
        race = _race_with_odds([(7, 3.0), (4, 5.0), (10, 8.0)])
        race.race_id = race_id
        for e in race.entries:
            e.result_finish_pos = {7: 1, 4: 2, 10: 3}[e.horse_number]
        if race_id == "202601010303":
            # 期待値がマイナスになる確定オッズ (hit_prob=0.4 に対し odds=1.5 → ev=-0.4)
            race.entries[0].result_odds = 1.5
        return race

    def fake_payouts(race_id, *, use_cache=True):
        return payouts

    monkeypatch.setattr("builder.scraping.netkeiba.fetch_race_result", fake_result)
    monkeypatch.setattr("builder.scraping.netkeiba.fetch_payouts", fake_payouts)
    monkeypatch.setattr("builder.model.update.update_from_races", lambda ids: {"updated": len(ids)})

    result = settle(tmp_path)

    assert result["settled"] == 1
    assert result["model_updates"] == 3          # 3レースとも学習対象
    assert result["excluded_not_attention"] == 1
    assert result["excluded_negative_ev"] == 1

    ledger = json.loads((tmp_path / "data" / "ledger.json").read_text(encoding="utf-8"))
    assert [e["race_id"] for e in ledger["entries"]] == ["202601010301"]
    reasons = {x["race_id"]: x["reason"] for x in ledger["excluded"]}
    assert reasons["202601010302"] == "not_attention"
    assert reasons["202601010303"] == "negative_ev"

    # 2回目の実行では同じレースを再処理しない (settled_ids / processed_ids で除外)
    calls = []
    monkeypatch.setattr("builder.scraping.netkeiba.fetch_race_result",
                         lambda race_id, **kw: calls.append(race_id) or fake_result(race_id))
    result2 = settle(tmp_path)
    assert result2["candidates"] == 0
    assert calls == []
