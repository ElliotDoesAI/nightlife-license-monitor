"""Source registry. Add a connector module, then list it here."""

from __future__ import annotations

from .base import Source


def all_sources() -> list[Source]:
    from .ca_abc import CaAbcSource
    from .chicago_bacp import ChicagoBacpSource
    from .chicago_pending import ChicagoPendingSource
    from .fl_abt import FlAbtSource
    from .ny_sla import NySlaSource
    from .tx_tabc import TxTabcSource
    from .wa_lcb import WaLcbSource

    return [NySlaSource(), TxTabcSource(), ChicagoPendingSource(), ChicagoBacpSource(),
            WaLcbSource(), CaAbcSource(), FlAbtSource()]


def get_sources(names: list[str] | None) -> list[Source]:
    sources = all_sources()
    if not names:
        return sources
    by_name = {s.name: s for s in sources}
    unknown = [n for n in names if n not in by_name]
    if unknown:
        # Do not echo the input: workflow logs are public.
        raise SystemExit(f"unknown source name; known: {', '.join(by_name)}")
    return [by_name[n] for n in names]
