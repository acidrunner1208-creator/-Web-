"""netkeiba (公開ページ) のパーサ。

対象サイトの HTML 構造は予告なく変わります。壊れたら CSS セレクタ / 列名マップを
更新してください。tests/ に固定 HTML でのテストがあります。

利用にあたっては netkeiba の利用規約・robots.txt を必ず確認し、
個人的・非商用の範囲で、サーバーに負荷をかけないよう運用してください。
リアルタイムのオッズ取得は行いません (サーバー負荷軽減のため)。
"""
from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from builder.scraping.client import get_client
from builder.scraping.models import Entry, PastRun, Race, RaceListItem

log = logging.getLogger("netkeiba")

RACE_LIST_URL = "https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date}"
SHUTUBA_URL = "https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
HORSE_URL = "https://db.netkeiba.com/horse/result/{horse_id}/"
RESULT_URL = "https://db.netkeiba.com/race/{race_id}/"

TTL_LIST = 6 * 3600
TTL_SHUTUBA = 6 * 3600
TTL_HORSE = 3 * 24 * 3600
TTL_RESULT = 365 * 24 * 3600

VENUE_BY_CODE = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}


# ---------------------------------------------------------------- helpers
def _num(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(m.group()) if m else None


def _int(text: str | None) -> int | None:
    v = _num(text)
    return int(v) if v is not None else None


def parse_time_to_sec(text: str | None) -> float | None:
    if not text:
        return None
    m = re.match(r"(?:(\d+):)?(\d+(?:\.\d+)?)$", text.strip())
    if not m:
        return None
    return (int(m.group(1)) if m.group(1) else 0) * 60 + float(m.group(2))


def _surface_distance(text: str | None) -> tuple[str | None, int | None]:
    if not text:
        return None, None
    surf = next((s for s in ("芝", "ダ", "障") if s in text), None)
    return surf, _int(re.sub(r"[^\d]", " ", text))


def venue_from_race_id(race_id: str) -> str | None:
    return VENUE_BY_CODE.get(race_id[4:6]) if len(race_id) >= 6 else None


def _iso_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


class _Empty:
    def get_text(self, *a, **k):
        return None


# ---------------------------------------------------------------- race list
def fetch_race_list(kaisai_date: str) -> list[RaceListItem]:
    html = get_client().get_text(RACE_LIST_URL.format(date=kaisai_date), TTL_LIST, encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    items: dict[str, RaceListItem] = {}
    for a in soup.select("a[href*='race_id=']"):
        m = re.search(r"race_id=(\d{12})", a.get("href", ""))
        if not m:
            continue
        rid = m.group(1)
        rno = _int(rid[-2:])
        t_el = a.select_one(".RaceList_Itemtime")
        start = None
        if t_el:
            mt = re.search(r"\d{1,2}:\d{2}", t_el.get_text())
            start = mt.group() if mt else None
        name_el = a.select_one(".RaceList_ItemTitle, .ItemTitle")
        race_name = name_el.get_text(strip=True) if name_el else (a.get_text(" ", strip=True) or None)
        items.setdefault(
            rid,
            RaceListItem(
                race_id=rid,
                kaisai_date=_iso_date(kaisai_date),
                venue=venue_from_race_id(rid),
                race_number=rno,
                race_name=race_name,
                start_time=start,
            ),
        )
    out = sorted(items.values(), key=lambda x: x.race_id)
    log.info("race list %s -> %d races", kaisai_date, len(out))
    return out


# ---------------------------------------------------------------- race card
def fetch_race_card(race_id: str, *, with_history: bool = True, history_limit: int = 12) -> Race:
    url = SHUTUBA_URL.format(race_id=race_id)
    html = get_client().get_text(url, TTL_SHUTUBA, encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    race = Race(
        race_id=race_id,
        kaisai_date="",
        venue=venue_from_race_id(race_id),
        race_number=_int(race_id[-2:]),
        source_url=url,
    )
    name_el = soup.select_one(".RaceName")
    if name_el:
        race.race_name = name_el.get_text(strip=True)

    head = soup.select_one(".RaceData01")
    if head:
        t = head.get_text(" ", strip=True)
        mt = re.search(r"(\d{1,2}:\d{2})", t)
        race.start_time = mt.group(1) if mt else None
        msd = re.search(r"(芝|ダ|障)\s*(\d{3,4})m", t)
        if msd:
            race.surface, race.distance = msd.group(1), int(msd.group(2))
        md = re.search(r"\((左|右|直線?)", t)
        race.direction = md.group(1) if md else None
        mw = re.search(r"天候\s*[:：]\s*(\S+?)(?:\s|/|$)", t)
        race.weather = mw.group(1) if mw else None
        mb = re.search(r"馬場\s*[:：]\s*(\S+?)(?:\s|/|$)", t)
        race.track_condition = mb.group(1) if mb else None

    head2 = soup.select_one(".RaceData02")
    if head2:
        spans = [x.get_text(strip=True) for x in head2.select("span")]
        for token in spans:
            if re.search(r"(G[123]|重賞|オープン|OP|リステッド|L|\d勝クラス|未勝利|新馬|１勝|２勝|３勝)", token):
                race.race_class = token
        for token in spans:
            if "頭" in token:
                race.field_size = _int(token)

    mdate = re.search(r"kaisai_date=(\d{8})", html)
    if mdate:
        race.kaisai_date = _iso_date(mdate.group(1))
    else:
        md2 = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", html)
        if md2:
            y, mo, d = md2.groups()
            race.kaisai_date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

    rows = soup.select("table.Shutuba_Table tr.HorseList, table.ShutubaTable tr.HorseList")
    for tr in rows:
        entry = _parse_shutuba_row(tr)
        if entry:
            race.entries.append(entry)

    if race.entries and all(e.horse_number is None for e in race.entries):
        for i, e in enumerate(race.entries, 1):
            e.horse_number = i

    if with_history:
        for e in race.entries:
            if e.horse_id and not e.scratched:
                try:
                    e.past_runs = fetch_horse_history(e.horse_id, limit=history_limit)
                except Exception as exc:  # noqa: BLE001
                    log.warning("history failed for %s: %s", e.horse_id, exc)

    race.field_size = race.field_size or len([e for e in race.entries if not e.scratched])
    return race


def _parse_shutuba_row(tr) -> Entry | None:
    a_horse = tr.select_one("a[href*='/horse/']")
    if not a_horse:
        return None
    m = re.search(r"/horse/(\w+)", a_horse.get("href", ""))

    def cls(name_):
        el = tr.select_one(f"td.{name_}")
        return el.get_text(" ", strip=True) if el else None

    umaban_el = tr.select_one("td[class*='Umaban']")
    umaban = _int(umaban_el.get_text()) if umaban_el else _int(cls("Umaban"))
    waku = _int((tr.select_one("td[class*='Waku'] span") or _Empty()).get_text())

    jw_el = tr.select_one(".JockeyWeight")
    weight_carried = _num(jw_el.get_text()) if jw_el else None

    a_jockey = tr.select_one("a[href*='/jockey/']")
    jm = re.search(r"/jockey/(?:result/recent/)?(\w+)", a_jockey.get("href", "")) if a_jockey else None
    a_trainer = tr.select_one("a[href*='/trainer/']")
    tr_area_el = tr.select_one("td.Trainer span")

    weight_txt = cls("Weight")
    body_weight = _int(weight_txt.split("(")[0]) if weight_txt else None
    bw_diff = _int(weight_txt.split("(")[1]) if weight_txt and "(" in weight_txt else None

    scratched = bool(tr.select_one(".Cancel, .Cancel_Txt")) or (
        "取消" in tr.get_text() or "除外" in tr.get_text()
    )
    return Entry(
        horse_id=m.group(1) if m else None,
        horse_name=a_horse.get_text(strip=True),
        horse_number=umaban,
        draw=waku,
        sex_age=cls("Barei"),
        weight_carried=weight_carried,
        jockey=a_jockey.get_text(strip=True) if a_jockey else None,
        jockey_id=jm.group(1) if jm else None,
        trainer=a_trainer.get_text(strip=True) if a_trainer else None,
        trainer_area=tr_area_el.get_text(strip=True) if tr_area_el else None,
        body_weight=body_weight,
        body_weight_diff=bw_diff,
        scratched=scratched,
    )


# ---------------------------------------------------------------- horse history
def fetch_horse_history(horse_id: str, limit: int = 12, before: date | None = None) -> list[PastRun]:
    html = get_client().get_text(HORSE_URL.format(horse_id=horse_id), TTL_HORSE)
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.db_h_race_results, table.db_h_race_results_table")
    if not table:
        return []

    header_cells = [th.get_text(strip=True) for th in table.select("tr")[0].select("th, td")]
    idx = {name: i for i, name in enumerate(header_cells)}

    def col(cells, *names):
        for n in names:
            for key, i in idx.items():
                if n in key and i < len(cells):
                    return cells[i].get_text(" ", strip=True)
        return None

    runs: list[PastRun] = []
    for tr in table.select("tr")[1:]:
        cells = tr.select("td")
        if len(cells) < 5:
            continue
        date_txt = col(cells, "日付")
        run_date = None
        if date_txt:
            dm = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})", date_txt)
            if dm:
                run_date = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        if before and run_date and run_date >= before:
            continue

        surf, dist = _surface_distance(col(cells, "距離"))
        bw_txt = col(cells, "馬体重")
        runs.append(
            PastRun(
                date=run_date.isoformat() if run_date else date_txt,
                venue=col(cells, "開催"),
                weather=col(cells, "天気"),
                race_name=col(cells, "レース名", "レース"),
                field_size=_int(col(cells, "頭数")),
                draw=_int(col(cells, "枠番", "枠")),
                horse_number=_int(col(cells, "馬番")),
                odds=_num(col(cells, "オッズ")),
                popularity=_int(col(cells, "人気")),
                finish_pos=_int(col(cells, "着順")),
                jockey=col(cells, "騎手"),
                weight_carried=_num(col(cells, "斤量")),
                distance=dist,
                surface=surf,
                track_condition=col(cells, "馬場"),
                time_sec=parse_time_to_sec(col(cells, "タイム")),
                margin=col(cells, "着差"),
                passing=col(cells, "通過"),
                pace=col(cells, "ペース"),
                last_3f=_num(col(cells, "上り", "上がり")),
                body_weight=_int(bw_txt.split("(")[0]) if bw_txt else None,
                body_weight_diff=_int(bw_txt.split("(")[1]) if bw_txt and "(" in bw_txt else None,
                prize=_num(col(cells, "賞金")),
            )
        )
        if len(runs) >= limit:
            break
    return runs


# ---------------------------------------------------------------- results (過去レース)
def fetch_race_result(race_id: str) -> Race:
    html = get_client().get_text(RESULT_URL.format(race_id=race_id), TTL_RESULT)
    soup = BeautifulSoup(html, "lxml")

    race = Race(
        race_id=race_id,
        kaisai_date="",
        venue=venue_from_race_id(race_id),
        race_number=_int(race_id[-2:]),
        source_url=RESULT_URL.format(race_id=race_id),
    )
    h1 = soup.select_one("h1, .RaceName")
    if h1:
        race.race_name = h1.get_text(strip=True)
    small = soup.select_one("p.smalltxt, .smalltxt")
    if small:
        dm = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", small.get_text())
        if dm:
            race.kaisai_date = f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"

    header_el = soup.select_one("diary_snap_cut, .racedata, .race_head, .RaceData01, .mainrace_data")
    header_txt = header_el.get_text(" ", strip=True) if header_el else ""
    msd = re.search(r"(芝|ダート|障)\D*?(\d{3,4})m", header_txt)
    if msd:
        race.surface = {"ダート": "ダ"}.get(msd.group(1), msd.group(1))
        race.distance = int(msd.group(2))
    mb = re.search(r"(良|稍重|重|不良)", header_txt)
    race.track_condition = mb.group(1) if mb else None

    table = soup.select_one("table.race_table_01, table.RaceTable01, table[summary*='レース']")
    if not table:
        return race
    rows = table.select("tr")
    headers = [th.get_text(strip=True) for th in rows[0].select("th, td")]
    hidx = {n: i for i, n in enumerate(headers)}

    def g(cells, *names):
        for name in names:
            for key, i in hidx.items():
                if name in key and i < len(cells):
                    return cells[i].get_text(" ", strip=True)
        return None

    for tr in rows[1:]:
        cells = tr.select("td")
        if len(cells) < 5:
            continue
        a_horse = tr.select_one("a[href*='/horse/']")
        if not a_horse:
            continue
        hm = re.search(r"/horse/(\w+)", a_horse.get("href", ""))
        pos_txt = g(cells, "着順", "着 順")
        a_jockey = tr.select_one("a[href*='/jockey/']")
        bw_txt = g(cells, "馬体重") or ""
        race.entries.append(
            Entry(
                horse_id=hm.group(1) if hm else None,
                horse_name=a_horse.get_text(strip=True),
                horse_number=_int(g(cells, "馬番")),
                draw=_int(g(cells, "枠番", "枠")),
                sex_age=g(cells, "性齢"),
                weight_carried=_num(g(cells, "斤量")),
                jockey=a_jockey.get_text(strip=True) if a_jockey else None,
                body_weight=_int(bw_txt.split("(")[0]) if bw_txt else None,
                scratched=pos_txt in ("中止", "取消", "除外", "-", None),
                result_finish_pos=_int(pos_txt),
            )
        )
    race.field_size = len(race.entries)
    return race


# ---------------------------------------------------------------- payouts (払戻)
_PAY_KEYS = {
    "単勝": "win", "複勝": "place", "枠連": "bracket", "馬連": "quinella",
    "ワイド": "wide", "馬単": "exacta", "3連複": "trio", "三連複": "trio",
    "3連単": "trifecta", "三連単": "trifecta",
}


def fetch_payouts(race_id: str) -> dict:
    """確定した払戻を返す。 {kind: [{"combo": [nums], "yen": int, "pop": int}, ...]}"""
    html = get_client().get_text(RESULT_URL.format(race_id=race_id), TTL_RESULT)
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, list] = {}
    for tr in soup.select("table.pay_table_01 tr, table.Payout_Detail_Table tr"):
        cells = tr.select("th, td")
        if len(cells) < 3:
            continue
        kind = _PAY_KEYS.get(cells[0].get_text(strip=True))
        if not kind:
            continue
        combos_raw = list(cells[1].stripped_strings)
        yens_raw = re.findall(r"[\d,]+", cells[2].get_text(" ", strip=True))
        pops_raw = re.findall(r"\d+", cells[3].get_text(" ", strip=True)) if len(cells) > 3 else []
        # combos は "11-12" 形式や複数行
        combo_texts = re.findall(r"[\d]+(?:\s*[-→]\s*[\d]+)*", " ".join(combos_raw))
        rows = []
        for i, ct in enumerate(combo_texts):
            nums = [int(x) for x in re.findall(r"\d+", ct)]
            yen = int(yens_raw[i].replace(",", "")) if i < len(yens_raw) else None
            pop = int(pops_raw[i]) if i < len(pops_raw) else None
            if nums and yen:
                rows.append({"combo": nums, "yen": yen, "pop": pop})
        if rows:
            out[kind] = rows
    return out


# ---------------------------------------------------------------- 追切 (best effort)
OIKIRI_URL = "https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
_OIKIRI_RATING = {"S": 1.0, "A": 0.6, "B": 0.0, "C": -0.5, "D": -1.0}


def fetch_workouts(race_id: str) -> dict:
    """最終追切の評価を返す。 {horse_id or umaban: score}

    netkeiba の追切評価は JavaScript 描画かつ多くが有料のため、
    静的 HTML から取れた範囲のみ返す (通常は空)。取れなくても致命的ではない。
    """
    try:
        html = get_client().get_text(OIKIRI_URL.format(race_id=race_id), TTL_SHUTUBA, encoding="utf-8")
    except Exception:  # noqa: BLE001
        return {}
    soup = BeautifulSoup(html, "lxml")
    out: dict = {}
    for row in soup.select("tr.HorseList, .OikiriRow, [class*='Oikiri'] tr"):
        a = row.select_one("a[href*='/horse/']")
        rating_el = row.select_one("[class*='Hyoka'], [class*='Eval'], .Oikiri_Hyoka")
        if not a or not rating_el:
            continue
        m = re.search(r"/horse/(\w+)", a.get("href", ""))
        letter = rating_el.get_text(strip=True)[:1].upper()
        if m and letter in _OIKIRI_RATING:
            out[m.group(1)] = _OIKIRI_RATING[letter]
    return out
