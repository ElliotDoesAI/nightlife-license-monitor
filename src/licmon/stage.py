"""Licensing stage: how far along an application is, in one shared vocabulary.

Every source words its status differently. Each Source maps its own wording
with ``Source.stage(rec)`` (see sources/base.py); ``from_status`` below is the
shared fallback for wording a source does not map itself. Stages, most
advanced first:

  Licensed   issued or active
  Approved   approved or conditional, not yet active
  In review  past intake, in process
  Received   just filed

None means no live stage (withdrawn, denied, discontinued, unknown).
"""

from __future__ import annotations

import re

LICENSED = "Licensed"
APPROVED = "Approved"
IN_REVIEW = "In review"
RECEIVED = "Received"

#: Most advanced first.
STAGES = (LICENSED, APPROVED, IN_REVIEW, RECEIVED)
_RANK = {s: len(STAGES) - i for i, s in enumerate(STAGES)}

_INACTIVE = re.compile(
    r"DISCONTINU|SURREND|SUREND|REVOK|CANCEL|WITHDRAW|DENIED|EXPIRED|NULL AND VOID|"
    r"SUSPEND|DELINQUENT|RELINQUISH|DECEASED|CLOSED|DELETED")
# Checked in this order; first hit wins.
_PATTERNS = (
    (re.compile(r"CONDITIONAL|APPROV"), APPROVED),
    (re.compile(r"\bACTIVE\b|\bCURRENT\b|ISSUED|\bLICENSED\b|TEMPORARY CERTIFICATE"),
     LICENSED),
    (re.compile(r"REVIEW|IN PROCESS|APPLICANT|ESCROW|NOTICE|PENDING"), IN_REVIEW),
    (re.compile(r"RECEIVED|INTAKE|APPLICATION|\bPEND\b|FILED"), RECEIVED),
)


def rank(stage: str | None) -> int:
    """Higher is further along; 0 for no stage."""
    return _RANK.get(stage or "", 0)


def best(stages) -> str | None:
    """The most advanced of several stages (None if none)."""
    found = [s for s in stages if rank(s)]
    return max(found, key=rank) if found else None


def from_status(status: str | None) -> str | None:
    """Shared fallback: map free status text to a stage. Comma-separated
    statuses (one per license type) give the most advanced stage."""
    parts = [p.strip().upper() for p in re.split(r"[,;]", status or "") if p.strip()]
    stages = []
    for part in parts:
        if _INACTIVE.search(part):
            continue
        stages.append(next((s for pat, s in _PATTERNS if pat.search(part)), None))
    return best(stages)
