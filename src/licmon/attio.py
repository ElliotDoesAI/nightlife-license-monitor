"""Attio CRM: the "License Leads" list on Targets, and the daily sync into it.

Hot, tier A, and tier B venues with a lead score of at least
ATTIO_MIN_B_SCORE (default 60) go to Attio. Adult venues never do. Each one becomes (or reuses) a record
in the workspace's existing Targets object (``target_client``) and gets an
entry in the "License Leads" list, whose parent object is Targets. All the
lead detail lives on the list entry, so the Targets object itself is never
changed structurally: no attribute is ever created on it. Attio is the
owner's internal CRM: nothing here contacts a business.

* ``setup`` creates the list, its entry attributes and their select options.
  It only ever creates new things: it stops if the list already exists.
* ``sync`` dedupes on the Venue key entry attribute. A venue already in the
  list gets only its stage, score and priority refreshed; the team's Status is
  never touched after the entry is made. A new venue reuses a Target with the
  same name (case-insensitive exact match) or creates a minimal one: name,
  client type Venue, status Prespecting. New Targets are capped per day
  (ATTIO_DAILY_CAP, default 50), highest score first. Before its first
  write the sync adds any missing Priority option (the live list was made
  with Hot and A only, before B leads were sent).

Endpoints and payloads follow the Attio REST API v2 reference
(docs.attio.com/rest-api/endpoint-reference, checked 2026-09-29). Public
Actions logs must never hold lead data, so errors carry the HTTP status, the
error type and Attio's error ``code`` only (never a response body), and
callers log counts only.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

API = "https://api.attio.com/v2"

LIST_SLUG = "license_leads"
LIST_NAME = "License Leads"
PARENT_OBJECT = "target_client"  # the existing Targets object
#: Everyone in the workspace can see and manage the list.
WORKSPACE_ACCESS = "full-access"

#: Target fields the sync writes when it has to create one. Spellings are
#: Attio's own (speakeasy-attio-crm/SCHEMA.md): "Prespecting" is not a typo
#: to fix. created_at is also marked required but Attio fills it itself.
TARGET_NAME = "company_1"
TARGET_TYPE_ATTR, TARGET_TYPE = "client_type", "Venue"
TARGET_STATUS_ATTR, TARGET_STATUS = "status", "Prespecting"

MATCH_ATTRIBUTE = "venue_key"
STATUS_ATTRIBUTE = "team_status"
#: The only entry fields a repeat venue has refreshed.
UPDATE_FIELDS = ("stage", "score", "priority")
DEFAULT_DAILY_CAP = 50
#: Tier B venues need at least this lead score to go to Attio.
DEFAULT_MIN_B_SCORE = 60

STAGE_OPTIONS = ["Licensed", "Approved", "In review", "Received"]
PRIORITY_OPTIONS = ["Hot", "A", "B"]
STATUS_OPTIONS = ["New", "Moved to Targets", "Not a fit", "Contacted"]

#: List entry attributes: (api_slug, title, type, is_unique, select options).
#: Attio has no URL attribute type, so links are text. Market and State are
#: text, not selects, so a new state needs no workspace change. The venue name
#: is the parent Target's name, so it is not repeated here.
ATTRIBUTES: list[tuple[str, str, str, bool, list[str] | None]] = [
    (MATCH_ATTRIBUTE, "Venue key", "text", True, None),
    ("priority", "Priority", "select", False, PRIORITY_OPTIONS),
    ("score", "Score", "number", False, None),
    ("stage", "Stage", "select", False, STAGE_OPTIONS),
    ("market", "Market", "text", False, None),
    ("state", "State", "text", False, None),
    ("address", "Address", "text", False, None),
    ("owner_company", "Owner / company", "text", False, None),
    ("phone", "Phone", "text", False, None),
    ("license", "License", "text", False, None),
    ("filing_type", "Filing type", "text", False, None),
    ("filed_on", "Filed on", "date", False, None),
    ("first_seen", "First seen", "date", False, None),
    ("official_record", "Official record", "text", False, None),
    ("map_link", "Map", "text", False, None),
    ("google_link", "Google", "text", False, None),
    ("instagram_link", "Instagram", "text", False, None),
    (STATUS_ATTRIBUTE, "Status", "select", False, STATUS_OPTIONS),
]

_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")


class AttioError(RuntimeError):
    """Attio failure with a value-free message: HTTP status, error type and
    Attio's error code (e.g. quota_exceeded). Never a response body."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def api_key() -> str:
    """ATTIO_WRITE_API_KEY if set (a key allowed to change the schema),
    else ATTIO_API_KEY."""
    return (os.environ.get("ATTIO_WRITE_API_KEY", "").strip()
            or os.environ.get("ATTIO_API_KEY", "").strip())


def configured() -> bool:
    return bool(api_key())


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("ATTIO_DAILY_CAP", "").strip()
                          or DEFAULT_DAILY_CAP))
    except ValueError:
        return DEFAULT_DAILY_CAP


def min_b_score() -> int:
    """Lowest lead score a tier B venue needs to go to Attio (ATTIO_MIN_B_SCORE)."""
    try:
        return int(os.environ.get("ATTIO_MIN_B_SCORE", "").strip() or DEFAULT_MIN_B_SCORE)
    except ValueError:
        return DEFAULT_MIN_B_SCORE


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _error_code(resp) -> str:
    """Attio's machine error code (e.g. quota_exceeded, slug_conflict). Only a
    short snake_case identifier is kept, so no free text can leak."""
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 - no body, no code
        return ""
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, str) and _CODE.fullmatch(code) else ""


def _retry_wait(value: str | None) -> float:
    """Seconds to wait from Retry-After, which Attio sends as an HTTP date
    (seconds are accepted too). Clamped to 0 to 10 s."""
    if not value:
        return 1.0
    try:
        wait = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            wait = (when - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            return 1.0
    return min(max(wait, 0.0), 10.0)


class Client:
    """Small JSON client for Attio. http.py stays GET-only for the scrapers."""

    def __init__(self, key: str | None = None, session=None, sleep=time.sleep):
        import requests

        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {key or api_key()}",
                                     "Content-Type": "application/json"})
        self.sleep = sleep

    def request(self, method: str, path: str, *, body: dict | None = None,
                params: dict | None = None, allow_404: bool = False):
        for attempt in range(4):
            try:
                resp = self.session.request(method, API + path, json=body,
                                            params=params, timeout=30)
            except Exception as exc:  # noqa: BLE001 - type only, values stay private
                raise AttioError(f"attio failed ({type(exc).__name__})") from exc
            if resp.status_code == 429 and attempt < 3:
                self.sleep(_retry_wait(resp.headers.get("Retry-After")))
                continue
            if allow_404 and resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                code = _error_code(resp)
                raise AttioError(f"attio failed (HTTP {resp.status_code}"
                                 + (f" {code}" if code else "") + ")")
            try:
                return resp.json()
            except ValueError as exc:
                raise AttioError("attio failed (bad JSON)") from exc
        raise AttioError("attio failed (HTTP 429 rate_limit_exceeded)")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def list_payload() -> dict:
    """POST /v2/lists body. workspace_access and workspace_member_access are
    both required; full-access for the workspace means the team sees it."""
    return {"data": {"name": LIST_NAME, "api_slug": LIST_SLUG,
                     "parent_object": PARENT_OBJECT,
                     "workspace_access": WORKSPACE_ACCESS,
                     "workspace_member_access": []}}


def attribute_payload(slug: str, title: str, kind: str, unique: bool) -> dict:
    """POST /v2/lists/{list}/attributes body (every field Attio requires)."""
    return {"data": {"title": title, "description": None, "api_slug": slug,
                     "type": kind, "is_required": False, "is_unique": unique,
                     "is_multiselect": False, "config": {}}}


def setup(client: Client | None, write: bool) -> list[str]:
    """Create the License Leads list on Targets, its entry attributes and
    their options. Dry run unless `write`. Returns plain step lines (schema
    names only, no lead data). Raises AttioError if the list already exists.
    Never changes the Targets object."""
    steps: list[str] = []
    if client is not None:
        if client.request("GET", f"/lists/{LIST_SLUG}", allow_404=True) is not None:
            raise AttioError(f"list {LIST_SLUG} already exists; nothing changed")
        if client.request("GET", f"/objects/{PARENT_OBJECT}", allow_404=True) is None:
            raise AttioError(f"object {PARENT_OBJECT} not found; nothing changed")
    steps.append(f"create list {LIST_NAME} ({LIST_SLUG}) on Targets "
                 f"({PARENT_OBJECT}), open to the whole workspace")
    if write:
        client.request("POST", "/lists", body=list_payload())
        listed = client.request("GET", f"/lists/{LIST_SLUG}/attributes") or {}
        have = {a.get("api_slug") for a in listed.get("data") or []}
    else:
        have = set()
    for slug, title, kind, unique, options in ATTRIBUTES:
        if slug in have:
            steps.append(f"keep list field {title} (Attio made it)")
            continue
        steps.append(f"create list field {title} ({kind}{', unique' if unique else ''})")
        if write:
            client.request("POST", f"/lists/{LIST_SLUG}/attributes",
                           body=attribute_payload(slug, title, kind, unique))
        for option in options or []:
            steps.append(f"  add option {option}")
            if write:
                client.request("POST", f"/lists/{LIST_SLUG}/attributes/{slug}/options",
                               body={"data": {"title": option}})
    return steps


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def _wanted(row: dict, min_b: int) -> bool:
    if row.get("adult"):
        return False  # adult venues stay in the spreadsheet only
    if row.get("hot") or row.get("priority") == "A":
        return True
    return row.get("priority") == "B" and (row.get("lead_score") or 0) >= min_b


def candidates(rows: list[dict], min_b: int | None = None) -> list[dict]:
    """Hot, tier A and strong tier B venues (not adult) with a venue key and
    a name, highest score first, one row per venue."""
    min_b = min_b_score() if min_b is None else min_b
    picked = [r for r in rows if r.get("venue_key") and (r.get("business_name") or "").strip()
              and _wanted(r, min_b)]
    picked.sort(key=lambda r: (-(r.get("lead_score") or 0), r.get("business_name") or ""))
    unique: dict[str, dict] = {}
    for row in picked:  # a venue queued twice in a day is one entry
        unique.setdefault(row["venue_key"], row)
    return list(unique.values())


def _day(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def entry_values(row: dict) -> dict:
    """List entry values for a new entry. Blank fields are left out. The
    team's Status starts at New."""
    address = ", ".join(p for p in (row.get("address"), row.get("city"),
                                    row.get("state"), row.get("zip")) if p)
    values = {
        MATCH_ATTRIBUTE: row.get("venue_key"),
        "priority": "Hot" if row.get("hot") else (row.get("priority") or "A"),
        "score": row.get("lead_score"),
        "stage": row.get("stage") if row.get("stage") in STAGE_OPTIONS else None,
        "market": row.get("market"),
        "state": row.get("state"),
        "address": address,
        "owner_company": row.get("company"),
        "phone": row.get("phone"),
        "license": row.get("license"),
        "filing_type": row.get("filing"),
        "filed_on": _day(row.get("filed_on")),
        "first_seen": _day(row.get("first_seen")),
        "official_record": row.get("record_url"),
        "map_link": row.get("map_url"),
        "google_link": row.get("google_url"),
        "instagram_link": row.get("instagram_url"),
        STATUS_ATTRIBUTE: "New",
    }
    return {k: v for k, v in values.items() if v not in (None, "")}


def update_values(row: dict) -> dict:
    """What a repeat venue has refreshed: stage, score and priority only.
    Never the team's Status."""
    values = entry_values(row)
    return {k: values[k] for k in UPDATE_FIELDS if k in values}


def target_values(row: dict) -> dict:
    """The minimum for a new Target: name, client type Venue, status
    Prespecting. Nothing else on the Targets object is written."""
    return {TARGET_NAME: row["business_name"].strip(),
            TARGET_TYPE_ATTR: [{"option": TARGET_TYPE}],
            TARGET_STATUS_ATTR: [{"status": TARGET_STATUS}]}


def existing_entries(client: Client, keys: list[str]) -> dict[str, str]:
    """venue key -> entry id for venues already in the list (read-only
    query, 100 keys per call)."""
    found: dict[str, str] = {}
    for i in range(0, len(keys), 100):
        data = client.request(
            "POST", f"/lists/{LIST_SLUG}/entries/query",
            body={"filter": {MATCH_ATTRIBUTE: {"$in": keys[i:i + 100]}}, "limit": 500},
            allow_404=True)
        if data is None:
            raise AttioError(f"list {LIST_SLUG} not found; run licmon attio-setup")
        for entry in data.get("data") or []:
            entry_id = (entry.get("id") or {}).get("entry_id")
            for value in (entry.get("entry_values") or {}).get(MATCH_ATTRIBUTE) or []:
                if value.get("value") and entry_id:
                    found.setdefault(value["value"], entry_id)
    return found


def _fold(text) -> str:
    return " ".join(str(text or "").split()).casefold()


def find_target(client: Client, name: str) -> str | None:
    """record id of a Target whose name equals `name`, ignoring case and
    extra spaces. Attio's $contains is case-insensitive; exactness is checked
    here."""
    data = client.request(
        "POST", f"/objects/{PARENT_OBJECT}/records/query",
        body={"filter": {TARGET_NAME: {"value": {"$contains": name.strip()}}}, "limit": 50})
    want = _fold(name)
    for rec in (data or {}).get("data") or []:
        for value in (rec.get("values") or {}).get(TARGET_NAME) or []:
            if _fold(value.get("value")) == want:
                record_id = (rec.get("id") or {}).get("record_id")
                if record_id:
                    return record_id
    return None


def check_target_fields(client: Client) -> None:
    """Read-only check, before the first new Target, that the fields and the
    exact option spellings the sync writes still exist in the workspace."""
    if client.request("GET", f"/objects/{PARENT_OBJECT}/attributes/{TARGET_NAME}",
                      allow_404=True) is None:
        raise AttioError(f"attio field {PARENT_OBJECT}.{TARGET_NAME} not found")
    for attr, kind, want in ((TARGET_TYPE_ATTR, "options", TARGET_TYPE),
                             (TARGET_STATUS_ATTR, "statuses", TARGET_STATUS)):
        data = client.request("GET", f"/objects/{PARENT_OBJECT}/attributes/{attr}/{kind}")
        titles = {o.get("title") for o in (data or {}).get("data") or []
                  if not o.get("is_archived")}
        if want not in titles:
            raise AttioError(f"attio option {want} missing on {PARENT_OBJECT}.{attr}")


def ensure_priority_options(client: Client) -> list[str]:
    """Add any PRIORITY_OPTIONS missing from the list's Priority select (the
    live list was made with Hot and A only). Returns the titles added."""
    path = f"/lists/{LIST_SLUG}/attributes/priority/options"
    data = client.request("GET", path)
    have = {o.get("title") for o in (data or {}).get("data") or []
            if isinstance(o, dict) and not o.get("is_archived")}
    added = [title for title in PRIORITY_OPTIONS if title not in have]
    for title in added:
        client.request("POST", path, body={"data": {"title": title}})
    return added


def _is_b(row: dict) -> bool:
    return not row.get("hot") and row.get("priority") == "B"


def sync(client: Client | None, rows: list[dict], *, write: bool,
         cap: int | None = None, min_b: int | None = None) -> dict:
    """Put the day's Hot, A and strong B venues into the License Leads list.

    Returns counts only: candidates, hot, b (B venues added or updated),
    created (new Targets), reused (existing Targets), added (new list
    entries), updated (entries refreshed), skipped (over the daily cap),
    options_added (Priority options made), b_held (B venues held back because
    the B option is missing and this key cannot add it: needs
    list_configuration:read-write), written. Without a client (dry run with
    no key) every venue counts as a new Target."""
    cap = daily_cap() if cap is None else cap
    picks = candidates(rows, min_b)
    counts = {"candidates": len(picks), "hot": sum(1 for r in picks if r.get("hot")),
              "b": 0, "created": 0, "reused": 0, "added": 0, "updated": 0, "skipped": 0,
              "options_added": 0, "b_held": 0, "written": bool(write)}
    if client is None:
        counts["created"] = counts["added"] = min(len(picks), cap)
        counts["skipped"] = len(picks) - counts["added"]
        counts["b"] = sum(1 for r in picks[:cap] if _is_b(r))
        return counts

    entries = existing_entries(client, [r["venue_key"] for r in picks])
    if write and picks:
        # Before the first write. A dry run never changes the list.
        try:
            counts["options_added"] = len(ensure_priority_options(client))
        except AttioError:
            # Hot and A still go; B waits until the option exists.
            counts["b_held"] = sum(1 for r in picks if _is_b(r))
            picks = [r for r in picks if not _is_b(r)]
    targets: dict[str, str | None] = {}  # folded name -> record id, this run
    checked = False
    for row in picks:
        entry_id = entries.get(row["venue_key"])
        if entry_id:
            if write:
                client.request("PATCH", f"/lists/{LIST_SLUG}/entries/{entry_id}",
                               body={"data": {"entry_values": update_values(row)}})
            counts["updated"] += 1
            counts["b"] += _is_b(row)
            continue

        name = row["business_name"].strip()
        folded = _fold(name)
        if folded not in targets:
            targets[folded] = find_target(client, name)
        record_id = targets[folded]
        if record_id:
            counts["reused"] += 1
        else:
            if counts["created"] >= cap:
                counts["skipped"] += 1
                continue
            if not checked:
                check_target_fields(client)
                checked = True
            if write:
                made = client.request("POST", f"/objects/{PARENT_OBJECT}/records",
                                      body={"data": {"values": target_values(row)}})
                record_id = (((made or {}).get("data") or {}).get("id") or {}).get("record_id")
                if not record_id:
                    raise AttioError("attio failed (no record id)")
            # A second venue by the same name reuses this Target.
            targets[folded] = record_id if write else "dry-run"
            counts["created"] += 1

        if write:
            client.request("POST", f"/lists/{LIST_SLUG}/entries", body={"data": {
                "parent_record_id": record_id, "parent_object": PARENT_OBJECT,
                "entry_values": entry_values(row)}})
        counts["added"] += 1
        counts["b"] += _is_b(row)
    return counts


def write_counts(path, counts: dict) -> None:
    """Counts-only hand-off to the Slack step (no lead data)."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(counts, fh)


def read_counts(path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
