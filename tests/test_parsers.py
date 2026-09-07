from bs4 import BeautifulSoup

from builder.scraping import netkeiba as nk
from builder.sim.horse_model import class_level

SHUTUBA_ROW = """
<table class="Shutuba_Table">
<tr class="HorseList" id="tr_5">
  <td class="Waku Waku3"><span>3</span></td>
  <td class="Umaban Umaban5">5</td>
  <td class="HorseInfo"><div class="HorseName">
    <a href="https://db.netkeiba.com/horse/2020104512/">テストホース</a></div></td>
  <td class="Barei Txt_C">牡4</td>
  <td class="Txt_C"><span class="JockeyWeight">57.0</span></td>
  <td class="Jockey"><a href="https://db.netkeiba.com/jockey/05339/">ルメール</a></td>
  <td class="Trainer"><span>栗東</span><a href="https://db.netkeiba.com/trainer/01075/">テスト師</a></td>
  <td class="Weight">486<small>(+4)</small></td>
</tr>
</table>
"""

HORSE_RESULTS = """
<table class="db_h_race_results nk_tb_common">
<tr><th>日付</th><th>開催</th><th>天気</th><th>R</th><th>レース名</th><th>頭数</th>
<th>枠番</th><th>馬番</th><th>オッズ</th><th>人気</th><th>着順</th><th>騎手</th><th>斤量</th>
<th>距離</th><th>馬場</th><th>タイム</th><th>着差</th><th>通過</th><th>ペース</th><th>上り</th>
<th>馬体重</th><th>賞金</th></tr>
<tr><td>2026/06/20</td><td>3阪神5</td><td>雨</td><td>11</td><td>天保山S(OP)</td><td>15</td>
<td>3</td><td>5</td><td>259.4</td><td>14</td><td>12</td><td>川又賢治</td><td>58</td>
<td>ダ1400</td><td>重</td><td>1:24.8</td><td>1.3</td><td>5-6</td><td>35.4-36.1</td><td>37.0</td>
<td>456(0)</td><td></td></tr>
</table>
"""


def test_parse_time_to_sec():
    assert nk.parse_time_to_sec("1:34.5") == 94.5
    assert nk.parse_time_to_sec("58.9") == 58.9
    assert nk.parse_time_to_sec("--") is None


def test_surface_distance():
    assert nk._surface_distance("芝2400") == ("芝", 2400)
    assert nk._surface_distance("ダ1600") == ("ダ", 1600)


def test_venue_from_race_id():
    assert nk.venue_from_race_id("202405021211") == "東京"
    assert nk.venue_from_race_id("202406010101") == "中山"


def test_class_level_ordering():
    assert class_level("G1") > class_level("オープン") > class_level("3勝クラス")
    assert class_level("未勝利") < class_level("1勝クラス")


def test_parse_shutuba_row():
    tr = BeautifulSoup(SHUTUBA_ROW, "lxml").select_one("tr.HorseList")
    e = nk._parse_shutuba_row(tr)
    assert e.horse_name == "テストホース"
    assert e.horse_id == "2020104512"
    assert e.horse_number == 5
    assert e.draw == 3
    assert e.sex_age == "牡4"
    assert e.weight_carried == 57.0
    assert e.jockey == "ルメール"
    assert e.body_weight == 486
    assert e.body_weight_diff == 4


def test_parse_horse_results(monkeypatch):
    from builder.scraping import client

    class FakeClient:
        def get_text(self, *a, **k):
            return HORSE_RESULTS

    monkeypatch.setattr(client, "get_client", lambda: FakeClient())
    monkeypatch.setattr(nk, "get_client", lambda: FakeClient())
    runs = nk.fetch_horse_history("2020104512", limit=5)
    assert len(runs) == 1
    r = runs[0]
    assert r.finish_pos == 12
    assert r.field_size == 15
    assert r.surface == "ダ" and r.distance == 1400
    assert r.track_condition == "重"
    assert r.time_sec == 84.8
    assert r.passing == "5-6"
    assert r.last_3f == 37.0
    assert r.body_weight == 456
