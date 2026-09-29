"""Deterministic lead qualification and scoring.

Rules, not AI, decide. Every decision carries a human-readable reason so the
operator can see why a record is (or is not) in the queue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Record

CATEGORY_POINTS = {
    "nightlife": 50,
    "on_premise": 35,
    "hospitality_mfg": 30,
    "catering_event": 20,
    "hotel": 15,
    # Unmapped license codes (e.g. WA approval privilege numbers): only a
    # hospitality-sounding name plus a meaningful action can qualify these.
    "other": 10,
}
# Categories that disqualify outright (PRD "normally exclude").
EXCLUDED_CATEGORIES = {"off_premise", "wholesale_mfg", "temporary"}

# Application types that signal something new is happening.
APPLICATION_TYPE_POINTS = [
    (re.compile(r"\b(NEW|ORIGINAL|ISSUE)\b"), 20, "new application"),
    (re.compile(r"CHANGE OF LOCATION"), 20, "change of location"),
    (re.compile(r"ASSUMPTION|CHANGE OF OWNER|TRANSFER"), 15, "ownership change"),
    (re.compile(r"EXPANSION|ADDED/CHANGE OF CLASS|CHANGE OF ACTIVITY|ADDED PRIVILEGE"),
     15, "expanded alcohol service"),
    (re.compile(r"TRADENAME|TRADE NAME"), 5, "new trade name"),
]
# Routine actions with no sign of a new venue/concept (PRD exclude).
ROUTINE_APPLICATION_TYPES = re.compile(
    r"RENEW|CHANGE OF CORPORATE OFFICER|DISCONTINU|DISC\. LIQUOR|RESUME BUSINESS")
ROUTINE_STATUSES = re.compile(r"DISCONTINU|SURREND|REVOK|CANCEL|WITHDRAW|DENIED|EXPIRED")

POSITIVE_WORDS = re.compile(
    r"\b(BAR|BARS|LOUNGE|NIGHT ?CLUB|CLUB|TAVERN|PUB|SALOON|COCKTAILS?|ROOFTOP|"
    r"SPEAKEASY|CANTINA|TAPROOM|TAP ROOM|TAP HOUSE|TAPHOUSE|BREWERY|BREWING|BREWPUB|"
    r"BEER GARDEN|BIERGARTEN|BEER HALL|WINE BAR|DISTILLERY|TASTING ROOM|CABARET|"
    r"MUSIC HALL|LIVE MUSIC|DANCE|KARAOKE|HOOKAH|SOCIAL CLUB|ICEHOUSE|ICE HOUSE|"
    r"GASTROPUB|GRILL|KITCHEN|BISTRO|TRATTORIA|OSTERIA|IZAKAYA|STEAKHOUSE|"
    r"SUPPER CLUB|EVENT SPACE|VENUE|BALLROOM|BOWL|ARCADE|COMEDY|THEATER|THEATRE)\b")

EXCLUDE_WORDS = re.compile(
    r"\b(GROCERY|GROCERIES|SUPERMARKET|SUPER MARKET|MARKET|MINI MART|MINIMART|"
    r"FOOD MART|MART|DELI & GROCERY|BODEGA|CONVENIENCE|PHARMACY|DRUG|CVS|WALGREENS?|"
    r"RITE AID|7-ELEVEN|7 ELEVEN|SEVEN ELEVEN|CIRCLE K|QUIKTRIP|BUC-EE'?S|WAWA|"
    r"GAS|FUEL|SHELL|CHEVRON|EXXON|MOBIL|VALERO|ARCO|TEXACO|SUNOCO|CITGO|"
    r"PETRO|TRUCK STOP|TRAVEL CENTER|DOLLAR GENERAL|FAMILY DOLLAR|WALMART|"
    r"WAL-MART|TARGET|COSTCO|SAM'?S CLUB|KROGER|SAFEWAY|ALBERTSONS|VONS|RALPHS|"
    r"H-E-B|HEB|WHOLE FOODS|TRADER JOE'?S|SPROUTS|ALDI|PUBLIX|FOOD LION|"
    r"LIQUOR STORE|LIQUORS|WINE & SPIRITS|WINE AND SPIRITS|BOTTLE SHOP|PACKAGE STORE|"
    r"SMOKE SHOP|TOBACCO|VAPE|DISTRIBUT\w*|WHOLESALE\w*|IMPORT\w*|WAREHOUSE|"
    r"LOGISTICS|AIRPORT|STADIUM|UNIVERSITY|COLLEGE|HOSPITAL|MEDICAL CENTER|"
    r"MILITARY|ARMY|NAVY|AIR FORCE|NAVAL|VETERANS OF FOREIGN WARS|VFW|"
    r"AMERICAN LEGION|CHURCH|PARISH|SCHOOL|HIGH SCHOOL)\b")

TIER_A = 70
TIER_B = 55
QUALIFY_MIN = 40


@dataclass
class Qualification:
    qualified: bool
    score: int
    tier: str | None  # "A", "B", "C" or None
    reason: str


def qualify(rec: Record, metro: str | None) -> Qualification:
    reasons: list[str] = []
    if not metro:
        return Qualification(False, 0, None, "outside target metros")
    if rec.category in EXCLUDED_CATEGORIES:
        return Qualification(False, 0, None, f"excluded license category: {rec.category}")

    app_type = (rec.application_type or "").upper()
    status = (rec.status or "").upper()
    if app_type and ROUTINE_APPLICATION_TYPES.search(app_type):
        return Qualification(False, 0, None, f"routine action: {app_type.lower()}")
    if status and ROUTINE_STATUSES.search(status):
        return Qualification(False, 0, None, f"inactive status: {status.lower()}")

    names = " ".join(x for x in (rec.dba, rec.legal_name) if x).upper()
    bad = EXCLUDE_WORDS.search(names)
    good = POSITIVE_WORDS.search(names)
    if bad and not good:
        return Qualification(False, 0, None, f"non-target business name ({bad.group(0).lower()})")

    score = CATEGORY_POINTS.get(rec.category, 0)
    if rec.category == "other":
        reasons.append("license type not classified"
                       + (f" ({rec.license_description})" if rec.license_description else ""))
    elif score:
        reasons.append(f"{rec.category.replace('_', ' ')} license"
                       + (f" ({rec.license_description})" if rec.license_description else ""))

    matched_type = False
    for pattern, points, label in APPLICATION_TYPE_POINTS:
        if app_type and pattern.search(app_type):
            score += points
            reasons.append(label)
            matched_type = True
            break
    if not matched_type and not app_type:
        # Pending-application lists without a type (e.g. CA export) are
        # applications by definition; give partial credit.
        score += 10
        reasons.append("pending application")

    if good:
        score += 15
        reasons.append(f"name suggests hospitality ({good.group(0).lower()})")
    if bad:
        score -= 20
        reasons.append(f"name also matches exclusion ({bad.group(0).lower()})")

    reasons.insert(0, metro)
    if score < QUALIFY_MIN:
        return Qualification(False, score, None, "; ".join(reasons + ["score below threshold"]))
    tier = "A" if score >= TIER_A else "B" if score >= TIER_B else "C"
    return Qualification(True, score, tier, "; ".join(reasons))
