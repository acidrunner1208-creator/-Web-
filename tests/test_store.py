"""過去戦績の永続ストア (builder.store) のテスト。"""
from datetime import date

import pytest

import builder.store as store_mod
from builder.scraping.models import PastRun
from builder.store import HorseStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE_PATH", tmp_path / "horse_store.json.gz")
    monkeypatch.setattr(store_mod, "_today_override", date(2026, 9, 8))
    return HorseStore()


def _run(d, pos=3):
    return PastRun(date=d, finish_pos=pos, field_size=12, distance=1600,
                   surface="芝", passing="4-4", last_3f=34.2, time_sec=94.1)


def test_put_fresh_roundtrip_and_persist(store, tmp_path):
    store.put("A", "アルファ", [_run("2026-08-20"), _run("2026-07-01")])
    store.save_if_dirty()
    assert (tmp_path / "horse_store.json.gz").exists()

    reopened = HorseStore()
    runs = reopened.fresh_runs("A")
    assert runs is not None and len(runs) == 2
    assert runs[0].last_3f == 34.2 and runs[0].surface == "芝"


def test_fresh_expires_after_ttl(store, monkeypatch):
    store.put("B", "ベータ", [_run("2026-06-01")])
    # 11 日後 = FRESH_DAYS(10) 超過 -> 再取得が必要
    monkeypatch.setattr(store_mod, "_today_override", date(2026, 9, 19))
    assert store.fresh_runs("B") is None


def test_gc_removes_retired_and_long_inactive_but_keeps_active(store):
    store.put("ACTIVE", "現役", [_run("2025-05-01")])
    store.put("RETIRED", "抹消済", [_run("2026-04-01")], retired=True)   # 抹消 & 約5か月 -> 削除
    store.put("INACTIVE", "長期不出走", [_run("2024-12-01")])            # 約21か月 -> 削除
    store.put("RECENT", "最近走った", [_run("2026-08-01")])              # 現役扱い -> 残る

    removed = set(store.gc(active_ids={"ACTIVE"}))
    assert removed == {"RETIRED", "INACTIVE"}
    assert set(store.horses) == {"ACTIVE", "RECENT"}


def test_gc_keeps_retired_horse_that_is_entered_again(store):
    store.put("COMEBACK", "復帰", [_run("2026-03-01")], retired=True)
    removed = store.gc(active_ids={"COMEBACK"})
    assert removed == []
    assert "COMEBACK" in store.horses
