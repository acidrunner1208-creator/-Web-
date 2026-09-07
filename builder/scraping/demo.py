"""DEMO_MODE 用の合成データ (ネットワーク不要)。"""
from __future__ import annotations

import random
from datetime import date, timedelta

from builder.scraping.models import Entry, PastRun, Race, RaceListItem

_VENUES = {"05": "東京", "06": "中山", "09": "阪神"}
_SURFACES = [("芝", [1400, 1600, 1800, 2000, 2400]), ("ダ", [1200, 1400, 1600, 1800])]
_CLASSES = ["未勝利", "1勝クラス", "2勝クラス", "3勝クラス", "オープン", "G3", "G2", "G1"]
_CONDS = ["良", "良", "良", "稍重", "重"]
_WEATHER = ["晴", "晴", "曇", "小雨"]
_SIRES = ["ディープインパクト", "キズナ", "ロードカナロア", "エピファネイア", "ハーツクライ",
          "ドゥラメンテ", "モーリス", "キングカメハメハ"]
_JOCKEYS = ["ルメール", "川田", "武豊", "戸崎圭", "横山武", "松山", "岩田望", "坂井"]


def _rng(seed: str) -> random.Random:
    return random.Random(seed)


def resolve_weekend(today: date | None = None) -> list[str]:
    today = today or date.today()
    wd = today.weekday()
    sat = today - timedelta(days=wd - 5) if wd in (5, 6) else today + timedelta(days=(5 - wd) % 7)
    return [sat.strftime("%Y%m%d"), (sat + timedelta(days=1)).strftime("%Y%m%d")]


def demo_race_list(kaisai_date: str) -> list[RaceListItem]:
    r = _rng(kaisai_date)
    codes = r.sample(list(_VENUES), k=2)
    items: list[RaceListItem] = []
    for code in codes:
        for rno in range(1, 13):
            rid = f"{kaisai_date[:4]}{code}0101{rno:02d}"
            items.append(
                RaceListItem(
                    race_id=rid,
                    kaisai_date=f"{kaisai_date[:4]}-{kaisai_date[4:6]}-{kaisai_date[6:8]}",
                    venue=_VENUES[code],
                    race_number=rno,
                    race_name=f"{_VENUES[code]}{rno}R " + r.choice(_CLASSES),
                    start_time=f"{9 + rno}:{r.choice(['05', '25', '40'])}",
                )
            )
    return items


def _demo_runs(r: random.Random, n: int, surface: str, distance: int) -> list[PastRun]:
    runs = []
    base = date.today() - timedelta(days=28)
    strength = r.uniform(0.28, 0.92)
    style_bias = r.random()  # 0=逃げ 1=追込
    for i in range(n):
        d = base - timedelta(days=34 * i + r.randint(-6, 6))
        field = r.randint(8, 16)
        pos = max(1, min(field, int(r.gauss((1 - strength) * field + 1, 2.6))))
        t = distance / (16.4 + strength * 1.3 + r.uniform(-0.35, 0.35))
        early = max(1, min(field, int(field * style_bias + r.gauss(0, 1.5))))
        runs.append(
            PastRun(
                date=d.isoformat(), venue=r.choice(list(_VENUES.values())),
                weather=r.choice(_WEATHER), race_name=r.choice(_CLASSES) + " 戦",
                field_size=field, draw=r.randint(1, 8), horse_number=r.randint(1, field),
                odds=round(r.uniform(1.8, 40), 1), popularity=r.randint(1, field),
                finish_pos=pos, jockey=r.choice(_JOCKEYS),
                weight_carried=float(r.choice([54, 55, 56, 57])),
                distance=distance + r.choice([-200, 0, 0, 200]), surface=surface,
                track_condition=r.choice(_CONDS), time_sec=round(t, 1),
                margin=r.choice(["クビ", "1/2", "1", "2", "アタマ", "3/4"]),
                passing="-".join(str(min(field, early + r.randint(-1, 2))) for _ in range(4)),
                pace=f"{r.uniform(34, 38):.1f}-{r.uniform(34, 38):.1f}",
                last_3f=round(r.uniform(33.2, 37.8), 1),
                body_weight=r.randint(440, 520), body_weight_diff=r.randint(-12, 12),
            )
        )
    return runs


def demo_race_card(race_id: str) -> Race:
    r = _rng(race_id)
    surface, dists = r.choice(_SURFACES)
    distance = r.choice(dists)
    n = r.randint(9, 16)
    venue = _VENUES.get(race_id[4:6], "東京")
    rno = int(race_id[-2:])
    race = Race(
        race_id=race_id, kaisai_date=date.today().isoformat(), venue=venue, race_number=rno,
        race_name=f"{venue}{rno}R " + r.choice(_CLASSES), start_time=f"{9 + rno}:30",
        surface=surface, distance=distance, direction=r.choice(["右", "左"]),
        weather=r.choice(_WEATHER), track_condition=r.choice(_CONDS),
        race_class=r.choice(_CLASSES), field_size=n,
    )
    for i in range(1, n + 1):
        hr = _rng(f"{race_id}-{i}")
        race.entries.append(
            Entry(
                horse_id=f"D{race_id}{i:02d}", horse_name=f"デモホース{race_id[-3:]}{i:02d}",
                horse_number=i, draw=(i + 1) // 2,
                sex_age=hr.choice(["牡3", "牝3", "牡4", "牝4", "セ5"]),
                weight_carried=hr.choice([54.0, 55.0, 56.0, 57.0]), jockey=hr.choice(_JOCKEYS),
                trainer=f"調教師{i:02d}", trainer_area=hr.choice(["美浦", "栗東"]),
                body_weight=hr.randint(440, 520), body_weight_diff=hr.randint(-10, 10),
                sire=hr.choice(_SIRES), dam_sire=hr.choice(_SIRES),
                past_runs=_demo_runs(hr, hr.randint(3, 10), surface, distance),
            )
        )
    return race
