import numpy as np

from builder.model.features import D
from builder.model.model import RankModel
from builder.settle import _settle_bet


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
