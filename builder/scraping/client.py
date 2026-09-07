"""サーバーに優しい HTTP クライアント (オフラインバッチ専用)。

- robots.txt を尊重
- リクエスト間隔 (sleep + ジッター) を強制
- ファイルキャッシュで再取得を回避 (バッチ再実行が速い)
- 5xx / タイムアウトは指数バックオフでリトライ
- 403 / 429 を受けたら待機してから中断
"""
from __future__ import annotations

import hashlib
import logging
import random
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from builder.config import get_settings

log = logging.getLogger("scraper")


class ScrapingDisabledError(RuntimeError):
    pass


class PoliteBlockedError(RuntimeError):
    """相手サーバーが 403/429 を返した。"""


class PoliteClient:
    def __init__(self) -> None:
        s = get_settings()
        self.settings = s
        self._cache = s.cache_path / "http"
        self._cache.mkdir(parents=True, exist_ok=True)
        self._last = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._client = httpx.Client(
            headers={"User-Agent": s.user_agent, "Accept-Language": "ja,en;q=0.8"},
            timeout=s.http_timeout_seconds,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last
        sleep_for = self.settings.request_delay_seconds - elapsed + random.uniform(0.4, 1.4)
        if sleep_for > 0:
            time.sleep(sleep_for)
        self._last = time.monotonic()

    def _robots_ok(self, url: str) -> bool:
        if not self.settings.respect_robots_txt:
            return True
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                self._wait()
                resp = self._client.get(f"{base}/robots.txt")
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse([])
            self._robots[base] = rp
        return rp.can_fetch(self.settings.user_agent, url)

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _do_get(self, url: str) -> httpx.Response:
        self._wait()
        log.info("GET %s", url)
        resp = self._client.get(url)
        if resp.status_code in (403, 429):
            log.warning("Blocked (%s) on %s", resp.status_code, url)
            time.sleep(30)
            raise PoliteBlockedError(f"{resp.status_code} for {url}")
        if resp.status_code >= 500:
            resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    def _cache_file(self, url: str) -> Path:
        return self._cache / (hashlib.sha256(url.encode()).hexdigest() + ".bin")

    def get_bytes(self, url: str, ttl_seconds: int, *, use_cache: bool = True) -> bytes:
        if not self.settings.scraping_enabled:
            raise ScrapingDisabledError("SCRAPING_ENABLED=false")
        cf = self._cache_file(url)
        if use_cache and cf.exists() and (time.time() - cf.stat().st_mtime) < ttl_seconds:
            return cf.read_bytes()
        if not self._robots_ok(url):
            raise PoliteBlockedError(f"robots.txt disallows {url}")
        resp = self._do_get(url)
        if resp.status_code == 200:
            cf.write_bytes(resp.content)
            return resp.content
        if cf.exists():
            return cf.read_bytes()
        raise httpx.HTTPStatusError(f"status {resp.status_code}", request=resp.request, response=resp)

    def get_text(self, url: str, ttl_seconds: int, encoding: str | None = None, **kw) -> str:
        raw = self.get_bytes(url, ttl_seconds, **kw)
        if encoding:
            return raw.decode(encoding, errors="replace")
        host = urlparse(url).netloc
        if host.startswith("db."):
            return raw.decode("euc_jp", errors="replace")
        return raw.decode("utf-8", errors="replace")

    def close(self) -> None:
        self._client.close()


_client: PoliteClient | None = None


def get_client() -> PoliteClient:
    global _client
    if _client is None:
        _client = PoliteClient()
    return _client
