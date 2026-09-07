"""過去戦績の永続キャッシュ (gzip JSON)。

GitHub Actions のバッチ実行をまたいで共有する保存庫。毎回すべての出走馬を
netkeiba から取り直さないためのもの。

- `builder/data/horse_store.json.gz` に保存し、リポジトリにコミットする。
  容量を抑えるため gzip + 1 頭あたりの過去走を `history_limit` 本で打ち切り、
  キーを短縮した配列形式で持つ。
- 出走が確認できた馬は `last_seen` を更新。
- `gc()` が「現在の出走表に無く、長期間出走していない」または
  「netkeiba で抹消と判定された」馬のデータを自動削除する（引退馬の掃除）。
"""
from __future__ import annotations

import gzip
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from builder.scraping.models import PastRun

log = logging.getLogger("store")

STORE_PATH = Path(__file__).parent / "data" / "horse_store.json.gz"

FRESH_DAYS = 10       # 保存済みがこの日数以内なら再取得しない
INACTIVE_DAYS = 460   # 最終出走からこれ以上 & 出走表に無ければ削除 (実質引退)
RETIRED_DAYS = 120    # netkeiba で抹消と判定でき、最終出走からこの日数以上なら早期削除

# PastRun の全フィールドのうち保存する項目 (シミュレーションで使うもの)
_KEEP = ("date", "venue", "race_name", "field_size", "draw", "horse_number",
         "popularity", "finish_pos", "weight_carried", "distance", "surface",
         "track_condition", "time_sec", "margin", "passing", "pace", "last_3f",
         "body_weight", "body_weight_diff")

_today_override: date | None = None  # テスト用


def _today() -> date:
    return _today_override or date.today()


def _compact(run: PastRun) -> dict:
    d = run.model_dump()
    return {k: d[k] for k in _KEEP if d.get(k) is not None}


# --------------------------------------------------------------------- I/O
def _load() -> dict:
    if not STORE_PATH.exists():
        return {"horses": {}, "updated": None}
    try:
        with gzip.open(STORE_PATH, "rt", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("horses", {})
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("store 読み込み失敗 (%s) — 作り直します", exc)
        return {"horses": {}, "updated": None}


def _save(data: dict) -> None:
    data["updated"] = datetime.now(timezone.utc).isoformat()
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".gz.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(STORE_PATH)


# --------------------------------------------------------------------- store
class HorseStore:
    def __init__(self) -> None:
        self._data = _load()
        self._dirty = False

    @property
    def horses(self) -> dict:
        return self._data["horses"]

    def fresh_runs(self, horse_id: str) -> list[PastRun] | None:
        """TTL 内で保存済みなら過去走を返す。無ければ None (要スクレイピング)。"""
        h = self.horses.get(horse_id)
        if not h or not h.get("fetched"):
            return None
        try:
            age = (_today() - date.fromisoformat(h["fetched"][:10])).days
        except ValueError:
            return None
        if age > FRESH_DAYS:
            return None
        return [PastRun(**r) for r in h.get("runs", [])]

    def put(self, horse_id: str, name: str, runs: list[PastRun], *,
            retired: bool = False) -> None:
        compact = [_compact(r) for r in runs]
        last_run = max((r.get("date", "")[:10] for r in compact if r.get("date")), default=None)
        self.horses[horse_id] = {
            "name": name,
            "fetched": _today().isoformat(),
            "last_seen": _today().isoformat(),
            "last_run": last_run,
            "retired": bool(retired),
            "runs": compact,
        }
        self._dirty = True

    def touch(self, horse_id: str) -> None:
        h = self.horses.get(horse_id)
        if h:
            h["last_seen"] = _today().isoformat()
            self._dirty = True

    def gc(self, active_ids: set[str]) -> list[str]:
        """出走予定に無く、長期不出走 or 抹消済みの馬を削除。削除した horse_id を返す。"""
        today = _today()
        drop: list[str] = []
        for hid, h in self.horses.items():
            if hid in active_ids:
                continue
            ref = h.get("last_run") or (h.get("fetched") or "")[:10]
            try:
                age = (today - date.fromisoformat(ref)).days
            except ValueError:
                continue
            limit = RETIRED_DAYS if h.get("retired") else INACTIVE_DAYS
            if age >= limit:
                drop.append(hid)
        for hid in drop:
            del self.horses[hid]
        if drop:
            self._dirty = True
        return drop

    def save_if_dirty(self) -> None:
        if self._dirty:
            _save(self._data)
            self._dirty = False

    def stats(self) -> dict:
        runs = sum(len(h.get("runs", ())) for h in self.horses.values())
        size = STORE_PATH.stat().st_size if STORE_PATH.exists() else 0
        return {"horses": len(self.horses), "runs": runs, "kb": round(size / 1024, 1)}
