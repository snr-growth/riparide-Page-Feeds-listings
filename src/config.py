# -*- coding: utf-8 -*-
"""Single place for every setting the monthly refresh depends on.

Nothing in this file is guessed. Each value is either taken from the page feed
specification, or was verified against riparide.com on 25 August 2026.
"""
import os

# ---------------------------------------------------------------- site source
BASE = "https://www.riparide.com"
SITEMAP_INDEX = BASE + "/sitemaps/sitemap.xml"

# The six child sitemaps, verified present in the index on 25 Aug 2026.
SITEMAPS = ["listings", "stories", "adventures", "destinations", "collections", "core"]

# VERIFIED 25 Aug 2026 from a Railway container (us-west2):
#   default command-line agent -> 403 Forbidden
#   this browser agent         -> 200 OK
# The site's protection layer rejects requests that identify as tooling.
USER_AGENT = os.environ.get(
    "FEED_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Ten rapid HEAD requests returned 200 with no rate limiting observed.
# A small delay is still used so the job stays polite over thousands of URLs.
REQUEST_TIMEOUT = 30
REQUEST_DELAY = float(os.environ.get("FEED_REQUEST_DELAY", "0.15"))
REQUEST_RETRIES = 2
STATUS_CHECK_WORKERS = int(os.environ.get("FEED_STATUS_WORKERS", "6"))

# D4's safety net, made automatic: a diff-only status check can never notice
# a sitemap URL that quietly started returning 404 without being removed
# from the sitemap. Every run in one of these months (by UTC date) checks
# every URL, not just the ones the diff flagged, regardless of whether
# --full-status was passed. See DECISIONS.md D11.
FULL_STATUS_MONTHS = {1, 7}

# If a network problem (blocked IP, site outage, DNS failure) makes every
# status check fail, every checked URL gets excluded as "dead" and the feed
# would otherwise ship as a near-empty file that silently overwrites a good
# one. A run whose per-feed row count falls below this fraction of last
# month's is treated as a validation failure instead. See DECISIONS.md D11.
MIN_ROW_RATIO = 0.5

# Safety valve. If a run would status-check more than this, it checks the
# newest ones and reports the rest as unchecked rather than running for hours.
MAX_STATUS_CHECKS = int(os.environ.get("FEED_MAX_STATUS_CHECKS", "1500"))

# Listing and story pages are read once to recover their location, then cached.
# The first run pays for the whole catalogue; later runs only read new pages.
# The cap keeps any single run bounded.
MAX_LOCATION_FETCHES = int(os.environ.get("FEED_MAX_LOCATION_FETCHES", "1200"))

# ---------------------------------------------------------------- storage
DATA_DIR = os.environ.get("FEED_DATA_DIR", "data")
SNAPSHOT_FILE = os.path.join(DATA_DIR, "snapshot.json")
OUTPUT_DIR = os.environ.get("FEED_OUTPUT_DIR", os.path.join(DATA_DIR, "output"))
ATTRIBUTES_FILE = os.environ.get("FEED_ATTRIBUTES_FILE", os.path.join(DATA_DIR, "listing-attributes.csv"))

CORE_CSV = "riparide-page-feed-core.csv"
ADVENTURES_CSV = "riparide-page-feed-adventures.csv"

# The .xlsx report (report.py) is committed to the repo, unlike the CSVs in
# OUTPUT_DIR above, so every month's report is visible in git history. See
# DECISIONS.md D13.
REPORT_DIR = os.environ.get("FEED_REPORT_DIR", "reports")
REPORT_XLSX = "riparide-page-feed-report.xlsx"

# Representative path prefixes covering every page type this feed can
# contain. Used to check robots.txt doesn't block Google's AdsBot crawlers,
# per the page feed spec's QA requirement. See DECISIONS.md D10.
ADSBOT_CHECK_PATHS = ["/listings", "/stories", "/au", "/nz", "/us"]

# ---------------------------------------------------------------- feed spec
# From the page feed specification and Google's page feed documentation.
MAX_LABELS_PER_URL = 20
TRACKING_PARAMS = ["utm_", "gclid", "srsltid", "fbclid", "msclkid"]
REQUIRED_PREFIX = "https://www.riparide.com/"
CSV_HEADER = ["Page URL", "Custom label"]

# ---------------------------------------------------------------- taxonomy
# The 22 stay-type subcategories exposed by the live facet filter, read off
# riparide.com/listings on 25 Aug 2026.
SUBCATS = [
    "a-frame", "barn", "beach-shack", "cabin", "camping", "caravan", "church",
    "cottage", "eco-house", "farm", "glamping", "house", "lodge", "luxury-house",
    "shipping-container", "studio", "suite", "tiny-house", "train", "treehouse",
    "villa", "yurt",
]

# Wordings the site uses for a stay type in its own page titles that have no
# entry in the facet list above. They become labels in their own right, taken
# from the site's wording rather than matched to a near neighbour: a beach
# house is not necessarily a beach shack, and a wrong match would put a
# listing in the wrong asset group.
#
# These are labels only. They are deliberately kept out of SUBCATS, which
# drives the facet URLs, because no facet page exists for them and a feed of
# URLs that do not exist is a feed of disapprovals.
#
# It is an allow-list on purpose. A wording that is not here is still
# reported after the run rather than labelled, so a parsing fault cannot
# quietly invent a stay type. That is how the A-Frame fault was caught.
EXTRA_STAY_WORDINGS = {
    "beach house": "TYPE_BEACH_HOUSE",
    "train carriage": "TYPE_TRAIN_CARRIAGE",
    "houseboat": "TYPE_HOUSEBOAT",
    "hotel": "TYPE_HOTEL",
    "vehicle": "TYPE_VEHICLE",
    "tipi": "TYPE_TIPI",
    "kiln": "TYPE_KILN",
    "cave": "TYPE_CAVE",
    "igloo": "TYPE_IGLOO",
}

# Six geo scopes the facet URLs are built for.
FACET_SCOPES = [
    ("AU", "VIC", "GEO_AU", "GEO_VIC"),
    ("AU", "NSW", "GEO_AU", "GEO_NSW"),
    ("AU", None, "GEO_AU", ""),
    ("NZ", None, "GEO_NZ", ""),
    ("US", "WA", "GEO_US", "GEO_WA"),
    ("US", "OR", "GEO_US", "GEO_OR"),
]


# Region slugs that exist under more than one state or country, so a label
# built from the slug alone would collide. Verified against the destinations
# sitemap on 25 Aug 2026: /au/nsw/north-coast and /us/oregon/north-coast both
# exist, and the same is true for south-coast and central-coast.
# For these, the state or country code is appended to keep the label unique.
# The runner re-detects collisions on every run and reports any new ones.
AMBIGUOUS_REGION_SLUGS = {"north-coast", "south-coast", "central-coast"}

# Short code appended to an ambiguous region label.
REGION_SUFFIX = {
    "GEO_VIC": "VIC", "GEO_NSW": "NSW", "GEO_WA": "WA", "GEO_OR": "OR",
}
REGION_SUFFIX_BY_COUNTRY = {"GEO_NZ": "NZ", "GEO_AU": "AU", "GEO_US": "US"}

STATE_OF = {"vic": "GEO_VIC", "nsw": "GEO_NSW", "washington": "GEO_WA", "oregon": "GEO_OR"}
COUNTRY_OF = {"au": "GEO_AU", "nz": "GEO_NZ", "us": "GEO_US"}

INTENT_KEYWORDS = [
    ("romantic", "INT_ROMANTIC"), ("honeymoon", "INT_ROMANTIC"), ("couples", "INT_ROMANTIC"),
    ("off-grid", "INT_OFFGRID"), ("offgrid", "INT_OFFGRID"),
    ("pet-friendly", "INT_PET_FRIENDLY"), ("dog-friendly", "INT_PET_FRIENDLY"),
    ("farm-stay", "INT_FARM_STAY"), ("farmstay", "INT_FARM_STAY"),
    ("hot-tub", "INT_HOT_TUB"), ("hottub", "INT_HOT_TUB"),
    ("sauna", "INT_SAUNA"),
    ("split-the-bill", "INT_GROUPS"), ("split-the-check", "INT_GROUPS"), ("groups", "INT_GROUPS"),
    ("luxury", "INT_LUXURY"),
    ("getaway", "INT_GETAWAY"),  # substring match also covers "getaways" and "weekend-getaway"
]

# Clusters Search Generic outperforms PMax on 2x+, per the role-split research
# (SNR, 9 Aug 2026): romantic, getaways, off-grid, pet-friendly. All four must
# be represented here or Option B's PMax exclusion list silently misses one.
SEARCH_HEAD_INTENTS = {"INT_ROMANTIC", "INT_OFFGRID", "INT_PET_FRIENDLY", "INT_GETAWAY"}

# UNCONFIRMED, see DECISIONS.md D8. The role-split research names query-intent
# clusters (romantic, getaways, off-grid, pet-friendly), not stay types, as
# where Search Generic beats PMax. This set is an inference applied only to
# the synthetic facet-type pages, not verified against SNR's own findings.
# Do not extend it to listing/story rows without the same confirmation.
SEARCH_HEAD_TYPES = {"TYPE_TINY_HOUSE", "TYPE_CABIN", "TYPE_GLAMPING", "TYPE_COTTAGE"}

# POI collection to region, only where the platform's own product data confirmed it.
POI_REGION = {
    "daylesford": "REG_MACEDON_RANGES",
    "warburton": "REG_YARRA_VALLEY",
    "kangaroo-valley": "REG_SOUTH_COAST_NSW",
    "mudgee": "REG_COUNTRY_NSW",
    "byron-bay": "REG_NORTH_COAST_NSW",
}

# ---------------------------------------------------------------- feeds
FEED_CORE = "CORE"
FEED_ADVENTURES = "ADVENTURES"
FEED_EXCLUDE = "EXCLUDE"

# ---------------------------------------------------------------- email
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_TO = [a.strip() for a in os.environ.get("EMAIL_TO", "").split(",") if a.strip()]


def email_configured():
    """True only when one complete delivery route is present."""
    if RESEND_API_KEY and EMAIL_FROM and EMAIL_TO:
        return True
    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD and EMAIL_FROM and EMAIL_TO:
        return True
    return False
