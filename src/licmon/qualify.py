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
    chain = next((m for m in (CHAINS.match(n.strip().upper().removeprefix("THE "))
                              for n in (rec.dba, rec.legal_name) if n) if m), None)
    if chain:
        return Qualification(False, 0, None, f"national chain ({chain.group(0).lower()})")
    tier, class_reason = venue_class(names, rec.license_description)
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
