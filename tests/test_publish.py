"""X スレッド / note 本文の生成テスト。"""
from builder.publish import (
    _day_attention,
    _oauth1_header,
    build_note_markdown,
    build_x_thread,
)


def _race(rid, venue, rno, name, conf_tier, conf, axis):
    return {
        "race_id": rid, "kaisai_date": "2026-09-13", "venue": venue,
        "race_number": rno, "race_name": name, "surface": "芝", "distance": 1600,
        "start_time": "15:45", "confidence": conf, "confidence_tier": conf_tier,
        "horses": [{"num": axis, "name": f"馬{axis}", "win_prob": 0.34, "place_prob": 0.71,
                    "avg_finish": 3.1, "fair_win_odds": 2.9}],
        "recommended": [
            {"key": "tansho", "type": "単勝", "selection": f"{axis}", "unit": 1},
            {"key": "sanrenpuku", "type": "3連複", "method": "流し",
             "selection": f"{axis} 軸 → 2・3・4・5・6", "unit": 10},
            {"key": "sanrentan", "type": "3連単", "method": "流し",
             "selection": f"{axis} 流し → 2・3・4・5", "unit": 12},
        ],
    }


def _payload():
    races = [
        _race("A", "中山", 11, "セントライト記念", "高", 0.35, 7),
        _race("B", "阪神", 11, "ローズS", "中", 0.20, 3),
        _race("C", "中山", 9, "習志野特別", "中", 0.24, 6),
        _race("D", "阪神", 8, "1勝クラス", "低", 0.08, 1),
    ]
    return {"races": races}


def test_day_attention_picks_top3_by_confidence():
    att = _day_attention(_payload()["races"])
    assert [r["race_id"] for r in att] == ["A", "C", "B"]


def test_x_thread_structure_and_length():
    att = _day_attention(_payload()["races"])
    thread = build_x_thread(att, "9/13（日）", "https://note.com/u/xyz")
    assert len(thread) >= 2
    assert all(len(seg) <= 280 for seg in thread)
    joined = "\n".join(thread)
    for token in ("注目レース", "軸", "勝率", "複勝", "適正", "単勝", "3連複", "3連単"):
        assert token in joined
    # 最後は note 宣伝 (返信でぶら下げる)
    assert "¥300" in thread[-1] and "https://note.com/u/xyz" in thread[-1]


def test_note_markdown_has_all_races_and_fields():
    md = build_note_markdown(_payload()["races"], "9/13（日）")
    assert md.count("### ") == 4                     # 4レースぶんの見出し
    for token in ("自信度", "軸：", "平均着順", "勝率", "複勝率", "適正オッズ",
                  "単勝：", "3連複（流し）", "3連単（流し）"):
        assert token in md


def test_oauth1_header_shape():
    h = _oauth1_header("POST", "https://api.twitter.com/2/tweets",
                       "ck", "cs", "at", "ats")
    assert h.startswith("OAuth ")
    assert "oauth_signature=" in h and "oauth_consumer_key=" in h
