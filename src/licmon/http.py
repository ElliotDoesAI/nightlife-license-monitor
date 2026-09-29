"""Polite HTTP client with retries for official public sources."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Snapshot

USER_AGENT = "nightlife-license-monitor/0.1 (public-records research; daily, low volume)"


class SourceHTTPError(RuntimeError):
    """HTTP failure. Message holds only status and public URL, safe to log."""


class Http:
    def __init__(self, timeout: float = 120, min_interval: float = 1.0,
                 retries: int = 4, headers: dict | None = None):
        self.timeout = timeout
        self.min_interval = min_interval
        self._last = 0.0
        self.session = requests.Session()
        retry = Retry(
            total=retries,
            backoff_factor=2,  # 0, 2, 4, 8 s ...
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers["User-Agent"] = USER_AGENT
        if headers:
            self.session.headers.update(headers)

    def get(self, url: str, params: dict | None = None,
            headers: dict | None = None) -> Snapshot:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            resp = self.session.get(url, params=params, headers=headers,
                                    timeout=self.timeout)
        except requests.RequestException as exc:
            raise SourceHTTPError(f"{type(exc).__name__} fetching {url}") from None
        finally:
            self._last = time.monotonic()
        if resp.status_code != 200:
            raise SourceHTTPError(f"HTTP {resp.status_code} fetching {resp.url}")
        return Snapshot(
            url=resp.url,
            body=resp.content,
            content_type=resp.headers.get("Content-Type", "application/octet-stream"),
            fetched_at=datetime.now(timezone.utc),
        )
