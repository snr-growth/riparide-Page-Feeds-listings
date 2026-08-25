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
PARSER_VERSION = 2

COUNTRY_TOKENS = {"AU": "GEO_AU", "NZ": "GEO_NZ", "US": "GEO_US"}
STATE_TOKENS = {"VIC": "GEO_VIC", "NSW": "GEO_NSW", "WA": "GEO_WA", "OR": "GEO_OR"}

_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
# " - <Stay type> for Rent in " or " - Adventure by <name> in "
_AFTER_IN = re.compile(r"\s+in\s+(.+?)\s*(?:\|\s*Riparide)?\s*$", re.I)
# Titles can contain several " - " separators, e.g.
#   "The Hideout - Hot Tub - Pets Ok - Cabin for Rent in ..."
# The stay type is the segment immediately before "for Rent", so the prefix
# is matched greedily to land on the LAST separator, and the captured group
# may not itself contain a dash.
_STAY = re.compile(r".*[-–]\s*([A-Za-z' ]+?)\s+for\s+Rent\s+in\s", re.I)


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

    region_name = rest[-1] if rest else ""
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
            # The title uses a wording that is not in the live subcategory
            # list. Recorded rather than guessed, and reported after the run
            # so the mapping can be added deliberately.
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


def enrich(rows, limit=None, log=print, cache_path=None):
    """Fill location on listing and story rows.

    Only pages missing from the cache are fetched. Returns a summary.
    """
    cache = load_cache(cache_path)
    targets = [r for r in rows
               if r["page_type"] in ("PAGE_LISTING", "PAGE_STORY") and not r["country"]]

    # A cached entry that recorded an unmapped stay-type wording may have been
    # parsed before a parser fix. Those are cheap to re-read and are the only
    # entries a parser change can alter, so they are refreshed once.
    stale = [u for u, loc in cache.items()
             if (loc or {}).get("stay_wording_unmapped")
             and not (loc or {}).get("parser", 0) >= PARSER_VERSION]
    for u in stale:
        cache.pop(u, None)
    if stale:
        log("re-reading %d page(s) whose stay type was recorded as unmapped" % len(stale))

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
