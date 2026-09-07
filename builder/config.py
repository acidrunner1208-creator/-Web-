"""ビルダー設定 (環境変数 / .env)。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- スクレイピング ---
    scraping_enabled: bool = True
    request_delay_seconds: float = 2.5
    user_agent: str = (
        "keiba-simulator/2.0 (personal research use; contact: you@example.com)"
    )
    respect_robots_txt: bool = True
    http_timeout_seconds: float = 20.0

    # --- 動作モード ---
    demo_mode: bool = False

    # --- シミュレーション ---
    n_sims: int = 10000
    history_limit: int = 12          # 1頭あたり取得する過去走数
    animation_ticks: int = 26

    # --- 出力 / パス ---
    cache_dir: str = "./.cache"
    out_dir: str = "./public"
    max_races: int | None = None     # 試験時にレース数を制限

    @property
    def cache_path(self) -> Path:
        p = Path(self.cache_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def out_path(self) -> Path:
        p = Path(self.out_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()
