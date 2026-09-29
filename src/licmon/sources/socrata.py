"""Shared fetch helper for Socrata (SODA) open-data portals."""

from __future__ import annotations

import json
import os

from ..http import Http
from ..models import Snapshot

PAGE_SIZE = 50000


def fetch_all(http: Http, domain: str, dataset: str, *, where: str | None = None,
              order: str = ":id", page_size: int = PAGE_SIZE,
              max_pages: int = 20) -> list[Snapshot]:
    """Fetch every row matching `where`, one snapshot per page.

    Ordered by `order` so identical data yields identical bytes (stable hash).
    Uses SOCRATA_APP_TOKEN when set (raises Socrata's anonymous throttle).
    """
    url = f"https://{domain}/resource/{dataset}.json"
    headers = {}
    token = os.environ.get("SOCRATA_APP_TOKEN")
    if token:
        headers["X-App-Token"] = token
    snapshots: list[Snapshot] = []
    for page in range(max_pages):
        params = {"$limit": page_size, "$offset": page * page_size, "$order": order}
        if where:
            params["$where"] = where
        snap = http.get(url, params=params, headers=headers)
        snapshots.append(snap)
        if len(json.loads(snap.body)) < page_size:
            return snapshots
    raise RuntimeError(f"{dataset}: more than {max_pages} pages; raise max_pages")


def rows(snapshots: list[Snapshot]) -> list[dict]:
    out: list[dict] = []
    for snap in snapshots:
        data = json.loads(snap.body)
        if not isinstance(data, list):
            raise ValueError("Socrata response is not a JSON array")
        out.extend(data)
    return out
