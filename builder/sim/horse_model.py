"""過去戦績から 1 頭ぶんのシミュレーション用パラメータを推定する。

(このモジュールの内部ロジックはユーザーには開示しない)
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import date

from builder.scraping.models import Entry, PastRun, Race

_SURF_REF_MPS = {"芝": 16.55, "ダ": 15.85, "障": 14.8}
_CLASS_PATTERNS = [
    (r"G1|GⅠ|ＧⅠ", 10), (r"G2|GⅡ|ＧⅡ", 9), (r"G3|GⅢ|ＧⅢ", 8),
    (r"オープン|OP|L\b|リステッド|オープン特別", 7),
    (r"3勝|３勝|1600万", 6), (r"2勝|２勝|1000万", 5), (r"1勝|１勝|500万", 4),
    (r"未勝利", 2), (r"新馬", 1),
]
STYLE_LABELS = ("逃げ", "先行", "差し", "追込")


def class_level(text: str | None) -> float:
    if not text:
        return 4.0
    for pat, lvl in _CLASS_PATTERNS:
        if re.search(pat, text):
            return float(lvl)
    return 4.0


def _pdate(s: str | None) -> date | None:
    if not s:
        return None
    for pat in (r"(\d{4})-(\d{2})-(\d{2})", r"(\d{4})/(\d{1,2})/(\d{1,2})"):
        m = re.match(pat, s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _passing_ratio(run: PastRun) -> float | None:
    if not run.passing or not run.field_size:
        return None
    nums = [int(x) for x in re.findall(r"\d+", run.passing)]
    if not nums:
        return None
    return min(1.0, (sum(nums) / len(nums)) / max(run.field_size, 2))


@dataclass
class HorseModel:
    num: int
    name: str
    horse_id: str | None
    jockey: str | None
    sex_age: str | None
    weight_carried: float | None
    draw: int | None
    scratched: bool
    entry: Entry

    rating: float = 50.0
    sigma: float = 9.0
    early_ratio: float = 0.5          # 0=逃げ 1=追込
    style: str = "先行"
    style_mix: dict = field(default_factory=dict)
    n_runs: int = 0
    best_last3f: float | None = None
    avg_last3f: float | None = None
    recent_finish: list[int] = field(default_factory=list)
    starts: int = 0
    wins: int = 0
    top3: int = 0
    workout: float = 0.0
    notes: list[str] = field(default_factory=list)
    features: dict = field(default_factory=dict)


def _run_points(run: PastRun) -> float | None:
    if not run.finish_pos or not run.field_size:
        return None
    pts = 50.0
    pts += ((run.field_size / 2 - run.finish_pos) / run.field_size) * 40.0
    if run.time_sec and run.distance and run.surface in _SURF_REF_MPS and run.time_sec > 0:
        v = run.distance / run.time_sec
        pts += max(-15.0, min(15.0, (v - _SURF_REF_MPS[run.surface]) * 55.0))
    pts += (class_level(run.race_name) - 4.0) * 2.4
    if run.last_3f:
        pts += max(-8.0, min(8.0, (36.0 - run.last_3f) * 2.0))
    cond_pen = {"稍重": 0.5, "重": 1.2, "不良": 2.0}.get(run.track_condition or "", 0.0)
    pts += cond_pen  # 道悪をこなした実績は僅かに加点
    return pts


def build_horse_model(
    entry: Entry, race: Race, *, as_of: date | None = None, workouts: dict | None = None
) -> HorseModel:
    as_of = as_of or _pdate(race.kaisai_date) or date.today()
    runs = [r for r in entry.past_runs if (_pdate(r.date) or date(1900, 1, 1)) < as_of]
    runs.sort(key=lambda r: _pdate(r.date) or date(1900, 1, 1), reverse=True)

    hm = HorseModel(
        num=entry.horse_number or 0, name=entry.horse_name, horse_id=entry.horse_id,
        jockey=entry.jockey, sex_age=entry.sex_age, weight_carried=entry.weight_carried,
        draw=entry.draw, scratched=entry.scratched, entry=entry, n_runs=len(runs),
    )
    if workouts:
        hm.workout = float(workouts.get(entry.horse_id, workouts.get(entry.horse_number, 0.0)) or 0.0)
    finished = [r for r in runs if r.finish_pos]
    hm.starts = len(finished)
    hm.wins = sum(1 for r in finished if r.finish_pos == 1)
    hm.top3 = sum(1 for r in finished if r.finish_pos <= 3)
    hm.recent_finish = [r.finish_pos for r in runs[:6] if r.finish_pos]

    l3 = [r.last_3f for r in runs if r.last_3f]
    if l3:
        hm.best_last3f = min(l3)
        hm.avg_last3f = round(statistics.fmean(l3), 1)

    # --- rating / sigma ---
    pts, wts = [], []
    for i, r in enumerate(runs[:8]):
        p = _run_points(r)
        if p is None:
            continue
        w = (0.86 ** i)
        pts.append(p)
        wts.append(w)
    if pts:
        tot = sum(wts)
        hm.rating = sum(p * w for p, w in zip(pts, wts)) / tot
        if len(pts) >= 2:
            mean = hm.rating
            var = sum(w * (p - mean) ** 2 for p, w in zip(pts, wts)) / tot
            hm.sigma = math.sqrt(var)
    hm.sigma = max(6.0, hm.sigma)
    if hm.n_runs < 2:
        hm.sigma += 6.0
        hm.rating -= 3.0
        hm.notes.append("キャリア浅く不確実")
    elif hm.n_runs < 4:
        hm.sigma += 3.0

    # --- 脚質 ---
    ratios = [(_passing_ratio(r), 0.86 ** i) for i, r in enumerate(runs[:6])]
    ratios = [(v, w) for v, w in ratios if v is not None]
    if ratios:
        hm.early_ratio = sum(v * w for v, w in ratios) / sum(w for _, w in ratios)
    else:
        hm.early_ratio = 0.5
    bounds = (0.22, 0.44, 0.68)
    hm.style = STYLE_LABELS[sum(hm.early_ratio >= b for b in bounds)]
    # 脚質の振れ (mix)
    cats = [STYLE_LABELS[sum((v >= b) for b in bounds)] for v, _ in ratios]
    hm.style_mix = {s: round(cats.count(s) / len(cats), 2) for s in STYLE_LABELS} if cats else {}

    # --- 当日条件の補正 (rating に加算) ---
    adj, notes = 0.0, hm.notes
    f_surface = f_dist = f_cond = 0.0

    same_surf = [r for r in runs if r.surface == race.surface and r.finish_pos]
    if not any(r.surface == race.surface for r in runs) and runs:
        adj -= 6.0
        f_surface = -1.0
        notes.append(f"{race.surface}コース未経験")
    elif same_surf:
        sr = sum(1 for r in same_surf if r.finish_pos <= 3) / len(same_surf)
        f_surface = sr - 0.33
        adj += f_surface * 8.0

    if race.distance:
        near = [r for r in runs if r.distance and abs(r.distance - race.distance) <= 200 and r.finish_pos]
        if near:
            f_dist = sum(1 for r in near if r.finish_pos <= 3) / len(near) - 0.33
            adj += f_dist * 6.0
        elif runs and all(r.distance and abs((r.distance or 0) - race.distance) > 400 for r in runs):
            adj -= 3.0
            f_dist = -0.5
            notes.append("距離条件が大きく異なる")

    if race.track_condition and race.track_condition != "良":
        cond_runs = [r for r in runs if r.track_condition and r.track_condition != "良" and r.finish_pos]
        if cond_runs:
            f_cond = sum(1 for r in cond_runs if r.finish_pos <= 3) / len(cond_runs) - 0.33
            adj += f_cond * 6.0
            if f_cond >= 0.17:
                notes.append("道悪巧者")

    f_weight = -(entry.weight_carried - 55.0) if entry.weight_carried else 0.0
    adj += f_weight * 0.7
    if entry.body_weight_diff is not None and abs(entry.body_weight_diff) >= 18:
        adj -= 2.0
        notes.append(f"馬体重{entry.body_weight_diff:+d}kg")

    f_rotation = 0.0
    if runs:
        gap = (as_of - (_pdate(runs[0].date) or as_of)).days
        if gap > 150:
            adj -= 3.5
            f_rotation = -1.0
            notes.append(f"約{gap // 30}か月の休養明け")
        elif 21 <= gap <= 70:
            adj += 1.0
            f_rotation = 0.5

    f_draw = 0.0
    if race.distance and entry.draw and race.field_size:
        outside = entry.draw / max(race.field_size / 2, 1)
        if race.distance <= 1400:
            f_draw = (1.0 - min(outside, 1.5))
            adj += f_draw * 1.2
        elif race.distance >= 2200:
            f_draw = -(min(outside, 1.5) - 1.0)
            adj += f_draw * 1.0

    adj += hm.workout * 2.5
    hm.rating += adj

    # --- 学習モデル用の特徴量 (レース内で後段が標準化する) ---
    hm.features = {
        "rating": hm.rating,
        "form_recent": _form_recent(runs),
        "win_rate": hm.wins / hm.starts if hm.starts else 0.0,
        "top3_rate": hm.top3 / hm.starts if hm.starts else 0.0,
        "best_last3f": -(hm.best_last3f or 36.0),
        "speed_best": _speed_best(runs),
        "surface_fit": f_surface,
        "dist_fit": f_dist,
        "cond_fit": f_cond,
        "class_delta": _class_delta(runs, race),
        "rotation": f_rotation,
        "weight": f_weight,
        "draw": f_draw,
        "early_ratio": hm.early_ratio - 0.5,
        "n_runs": min(hm.n_runs, 15) / 15.0,
        "workout": hm.workout,
    }
    return hm


def _form_recent(runs: list[PastRun]) -> float:
    w = [0.35, 0.25, 0.2, 0.12, 0.08]
    num = den = 0.0
    for wi, r in zip(w, runs[:5]):
        if r.finish_pos and r.field_size:
            num += wi * max(0.0, (r.field_size - r.finish_pos + 1) / r.field_size)
            den += wi
    return num / den if den else 0.4


def _speed_best(runs: list[PastRun]) -> float:
    vs = []
    for r in runs:
        if r.time_sec and r.distance and r.surface in _SURF_REF_MPS and r.time_sec > 0:
            vs.append(r.distance / r.time_sec - _SURF_REF_MPS[r.surface])
    return max(vs) if vs else 0.0


def _class_delta(runs: list[PastRun], race: Race) -> float:
    today = class_level(race.race_class or race.race_name)
    past = [class_level(r.race_name) for r in runs[:5]]
    return (sum(past) / len(past) - today) if past else 0.0
