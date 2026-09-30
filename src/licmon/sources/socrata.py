"""Shared fetch helper for Socrata (SODA) open-data portals."""

from __future__ import annotations

import json
import os
import re

from ..http import Http
from ..models import Snapshot

PAGE_SIZE = 50000


def fetch_all(http: Http, domain: str, dataset: str, *, where: str | None = None,
              order: str = ":id", page_size: int = PAGE_SIZE,
              max_pages: int = 20, select: str | None = None) -> list[Snapshot]:
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
        if select:
            params["$select"] = select
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


#: Address filters per query. Each is ~70 characters, so a batch stays well
#: under URL length limits.
ADDRESS_BATCH = 40


def rows_near(http: Http, domain: str, dataset: str, records, *, zip_field: str,
              address_field: str, select: str, city_field: str | None = None,
              where: str | None = None) -> list[dict]:
    """Rows of a license list at the same ZIP (or city) and house number as
    any of `records`, in batched queries: ``starts_with(zip, '78701') AND
    starts_with(address, '216')``. The match is loose on purpose (2160 also
    starts with 216); callers confirm with history.same_premises. Records
    without a house number, or without a ZIP and city, are skipped."""
    from ..history import house_number

    keys = set()
    for rec in records:
        number = house_number(rec.address)
        zip5 = re.sub(r"\D", "", rec.zip or "")[:5]
        city = re.sub(r"[^A-Z ]", "", (rec.city or "").upper()).strip()
        if not number:
            continue
        if len(zip5) == 5:
            keys.add(("zip", zip5, number))
        elif city and city_field:
            keys.add(("city", city, number))
    clauses = []
    for kind, place, number in sorted(keys):
        test = (f"starts_with({zip_field}, '{place}')" if kind == "zip"
                else f"upper({city_field}) = '{place}'")
        clauses.append(f"({test} AND starts_with({address_field}, '{number}'))")
    out: list[dict] = []
    for i in range(0, len(clauses), ADDRESS_BATCH):
        cond = "(" + " OR ".join(clauses[i:i + ADDRESS_BATCH]) + ")"
        if where:
            cond = f"({where}) AND {cond}"
        out.extend(rows(fetch_all(http, domain, dataset, where=cond, select=select,
                                  page_size=5000)))
    return out
