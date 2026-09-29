"""Connector contract. One subclass per official dataset/report."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from ..http import Http
from ..models import MATERIAL_FIELDS, Record, Snapshot


class Source(ABC):
    #: stable machine name, used as the DB key. Never rename once live.
    name: str = ""
    #: human title for logs and exports
    title: str = ""
    #: two-letter state the source covers
    state: str = ""
    #: official landing page for the dataset (provenance)
    homepage: str = ""
    #: True if a record missing from a full snapshot means it left the list
    #: (e.g. a pending list). False for rolling windows (e.g. last 30 days).
    tracks_removals: bool = True
    #: Sanity floor. A successful fetch that parses to fewer records than this
    #: is treated as a failure (protects against an upstream format change
    #: silently marking everything as removed).
    min_records: int = 1
    #: Fields whose change is reported as a material change. Rolling-window
    #: reports that show one action in several formats can narrow this.
    material_fields: tuple[str, ...] = MATERIAL_FIELDS

    def contact(self, raw: dict) -> dict:
        """Contact details the official record itself publishes, from the
        stored raw row. Keys (all optional): "phone", "people" (owner or
        applicant names), "mailing_address". Never looked up elsewhere."""
        return {}

    @abstractmethod
    def fetch(self, http: Http) -> list[Snapshot]:
        """Download raw payload(s). Must not modify bytes."""

    @abstractmethod
    def parse(self, snapshots: list[Snapshot]) -> Iterable[Record]:
        """Turn raw payloads into normalized records (category assigned)."""
