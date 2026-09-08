"""モンテカルロ・レースシミュレーション。

各馬の推定パラメータから N 回レースを試行し、勝率・複勝率・適正オッズ・各買い目の
推定的中率、代表的なレース展開 (アニメーション用)、および買い目チェッカー用の
着順サンプルを算出する。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from itertools import combinations

import numpy as np

from builder.scraping.models import Race
from builder.sim.horse_model import HorseModel, build_horse_model

log = logging.getLogger("sim")

_PACE_K = 7.5
_PODIUM_SAMPLES = 6000

try:
    from builder.model.features import race_matrix, standardize
    from builder.model.model import RankModel

    _MODEL = RankModel.load()
except Exception:  # noqa: BLE001
    _MODEL = None
    race_matrix = standardize = None  # type: ignore


def _finish_positions(perf: np.ndarray) -> np.ndarray:
    n, h = perf.shape
    order = np.argsort(-perf, axis=1, kind="stable")
    pos = np.empty((n, h), dtype=np.int16)
    rows = np.arange(n)[:, None]
    pos[rows, order] = np.arange(1, h + 1)[None, :]
    return pos


def _mu_from_models(models: list[HorseModel]) -> np.ndarray:
    heur = np.array([m.rating for m in models], dtype=float)
    if _MODEL is None or race_matrix is None or len(models) < 3:
        return heur
    try:
        Xz = standardize(race_matrix(models))
        s = _MODEL.strength(Xz)
        s_z = (s - s.mean()) / (s.std() + 1e-9)
        h_z = (heur - heur.mean()) / (heur.std() + 1e-9)
        t = _MODEL.trust
        combined = (0.35 + 0.45 * t) * s_z + (0.65 - 0.45 * t) * h_z
        return 50.0 + combined * _MODEL.spread
    except Exception as exc:  # noqa: BLE001
        log.warning("model strength failed: %s", exc)
        return heur


def simulate(race: Race, n_sims: int = 10000, seed: int = 12345,
             workouts: dict | None = None) -> dict:
    rng = np.random.default_rng(seed + int(race.race_id[-6:] or 0))
    models = [build_horse_model(e, race, workouts=workouts)
              for e in race.entries if not e.scratched]
    models = [m for m in models if m.num]
    H = len(models)
    if H < 2:
        return {"race_id": race.race_id, "n_sims": 0, "horses": [], "recommended": [],
                "animation": None, "confidence": 0.0, "podium": [], "podium_n": 0}

    mu = _mu_from_models(models)
    sig = np.array([m.sigma for m in models])
    early = np.array([m.early_ratio for m in models])
    nums = np.array([m.num for m in models])

    n_front = int(np.sum(early < 0.36))
    pace_press = float(np.clip((n_front - 1.2) / max(H * 0.32, 1.0), -0.6, 1.8))
    pace_sim = rng.normal(pace_press, 0.5, n_sims)

    pace_effect = pace_sim[:, None] * (early[None, :] - 0.5) * _PACE_K
    form_noise = rng.normal(0.0, sig[None, :], (n_sims, H))
    trouble = rng.normal(0.0, 1.8 + 3.2 * early[None, :], (n_sims, H))
    perf = mu[None, :] + pace_effect + form_noise + trouble
    pos = _finish_positions(perf)

    win = (pos == 1).mean(axis=0)
    top2 = (pos <= 2).mean(axis=0)
    top3 = (pos <= 3).mean(axis=0)
    avg_finish = pos.mean(axis=0)
    dist = np.stack([(pos[:, i] == k).mean() for i in range(H) for k in range(1, H + 1)]).reshape(H, H)

    order_by_win = list(np.argsort(-win))
    ws = win[order_by_win]
    # 「軸がはっきりしているか」の指標 (0..1): 1番手の勝率 と 1↔2番手の勝率差 の合成。
    # 確率そのものではなく "抜けの大きさ" なので、表示は数値ではなく段階ラベルにする。
    confidence = float(np.clip(0.58 * ws[0] + 0.42 * (ws[0] - ws[1]), 0, 1))
    conf_tier = "高" if confidence >= 0.30 else ("中" if confidence >= 0.16 else "低")

    def fair(p: float) -> float:
        return round(1.0 / p, 1) if p > 1e-4 else 999.9

    horses = []
    for i, m in enumerate(models):
        horses.append({
            "num": m.num, "name": m.name, "horse_id": m.horse_id, "jockey": m.jockey,
            "sex_age": m.sex_age, "weight_carried": m.weight_carried, "draw": m.draw,
            "style": m.style, "style_mix": m.style_mix, "early_ratio": round(float(early[i]), 3),
            "win_prob": round(float(win[i]), 4),
            "top2_prob": round(float(top2[i]), 4),
            "place_prob": round(float(top3[i]), 4),
            "fair_win_odds": fair(float(win[i])),
            "fair_place_odds": fair(float(top3[i])),
            "avg_finish": round(float(avg_finish[i]), 2),
            "finish_dist": [round(float(x), 4) for x in dist[i]],
            "rank": 0,
            "starts": m.starts, "wins": m.wins, "top3": m.top3,
            "recent_finish": m.recent_finish,
            "best_last3f": m.best_last3f, "avg_last3f": m.avg_last3f,
            "workout": round(m.workout, 2) if m.workout else 0,
            "notes": m.notes,
            "netkeiba_url": f"https://db.netkeiba.com/horse/{m.horse_id}/" if m.horse_id else None,
        })
    horses.sort(key=lambda x: x["win_prob"], reverse=True)
    for r, hh in enumerate(horses, 1):
        hh["rank"] = r

    col = {int(nums[i]): i for i in range(H)}
    recommended = _recommended(pos, horses, col, nums, confidence)
    animation = build_animation(race, models, horses, pace_press, rng)

    # 買い目チェッカー用: 各試行の上位3頭 (馬番)
    p1 = nums[(pos == 1).argmax(axis=1)]
    p2 = nums[(pos == 2).argmax(axis=1)]
    p3 = nums[(pos == 3).argmax(axis=1)]
    n_pod = min(n_sims, _PODIUM_SAMPLES)
    podium = np.stack([p1, p2, p3], axis=1)[:n_pod].reshape(-1).astype(int).tolist()

    pace_label = "H" if pace_press > 0.55 else ("S" if pace_press < -0.1 else "M")
    return {
        "race_id": race.race_id,
        "n_sims": n_sims,
        "model": ("学習モデル" if _MODEL is not None else "ベースライン"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "confidence": round(confidence, 3),
        "confidence_tier": conf_tier,
        "pace": pace_label,
        "pace_press": round(pace_press, 2),
        "horses": horses,
        "recommended": recommended,
        "podium": podium,
        "podium_n": n_pod,
        "animation": animation,
    }


# --------------------------------------------------------------------- 推奨買い目
def _trio_combos(method: str, r: list[int]) -> list[tuple[int, int, int]]:
    """3連複の買い目。method="流し": r[0] 軸 + r[1:6] から2頭 / "フォーメーション": 上位5頭の
    3頭組で r[0] か r[1] を含むもの。"""
    if method == "流し":
        axis, partners = r[0], r[1:6]
        return sorted({tuple(sorted((axis, a, b)))
                       for i, a in enumerate(partners) for b in partners[i + 1:]})
    top5 = r[:5]
    return sorted({tuple(sorted(c)) for c in combinations(top5, 3)
                   if r[0] in c or r[1] in c})


def _trifecta_combos(method: str, r: list[int]) -> list[tuple[int, int, int]]:
    """3連単の買い目 (着順あり)。method="流し": 1着 r[0] 固定・2,3着を r[1:5] から /
    "フォーメーション": 1着[r0,r1] 2着[r0,r1,r2] 3着[r0,r1,r2,r3]。"""
    if method == "流し":
        first, rest = r[0], r[1:5]
        return [(first, a, b) for a in rest for b in rest if a != b]
    firsts, secs, thirds = [r[0], r[1]], [r[0], r[1], r[2]], [r[0], r[1], r[2], r[3]]
    out = {(a, b, c) for a in firsts for b in secs for c in thirds if len({a, b, c}) == 3}
    return sorted(out)


def _recommended(pos: np.ndarray, horses: list[dict], col: dict[int, int],
                 nums: np.ndarray, confidence: float) -> list[dict]:
    ranked = [h["num"] for h in horses]
    out: list[dict] = []

    def c(n):
        return col[n]

    def prob(mask) -> float:
        return float(mask.mean())

    def add(bet: dict):
        p = bet["hit_prob"]
        bet["fair_odds"] = round(1.0 / p, 1) if p > 1e-4 else 999.9
        out.append(bet)

    t = ranked[:6] + ranked[:1] * max(0, 6 - len(ranked))
    r1, r2, r3, r4, r5, r6 = t[0], t[1], t[2], t[3], t[4], t[5]

    add({"key": "tansho", "type": "単勝", "tracked": True,
         "selection": f"{r1}", "nums": [r1], "unit": 1,
         "hit_prob": round(prob(pos[:, c(r1)] == 1), 4),
         "note": "軸馬の単勝。1点100円"})

    add({"key": "fukusho", "type": "複勝", "tracked": False,
         "selection": f"{r1}", "nums": [r1], "unit": 1,
         "hit_prob": round(prob(pos[:, c(r1)] <= 3), 4),
         "note": "軸馬が3着以内"})

    add({"key": "umaren", "type": "馬連", "tracked": False,
         "selection": f"{r1} - {r2}", "nums": [r1, r2], "unit": 1,
         "hit_prob": round(prob((pos[:, c(r1)] <= 2) & (pos[:, c(r2)] <= 2)), 4),
         "note": "上位2頭で1・2着 (順不同)"})

    for o in (r2, r3):
        add({"key": f"wide_{o}", "type": "ワイド", "tracked": False,
             "selection": f"{r1} - {o}", "nums": [r1, o], "unit": 1,
             "hit_prob": round(prob((pos[:, c(r1)] <= 3) & (pos[:, c(o)] <= 3)), 4),
             "note": "2頭とも3着以内"})

    # --- 3連複 / 3連単: 軸のはっきり度で「流し」か「フォーメーション」を都度判断 ---
    r6list = [r1, r2, r3, r4, r5, r6]
    method = "流し" if confidence >= 0.24 else "フォーメーション"

    top3_ord = np.stack([nums[(pos == k).argmax(axis=1)] for k in (1, 2, 3)], axis=1)  # (n,3) 着順
    top3_set = np.sort(top3_ord, axis=1)

    trio = _trio_combos(method, r6list)
    trio_hit = _any_set_match(top3_set, np.sort(np.array(trio), axis=1))
    add({"key": "sanrenpuku", "type": "3連複", "method": method, "tracked": True,
         "selection": _combo_label("3連複", method, r6list),
         "combos": [list(x) for x in trio], "unit": len(trio),
         "hit_prob": round(prob(trio_hit), 4),
         "note": f"{method}・{len(trio)}点（計{len(trio) * 100}円）。上位陣の3頭が的中"})

    tri = _trifecta_combos(method, r6list)
    tri_arr = np.array(tri)
    tri_hit = (top3_ord[:, None, :] == tri_arr[None, :, :]).all(axis=2).any(axis=1)
    add({"key": "sanrentan", "type": "3連単", "method": method, "tracked": True,
         "selection": _combo_label("3連単", method, r6list),
         "combos": [list(x) for x in tri], "unit": len(tri),
         "hit_prob": round(prob(tri_hit), 4),
         "note": f"{method}・{len(tri)}点（計{len(tri) * 100}円）。1→2→3着を着順どおり"})
    return out


def _combo_label(kind: str, method: str, r: list[int]) -> str:
    if method == "流し":
        rest = "・".join(map(str, r[1:5]))
        return (f"{r[0]} 流し → {rest}" if kind == "3連単"
                else f"{r[0]} 軸 → {'・'.join(map(str, r[1:6]))}")
    if kind == "3連単":
        return f"[{r[0]},{r[1]}] → [{r[0]},{r[1]},{r[2]}] → [{r[0]},{r[1]},{r[2]},{r[3]}]"
    return f"上位5頭（{'・'.join(map(str, r[:5]))}）から3頭・{r[0]}か{r[1]}を含む"


def _podium_col(pos: np.ndarray, k: int) -> np.ndarray:
    return (pos == k).argmax(axis=1)


def _any_set_match(top3_cols_sorted: np.ndarray, combo_arr: np.ndarray) -> np.ndarray:
    """top3_cols_sorted は列インデックスではなく馬番前提にできないので、呼び出し側で
    馬番へ変換済みの (N,3) ソート済み配列を渡すこと。"""
    if combo_arr.size == 0:
        return np.zeros(top3_cols_sorted.shape[0], dtype=bool)
    # (N,1,3) == (1,K,3)
    eq = (top3_cols_sorted[:, None, :] == combo_arr[None, :, :]).all(axis=2)
    return eq.any(axis=1)


# --------------------------------------------------------------------- アニメーション
_HORSE_LENGTH_M = 2.4  # 1馬身 ≈ 2.4m (隊列の縦の伸びを距離に換算するため)


def build_animation(race: Race, models: list[HorseModel], horses: list[dict],
                    pace_press: float, rng: np.random.Generator, ticks: int = 34) -> dict:
    """各 tick で「その馬がレース距離のどこまで進んだか」(pos_track, 0..1) と
    「隊列内の順位」(rank_track) を返す。前後の隊列が見えるアニメーション用。"""
    H = len(models)
    finish_rank = {h["num"]: h["rank"] for h in horses}
    early = np.array([m.early_ratio for m in models])           # 0=逃げ .. 1=追込
    nums = [m.num for m in models]
    draws = np.array([float(m.draw or i + 1) for i, m in enumerate(models)])

    early_score = -(early - 0.5)                                # 高いほど前
    final_score = np.array([0.5 - (finish_rank[n] - 1) / max(H - 1, 1) for n in nums])
    phase_shift = 0.55 + (early - 0.5) * 0.9
    wobble_amp = 0.08 + 0.14 * early
    wobble_phase = rng.uniform(0, 2 * np.pi, H)
    wobble_freq = rng.uniform(1.4, 2.6, H)

    D = float(race.distance or 1600)
    ranks = np.zeros((ticks + 1, H), dtype=int)
    posf = np.zeros((ticks + 1, H))
    for tk in range(ticks + 1):
        frac = tk / ticks
        w = np.clip((frac - 0.10) / 0.90, 0, 1) ** np.clip(phase_shift / 0.55, 0.5, 2.2)
        score = (1 - w) * early_score + w * final_score
        score = score + np.sin(frac * np.pi * wobble_freq + wobble_phase) * wobble_amp * (1 - frac ** 2)
        ranks[tk] = (-score).argsort().argsort() + 1
        # 隊列の縦の伸び(m): 序盤は詰まり、道中〜終盤で開く。逃げ・追込差が大きいほど伸びる
        spread_m = min(0.45 * D, 6.0 + (0.05 * D + 26.0) * frac + 14.0 * max(0.0, pace_press))
        rel = (score.max() - score) / (np.ptp(score) + 1e-9)   # 先頭0 .. 最後方1
        behind_m = rel * spread_m
        posf[tk] = np.clip((frac * D - behind_m) / D, -0.03, 1.03)
    ranks[ticks] = np.array([finish_rank[n] for n in nums])
    # frac=1 の反復は final_score そのものなので並びは着順どおり。
    # 先頭をゴール線 (pos=1.0) に合わせ、後続はその時点の隊列の伸びぶんだけ後方に置く。
    posf[ticks] = posf[ticks] - posf[ticks].max() + 1.0

    pace_note = {
        "H": "前に行きたい馬が多く、締まったペースになりそう。差し・追込にチャンス。",
        "M": "平均的なペース。展開の紛れは小さめ。",
        "S": "逃げ・先行馬が少なく、スローペースの公算。前々で運べる馬が有利。",
    }
    pace_label = "H" if pace_press > 0.55 else ("S" if pace_press < -0.1 else "M")
    return {
        "ticks": ticks,
        "distance": race.distance,
        "surface": race.surface,
        "direction": race.direction,
        "venue": race.venue,
        "pace": pace_label,
        "pace_note": pace_note[pace_label],
        "horse_length_m": _HORSE_LENGTH_M,
        "horses": [
            {
                "num": m.num, "name": m.name, "style": m.style, "draw": int(draws[i]),
                "rank_track": [int(ranks[t, i]) for t in range(ticks + 1)],
                "pos_track": [round(float(posf[t, i]), 4) for t in range(ticks + 1)],
                "finish": finish_rank[m.num],
            }
            for i, m in enumerate(models)
        ],
    }
