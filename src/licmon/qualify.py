"""Deterministic lead qualification and scoring.

Rules, not AI, decide. Every decision carries a human-readable reason so the
operator can see why a record is (or is not) in the queue.

The owner sells event ticketing to venues, so the tier is the kind of venue:

  A  nightclub: club / lounge / cabaret / dance names, cabaret licenses
  B  obvious bar or event venue: tavern, pub, taproom, rooftop, karaoke,
     comedy, live music, event center, bar-only licenses (no food required)
  C  everything else that qualifies, mostly restaurants

Coffee shops, bakeries, dessert shops and national chains are dropped.
Licenses alone rarely tell a bar from a restaurant, so the business name
does most of the work.

Two numbers per record. ``score`` is the qualification threshold (unchanged
job: is this a lead at all). ``lead_score`` (0 to 100) ranks leads by
ticketing fit: venue tier, nightlife license, licensing stage, filing type.
``hot`` = tier A with a lead_score of at least HOT_MIN_SCORE (default 75).
Hot is a label on top of A/B/C, not a fourth tier.

Stage and nightlife-license signals come from each source (Source.stage,
Source.nightlife_license in sources/base.py); the points table below is
shared by every state.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from . import stage as stage_mod
from .models import Record

CATEGORY_POINTS = {
    "nightlife": 50,
    "on_premise": 35,
    "hospitality_mfg": 30,
    "catering_event": 20,
    "hotel": 15,  # deliberately low: hotels need a bar/lounge name to qualify
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
    r"\b(BAR|BARS|LOUNGE|NIGHT ?CLUB|COMEDY CLUB|DANCE CLUB|DANCE HALL|TAVERN|PUB|SALOON|COCKTAILS?|ROOFTOP|"
    r"SPEAKEASY|CANTINA|TAPROOM|TAP ROOM|TAP HOUSE|TAPHOUSE|BREWERY|BREWING|BREWPUB|"
    r"BEER GARDEN|BIERGARTEN|BEER HALL|WINE BAR|DISTILLERY|TASTING ROOM|CABARET|"
    r"MUSIC HALL|LIVE MUSIC|KARAOKE|HOOKAH|SOCIAL CLUB|ICEHOUSE|ICE HOUSE|"
    r"GASTROPUB|GRILL|KITCHEN|BISTRO|TRATTORIA|OSTERIA|IZAKAYA|STEAKHOUSE|"
    r"SUPPER CLUB|EVENT SPACE|VENUE|BALLROOM|BOWLING|BOWL|ARCADE|COMEDY)\b")

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

# --- Venue class (decides the tier) ---------------------------------------

# Nightclub names (tier A).
NIGHTCLUB_WORDS = re.compile(
    r"\b(NIGHT ?CLUBS?|NIGHTLIFE|ULTRA ?LOUNGE|LOUNGE|CABARET|DISCO|DISCOTHEQUE|"
    r"DANCE CLUB|DANCE HALL|DANCEHALL|GENTLEMEN'?S CLUB|HOOKAH|AFTER ?HOURS|"
    r"DAY ?CLUB|BEACH CLUB)\b")
# "Lounge" that is not a nightlife lounge.
NOT_NIGHTCLUB = re.compile(
    r"\b(COFFEE|CAFE|TEA|CIGAR|NAIL|HAIR|BEAUTY|LASH|BROW|SPA|AIRPORT|ESPRESSO|"
    r"DESSERT|JUICE|MASSAGE) LOUNGE\b")

# Obvious bars and event venues (tier B).
BAR_VENUE_WORDS = re.compile(
    r"\b(BAR|BARS|TAVERN|PUB|SALOON|COCKTAILS?|ROOFTOP|SPEAKEASY|CANTINA|"
    r"TAPROOM|TAP ROOM|TAP HOUSE|TAPHOUSE|BREWERY|BREWING|BREWPUB|GASTROPUB|"
    r"BEER GARDEN|BIERGARTEN|BEER HALL|WINE BAR|DISTILLERY|ICEHOUSE|ICE HOUSE|"
    r"KARAOKE|LIVE MUSIC|MUSIC HALL|MUSIC VENUE|CONCERTS?|COMEDY|THEATER|THEATRE|"
    r"AMPHITHEATER|EVENT CENTER|EVENT SPACE|EVENT HALL|EVENTS|VENUE|BALLROOM|"
    r"BOWLING|ARCADE|BILLIARDS|POOL HALL|SOCIAL CLUB|SUPPER CLUB|SPORTS BAR|"
    r"ENTERTAINMENT|JAZZ|HONKY ?TONK|WHISKEY|WHISKY|TEQUILA|MEZCAL)\b")
# "Bar" that is really food or a service (sushi bar, bar & grill, nail bar).
FOOD_BAR = re.compile(
    r"\b(SUSHI|OYSTER|RAW|JUICE|SALAD|ESPRESSO|COFFEE|NOODLE|TACO|POKE|RAMEN|"
    r"NAIL|BLOW ?DRY|BROW|LASH|SMOOTHIE|DESSERT|YOGURT|CEREAL|OXYGEN|CANDY|"
    r"MILK|TEA|PHO|DUMPLING|BURGER|WING|SNACK|HOT ?POT|KBBQ|BBQ|GRILL|RESTAURANT|"
    r"KITCHEN|EATERY|CAFE|PIZZA|PIZZERIA|BISTRO|CUISINE|TAQUERIA)S?,? ?(&|AND|\+)? ?BARS?\b"
    r"|\bBARS? ?(&|AND) ?(GRILL|KITCHEN|RESTAURANT|EATERY|BISTRO)\b")

# Venue names that hold amusement licenses without being nightlife.
PPA_NOT_NIGHTLIFE = re.compile(
    r"\b(THEATER|THEATRE|AMPHITHEATER|BOWLING|BOWL|ARCADE|BILLIARDS|POOL HALL|"
    r"CINEMA|MOVIES?|ESCAPE ROOM|TRAMPOLINE|SKATING|GOLF|MUSEUM|BINGO)\b")

# License descriptions that are a nightclub or a bar by definition.
NIGHTCLUB_LICENSES = re.compile(r"\bCABARET\b|NIGHTCLUB|NIGHT CLUB")
BAR_VENUE_LICENSES = re.compile(
    r"PUBLIC PREMISES|MUSIC VENUE|\bTAVERN\b|PUBLIC PLACE OF AMUSEMENT|"
    r"PERFORMING ARTS|BOWLING|CIVIC CENTER|^ON-SALE BEER$",
    re.I)

# Restaurant names: a bar-type license alone does not make these a bar.
RESTAURANT_WORDS = re.compile(
    r"\b(RESTAURANTE?S?|GRILL|KITCHEN|EATERY|BISTRO|STEAK ?HOUSE|SMOKEHOUSE|BBQ|"
    r"BARBECUE|SUSHI|RAMEN|PIZZA|PIZZERIA|TAQUERIA|TACOS?|MARISCOS|CUISINE|DINER|"
    r"TRATTORIA|OSTERIA|IZAKAYA|NOODLES?|BURGERS?|WINGS?|CHICKEN|SEAFOOD|CRAB|"
    r"FOODS?|EMPANADAS?|EMPANADAZO)\b")

# Not a ticketing lead even with an on-premises license.
DROP_WORDS = re.compile(
    r"\b(COFFEE|CAFE|CAF\u00c9|ESPRESSO|BAKERY|BAKE SHOP|BAKESHOP|PATISSERIE|"
    r"PASTRY|PASTRIES|DONUTS?|DOUGHNUTS?|BAGELS?|TEA HOUSE|TEAHOUSE|TEA ROOM|"
    r"BOBA|BUBBLE TEA|JUICE|SMOOTHIES?|CREAMERY|ICE CREAM|GELATO|FROZEN YOGURT|"
    r"FROYO|DESSERTS?|CREPES?|CUPCAKES?|CHOCOLATES?|BREAKFAST|PANCAKES?|WAFFLES?|"
    r"SANDWICH(ES)?|DELI|BUFFET|FOOD TRUCK|DAYCARE|SALON|SPA|NAILS?)\b")
CHAINS = re.compile(
    r"\b(APPLEBEE'?S|CHILI'?S|OLIVE GARDEN|RED LOBSTER|OUTBACK|TEXAS ROADHOUSE|"
    r"CHEESECAKE FACTORY|BJ'?S RESTAURANT|BUFFALO WILD WINGS|HOOTERS|TWIN PEAKS|"
    r"TGI ?FRIDAY'?S|RED ROBIN|DENNY'?S|IHOP|CRACKER BARREL|LONGHORN STEAKHOUSE|"
    r"CHUY'?S|PAPPADEAUX|PAPPASITO'?S|PAPPAS|TORCHY'?S|STARBUCKS|DUNKIN|PANERA|"
    r"CHIPOTLE|TACO BELL|MCDONALD'?S|WHATABURGER|P\.? ?F\.? CHANG'?S|CARRABBA'?S|"
    r"BONEFISH|RUTH'?S CHRIS|MORTON'?S|FOGO DE CHAO|YARD HOUSE|MAGGIANO'?S|"
    r"FIRST WATCH|HOUSE OF PIES|CHUCK E\.? CHEESE|PEI WEI|SHAKE SHACK|"
    r"CAVA|SWEETGREEN|WINGSTOP|PIZZA HUT|DOMINO'?S|PAPA JOHN'?S|CICI'?S)\b")

TIER_BONUS = {"A": 60, "B": 30, "C": 0}
QUALIFY_MIN = 40

# --- Lead score (0 to 100) ---------------------------------------------------

TIER_POINTS = {"A": 45, "B": 25, "C": 5}
#: Keys a Source.nightlife_license() may return -> (points, plain label).
#: The highest one on a record counts.
NIGHTLIFE_LICENSE_POINTS = {
    "ppa": (20, "Public place of amusement (Chicago)"),
    "late_hours": (15, "Late hours (Texas LH, Chicago Late Hour)"),
    "public_premises": (15, "Public premises bar (California type 48)"),
    "music_venue": (15, "Music venue (California type 90)"),
    "nightclub_cabaret": (15, "Night club or cabaret (New York)"),
    "full_liquor_bar": (10, "Full-liquor bar, no restaurant modifier (Florida COP)"),
}
STAGE_POINTS = {stage_mod.LICENSED: 25, stage_mod.APPROVED: 20,
                stage_mod.IN_REVIEW: 10, stage_mod.RECEIVED: 5}
#: (pattern on the upper-cased application type, points, label). First wins.
FILING_POINTS = [
    (re.compile(r"\b(NEW|ORIGINAL|ISSUE)\b|CHANGE OF LOCATION"), 10, "new or new location"),
    (re.compile(r"ASSUMPTION|CHANGE OF OWNER|TRANSFER"), 5, "change of owner"),
]
#: Pending lists without an application type (CA export) are new filings.
BLANK_FILING_POINTS = 10
HOT_MIN_SCORE_DEFAULT = 75


def hot_min_score() -> int:
    """Hot threshold, tunable without a code change (HOT_MIN_SCORE)."""
    try:
        return int(os.environ.get("HOT_MIN_SCORE", "").strip() or HOT_MIN_SCORE_DEFAULT)
    except ValueError:
        return HOT_MIN_SCORE_DEFAULT


def venue_class(names: str, license_description: str | None) -> tuple[str, str]:
    """(tier, reason) from the business names and the license description."""
    lic = (license_description or "").upper()
    club = NIGHTCLUB_WORDS.search(names)
    if club and not NOT_NIGHTCLUB.search(names):
        if DROP_WORDS.search(names):  # "K-Cafe & Lounge": a cafe with a lounge
            return "B", f"lounge name ({club.group(0).lower()})"
        return "A", f"nightclub name ({club.group(0).lower()})"
    lic_club = NIGHTCLUB_LICENSES.search(lic)
    if lic_club:
        return "A", f"nightclub license ({lic_club.group(0).lower()})"
    bar_names = FOOD_BAR.sub(" ", names)
    bar = BAR_VENUE_WORDS.search(bar_names)
    if bar:
        return "B", f"bar or venue name ({bar.group(0).lower()})"
    if RESTAURANT_WORDS.search(names) or DROP_WORDS.search(names):
        return "C", "restaurant or other (no bar or club signal)"
    for part in re.split(r"[,;]", lic):
        lic_bar = BAR_VENUE_LICENSES.search(part.strip())
        if lic_bar:
            return "B", f"bar or venue license ({part.strip().lower()})"
    return "C", "restaurant or other (no bar or club signal)"


@dataclass
class Qualification:
    qualified: bool
    score: int
    tier: str | None  # "A", "B", "C" or None
    reason: str
    stage: str | None = None  # one of stage.STAGES, set for every record
    lead_score: int = 0  # 0 to 100, qualified records only
    hot: bool = False


_REGISTRY: dict | None = None


def _source_for(rec: Record, source):
    """The Source object for a record (None for unknown test sources)."""
    global _REGISTRY
    if source is not None:
        return source
    if _REGISTRY is None:
        from .sources import all_sources

        _REGISTRY = {s.name: s for s in all_sources()}
    return _REGISTRY.get(rec.source)


def lead_score(tier: str, license_keys, stage: str | None, stage_counts: bool,
               application_type: str | None) -> int:
    """The shared 0 to 100 ranking (see the module docstring)."""
    points = TIER_POINTS.get(tier, 0)
    points += max((NIGHTLIFE_LICENSE_POINTS[k][0] for k in license_keys
                   if k in NIGHTLIFE_LICENSE_POINTS), default=0)
    if stage_counts:
        points += STAGE_POINTS.get(stage, 0)
    app_type = (application_type or "").upper()
    if not app_type:
        points += BLANK_FILING_POINTS
    else:
        points += next((pts for pat, pts, _ in FILING_POINTS if pat.search(app_type)), 0)
    return min(points, 100)


def qualify(rec: Record, metro: str | None, source=None,
            today: date | None = None) -> Qualification:
    """Gate, tier, qualification score, then stage and lead score.
    `source` defaults to the registered Source named rec.source."""
    src = _source_for(rec, source)
    license_keys = src.nightlife_license(rec) if src else ()
    q = _qualify(rec, metro, license_keys)
    q.stage = src.stage(rec) if src else stage_mod.from_status(rec.status)
    if q.qualified:
        today = today or datetime.now(timezone.utc).date()
        counts = src.stage_counts(rec, today) if src else True
        q.lead_score = lead_score(q.tier, license_keys, q.stage, counts,
                                  rec.application_type)
        q.hot = q.tier == "A" and q.lead_score >= hot_min_score()
    return q


def _qualify(rec: Record, metro: str | None, license_keys=()) -> Qualification:
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
    chain = next((m for m in (CHAINS.match(n.strip().upper().removeprefix("THE "))
                              for n in (rec.dba, rec.legal_name) if n) if m), None)
    if chain:
        return Qualification(False, 0, None, f"national chain ({chain.group(0).lower()})")
    tier, class_reason = venue_class(names, rec.license_description)
    if (tier == "B" and "ppa" in license_keys
            and BAR_VENUE_WORDS.search(FOOD_BAR.sub(" ", names))
            and not PPA_NOT_NIGHTLIFE.search(names)):
        # A bar or event name holding a public place of amusement license is
        # a nightlife venue. PPA on an unclear name stays B: bowling alleys
        # and theaters hold PPAs too.
        tier, class_reason = "A", class_reason + " with amusement license"
    drop = DROP_WORDS.search(names)
    if drop and tier == "C":
        return Qualification(False, 0, None,
                             f"not a nightlife venue ({drop.group(0).lower()})")

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
    if score < QUALIFY_MIN and tier == "C":
        return Qualification(False, score, None, "; ".join(reasons + ["score below threshold"]))
    if score < QUALIFY_MIN - 15:
        # A/B names still need some license or filing signal.
        return Qualification(False, score, None, "; ".join(reasons + ["score below threshold"]))
    reasons.insert(1, class_reason)
    return Qualification(True, score + TIER_BONUS[tier], tier, "; ".join(reasons))
