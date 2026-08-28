# -*- coding: utf-8 -*-
"""Read each listing and story page to recover its location.

A listing URL carries no location, but the page title does. Verified on
25 Aug 2026 across listings in three countries:

    Pebble Point - Glamping for Rent in Princetown, Great Ocean Road, VIC, AU
    Hobbit Tree House in Waikino - Cabin for Rent in Waikino, The Coromandel, NZ
    The Hideout - Cabin for Rent in Deming, North Cascades, WA, US
    The Willows - Adventure by Chris in Anglers Rest, High Country, VIC, AU

So country, state, region and stay type can all be read from the page itself
and no external data file is required.

Adventure pages carry no location in the title, which does not matter while
they are held out of the asset groups.

Results are cached by URL, so the first run pays for the whole catalogue and
later runs only fetch pages that are new.
"""
import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import config as cfg
import fetcher
import labeller

CACHE_FILE = os.path.join(cfg.DATA_DIR, "location-cache.json")

# Bumped whenever parse_title changes in a way that could alter a stored
# result. Entries recorded as unmapped under an older parser are re-read.
PARSER_VERSION = 5

# Keyed the same way a title wording is reduced before comparison, so the
# readable form can stay in config where it is easy to check against a page.
_EXTRA_STAY = {re.sub(r"[^a-z]", "", k.lower()): v
               for k, v in cfg.EXTRA_STAY_WORDINGS.items()}

COUNTRY_TOKENS = {"AU": "GEO_AU", "NZ": "GEO_NZ", "US": "GEO_US"}
STATE_TOKENS = {"VIC": "GEO_VIC", "NSW": "GEO_NSW", "WA": "GEO_WA", "OR": "GEO_OR"}

_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
# " - <Stay type> for Rent in " or " - Adventure by <name> in ". The prefix is
# matched greedily so this lands on the LAST " in " in the title. A listing is
# free to have " in " inside its own name, as "Cozy Cabin in Brownsbay" and
# "Karekare Cabin in the Heart of West Coast" do, and matching the first one
# read the listing's own name as the region.
_AFTER_IN = re.compile(r"^.*\s+in\s+(.+?)\s*(?:\|\s*Riparide)?\s*$", re.I)
# A NZ title can carry a postcode of its own, either as its own comma segment
# ("Waiheke Island, 1971, NZ") or trailing the place ("North Cove 0920").
_POSTCODE = re.compile(r"^\d{3,5}$")
_TRAILING_POSTCODE = re.compile(r"\s+\d{3,5}$")


def clean_region(name):
    """Return a usable region name, or "" when the text is not one.

    A region is a place name: a handful of words, no digits and no " in ".
    Anything else means the title was split in the wrong place, and a wrong
    label is worse than a missing one because it silently groups a listing
    with the wrong market.
    """
    name = _TRAILING_POSTCODE.sub("", (name or "").strip()).strip()
    if not name:
        return ""
    if re.search(r"\d", name):
        return ""
    if re.search(r"in", name, re.I):
        return ""
    if len(name.split()) > 5:
        return ""
    return name
# Titles can carry several separators, e.g.
#   "The Hideout - Hot Tub - Pets Ok - Cabin for Rent in ..."
# The stay type is the segment immediately before "for Rent", so the prefix is
# matched greedily to land on the last separator. The separator has to be a
# spaced dash: a stay type can contain a dash of its own, as "A-Frame" does,
# and splitting on any dash left it reading as "Frame".
# The leading separator is optional so a title that is only the stay type
# still parses.
_STAY = re.compile(r"^(?:.*\s[-–]\s)?([A-Za-z'\- ]+?)\s+for\s+Rent\s+in\s", re.I)


def parse_title(title):
    """Pull country, state, region and stay type out of a page title.

    Returns {} when the title does not carry a location.
    """
    if not title:
        return {}
    title = html.unescape(title).replace("\n", " ").strip()
    title = re.sub(r"\s*\|\s*Riparide\s*$", "", title)

    m = _AFTER_IN.search(title)
    if not m:
        return {}
    tail = [p.strip() for p in m.group(1).split(",") if p.strip()]
    if len(tail) < 2:
        return {}

    country = COUNTRY_TOKENS.get(tail[-1].upper(), "")
    if not country:
        return {}

    rest = tail[:-1]
    state = ""
    if rest and rest[-1].upper() in STATE_TOKENS:
        state = STATE_TOKENS[rest[-1].upper()]
        rest = rest[:-1]

    rest = [p for p in rest if not _POSTCODE.match(p)]
    region_name = clean_region(rest[-1]) if rest else ""
    out = {"country": country, "state": state}
    if region_name:
        slug = re.sub(r"[^a-z0-9]+", "-", region_name.lower()).strip("-")
        out["region"] = labeller.region_label(slug, country, state)
        out["region_name"] = region_name

    sm = _STAY.search(title)
    if sm:
        wording = sm.group(1).strip()
        want = re.sub(r"[^a-z]", "", wording.lower())
        for sub in cfg.SUBCATS:
            if re.sub(r"[^a-z]", "", sub) == want:
                out["stay"] = "TYPE_" + sub.upper().replace("-", "_")
                break
        else:
            # Not a facet subcategory. It may still be a stay type the site
            # names in its titles without offering a facet page for it.
            extra = _EXTRA_STAY.get(want)
            if extra:
                out["stay"] = extra
            else:
                # A wording nobody has accounted for yet. Recorded rather
                # than guessed, and reported after the run so it can be
                # added deliberately, or so a parsing fault shows up.
                out["stay_wording_unmapped"] = wording
    return out


def load_cache(path=None):
    path = path or CACHE_FILE
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache, path=None):
    path = path or CACHE_FILE
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=0)
    os.replace(tmp, path)


def fetch_location(url):
    """Fetch one page and return its parsed location, or {} on failure."""
    try:
        body = fetcher.get(url, retries=1)
    except Exception:
        return {}
    m = _TITLE.search(body)
    out = parse_title(m.group(1)) if m else {}
    if out:
        out["parser"] = PARSER_VERSION
    return out


def region_is_stale(loc):
    """True if a cached entry's region_name or saved REG_ label would come
    out differently if the page were parsed again right now.

    Two things are checked, not one: region_name against what clean_region()
    would make of it (catches a stored "North Cove 0920" that clean_region
    can *salvage* to "North Cove" without erroring - the old check only
    fired on outright rejection, so a salvageable dirty value could sit
    forever), and the saved region label against what freshly deriving it
    from region_name would produce right now. That second check matters on
    its own: region_name looking clean is only a proxy for the label being
    right - if the disambiguation rule in labeller.region_label() (or
    cfg.AMBIGUOUS_REGION_SLUGS) ever changes after a page was cached, its
    region_name can still look perfectly clean while the saved label is the
    old one, and checking region_name alone would never notice.
    """
    loc = loc or {}
    rn = loc.get("region_name")
    if not rn:
        return False
    if clean_region(rn) != rn:
        return True
    slug = re.sub(r"[^a-z0-9]+", "-", rn.lower()).strip("-")
    expected = labeller.region_label(slug, loc.get("country", ""), loc.get("state", ""))
    return loc.get("region") != expected


def enrich(rows, limit=None, log=print, cache_path=None):
    """Fill location on listing and story rows.

    Only pages missing from the cache are fetched. Returns a summary.
    """
    cache = load_cache(cache_path)
    targets = [r for r in rows
               if r["page_type"] in ("PAGE_LISTING", "PAGE_STORY") and not r["country"]]

    # A cached entry may have been parsed before a parser fix. Re-read one
    # that recorded an unmapped stay-type wording, or one region_is_stale()
    # flags. Both are cheap, and are the only entries a parser or
    # region-labelling change can alter.
    stale = [u for u, loc in cache.items()
             if ((loc or {}).get("stay_wording_unmapped") or region_is_stale(loc))
             and not (loc or {}).get("parser", 0) >= PARSER_VERSION]
    for u in stale:
        cache.pop(u, None)
    if stale:
        log("re-reading %d page(s) whose stay type or region needs a fresh parse" % len(stale))

    todo = [r["url"] for r in targets if r["url"] not in cache]

    capped = 0
    if limit is not None and len(todo) > limit:
        capped = len(todo) - limit
        todo = todo[:limit]

    if todo:
        log("reading location from %d page(s), %d already cached%s"
            % (len(todo), len(cache), (", %d deferred to next run" % capped) if capped else ""))

        def work(u):
            time.sleep(cfg.REQUEST_DELAY)
            return u, fetch_location(u)

        done = 0
        with ThreadPoolExecutor(max_workers=cfg.STATUS_CHECK_WORKERS) as pool:
            for u, loc in pool.map(work, todo):
                cache[u] = loc
                done += 1
                if done % 250 == 0:
                    log("  read %d/%d" % (done, len(todo)))
        save_cache(cache, cache_path)
    else:
        log("location cache covers every page, nothing to fetch")

    unmapped = {}
    for loc in cache.values():
        w = (loc or {}).get("stay_wording_unmapped")
        if w:
            unmapped[w] = unmapped.get(w, 0) + 1

    applied = 0
    for r in targets:
        loc = cache.get(r["url"])
        if not loc:
            continue
        r["country"] = r["country"] or loc.get("country", "")
        r["state"] = r["state"] or loc.get("state", "")
        r["region"] = r["region"] or loc.get("region", "")
        r["stay"] = r["stay"] or loc.get("stay", "")
        if r["country"] == "GEO_NZ":
            r["boundary"] = "NZ_REVIEW"
        elif r["country"] == "GEO_US":
            r["boundary"] = "US_HOLD"
        r["notes"] = "location read from the page"
        applied += 1

    still = sum(1 for r in rows
                if r["page_type"] in ("PAGE_LISTING", "PAGE_STORY") and not r["country"])
    return {"targets": len(targets), "fetched": len(todo), "applied": applied,
            "deferred": capped, "cached_total": len(cache),
            "still_without_location": still,
            "unmapped_stay_wordings": dict(sorted(unmapped.items(), key=lambda x: -x[1])[:15])}
