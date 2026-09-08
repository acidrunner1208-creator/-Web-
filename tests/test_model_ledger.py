import numpy as np

import builder.render as render
from builder.model.features import D
from builder.model.model import RankModel
from builder.render import roi_headline
from builder.settle import _settle_bet


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
