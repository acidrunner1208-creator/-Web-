"""スクレイピングで取得するドメインモデル。"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class PastRun(BaseModel):
    """1頭の過去1走分の戦績とレース展開。"""

    date: str | None = None
    venue: str | None = None
    weather: str | None = None
    race_name: str | None = None
    field_size: int | None = None
    draw: int | None = None
    horse_number: int | None = None
    odds: float | None = None          # 過去走時点の確定オッズ (履歴。リアルタイム取得ではない)
    popularity: int | None = None
    finish_pos: int | None = None
    jockey: str | None = None
    weight_carried: float | None = None
    distance: int | None = None
    surface: str | None = None
    track_condition: str | None = None
    time_sec: float | None = None
    margin: str | None = None
    passing: str | None = None         # "3-3-2-1"
    pace: str | None = None            # "37.2-35.1"
    last_3f: float | None = None
    body_weight: int | None = None
    body_weight_diff: int | None = None
    prize: float | None = None


class Entry(BaseModel):
    """今回のレースの1出走馬 (リアルタイムのオッズ・人気は保持しない)。"""

    horse_id: str | None = None
    horse_name: str
    horse_number: int | None = None
    draw: int | None = None
    sex_age: str | None = None
    weight_carried: float | None = None
    jockey: str | None = None
    jockey_id: str | None = None
    trainer: str | None = None
    trainer_area: str | None = None
    body_weight: int | None = None
    body_weight_diff: int | None = None
    sire: str | None = None
    dam_sire: str | None = None
    scratched: bool = False
    result_finish_pos: int | None = None
    past_runs: list[PastRun] = Field(default_factory=list)

    @property
    def netkeiba_url(self) -> str | None:
        return f"https://db.netkeiba.com/horse/{self.horse_id}/" if self.horse_id else None


class Race(BaseModel):
    race_id: str
    kaisai_date: str
    venue: str | None = None
    race_number: int | None = None
    race_name: str | None = None
    start_time: str | None = None
    surface: str | None = None
    distance: int | None = None
    direction: str | None = None
    weather: str | None = None
    track_condition: str | None = None
    race_class: str | None = None
    field_size: int | None = None
    source_url: str | None = None
    entries: list[Entry] = Field(default_factory=list)
    fetched_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RaceListItem(BaseModel):
    race_id: str
    kaisai_date: str
    venue: str | None = None
    race_number: int | None = None
    race_name: str | None = None
    start_time: str | None = None
