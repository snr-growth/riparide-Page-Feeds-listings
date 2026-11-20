# -*- coding: utf-8 -*-
"""Daily Meta catalogue feeds whose `link` points at a riparide.com search.

Riparide's four Meta catalogue feeds (listings/stories x VIC/NSW) link each
item to its own page. This job rebuilds them with `link` (and
`applink.ios_url`, which always equals it) replaced by a search-results page
that matches the item - region, stay type and pet-friendliness - and that
shows at least MIN_RESULTS stays. Everything else in every row is copied
unchanged, so the client points Meta Commerce Manager at our URL instead of
theirs and nothing else changes.

Where the facts come from (none of it is in the feeds themselves):
  * region and stay type: the labels the monthly PMax run already writes to
    the core page feed CSV (REG_*, TYPE_*), joined by listing/story id;
  * which region label is which site slug: that same CSV's region-hub rows
    (/au/<state>/<slug>, exactly three path segments);
  * pet-friendly: harvested from the site's own petFriendly=true searches,
    plus stories whose custom_label_4 contains "Pet", plus INT_PET_FRIENDLY;
  * result counts: fetched live, every run (fetcher.search_totals).

Landing ladder, first rung with >= MIN_RESULTS results wins (an unknown count
never wins):
  pet-friendly: region+type+pet, region+pet, region+type, region, state+pet, state
  other:        region+type, region, state+type, state
Type rungs need a stay type that is a site filter (config.SUBCATS); region
rungs need a known hub slug. Items newer than the monthly PMax labels are
labelled from their own page title (cached); only those whose page can't be
read or parsed go to their state search.
If no rung qualifies the state search is still used when its count is known;
if even that is unknown the original link is kept.

A feed that fails to fetch or validate keeps its previous good file. The
build fails as a whole (exit 1) only if the core CSV is missing or every
feed failed. Pet-friendly rungs are off unless META_PET=on (client decision,
19 Nov 2026); when on, pet harvesting failing never fails anything.

CLI:
  python src/meta_feed.py [--out DIR] [--core CSV] [--offline-feeds DIR]
                          [--counts-json FILE] [--skip-pet | --pet]
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402
import enricher  # noqa: E402
import fetcher  # noqa: E402
import labeller  # noqa: E402

# --- constants (env-overridable) -------------------------------------------

# Pages newer than the monthly PMax labels are read directly (their page title
# names region and stay type) so they get a specific search on day one. Each
# is read once and cached until the monthly run labels it.
PAGE_CACHE_JSON = "meta-new-pages-cache.json"
MAX_PAGE_FETCHES = int(os.environ.get("META_MAX_PAGE_FETCHES") or 300)
PAGE_DELAY = float(os.environ.get("META_PAGE_DELAY") or 0.5)

MIN_RESULTS = int(os.environ.get("META_MIN_RESULTS") or 6)
SOURCE_URL = os.environ.get(
    "META_SOURCE_URL", cfg.BASE + "/public_api/{kind}.csv?market={market}")
OUT_SUBDIR = "meta"
REPORT_JSON = "meta-feed-report.json"
# A feed where more than this share of rows had to keep their original link
# is treated as broken (the site most likely failed to answer the count
# searches) and the previous good file is kept instead.
MAX_ORIGINAL_RATIO = float(os.environ.get("META_MAX_ORIGINAL_RATIO") or 0.5)
PET_DELAY = float(os.environ.get("META_PET_DELAY") or 1.0)
# Pet-friendly landing pages are OFF: the client chose to skip them (19 Nov
# 2026). With pet off, no item is treated as pet-friendly at all and no pet
# searches are fetched. META_PET=on brings the pet rungs and harvest back.
PET_ENABLED = (os.environ.get("META_PET") or "off").strip().lower() in ("1", "on", "true", "yes")

# (output file, feed kind, market)
FEEDS = [
    ("meta-listings-vic.csv", "listings", "VIC"),
    ("meta-listings-nsw.csv", "listings", "NSW"),
    ("meta-stories-vic.csv", "stories", "VIC"),
    ("meta-stories-nsw.csv", "stories", "NSW"),
]
# One file with all four feeds (client request, 20 Nov 2026), built from the
# four finished files so a part that failed today is the last good version
# of that part. Market goes in custom_label_2 so product sets can still be
# split by VIC/NSW: the location column is not reliable for that (some
# stories say "Victoria" or a region name).
COMBINED_CSV = "meta-all.csv"
MARKET_COL = "custom_label_2"
OUTPUT_FILES = [f for f, _, _ in FEEDS] + [COMBINED_CSV, REPORT_JSON]

LINK_COLS = ("link", "applink.ios_url")
SEARCH_PREFIX = cfg.BASE + "/listings?"
ID_PREFIX = {"listing": "listings", "story": "stories"}

PET_RUNGS = ["region+type+pet", "region+pet", "region+type", "region", "state+pet", "state"]
PLAIN_RUNGS = ["region+type", "region", "state+type", "state"]


def default_out_dir():
    return os.path.join(cfg.OUTPUT_DIR, OUT_SUBDIR)


def default_core_csv():
    return os.path.join(cfg.OUTPUT_DIR, cfg.CORE_CSV)


# --- PMax label join --------------------------------------------------------

_PAGE_ID = re.compile(r"^/(listings|stories)/(\d+)(?:-|$)")


def page_key(url):
    """('listings', '106') for .../listings/106-slug, else None."""
    m = _PAGE_ID.match(urlparse(url).path)
    return (m.group(1), m.group(2)) if m else None


def feed_key(item_id):
    """('listings', '106') for listing_106, ('stories', '47') for story_47."""
    kind, _, num = (item_id or "").strip().partition("_")
    if kind in ID_PREFIX and num.isdigit():
        return (ID_PREFIX[kind], num)
    return None


def hub_slug(url):
    """(STATE, slug) for an AU region hub /au/<state>/<slug>, else None.
    Landmarks (/au/vic/grampians/venus-baths) have four segments and return
    None: their slugs are not search regions and give 0 results."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) == 3 and parts[0] == "au":
        return parts[1].upper(), parts[2]
    return None


def load_labels(core_csv):
    """Read the PMax core CSV. Returns (labels, hubs):
    labels {('listings','106'): set of labels}, hubs {(STATE, REG_X): slug}."""
    labels, hubs = {}, {}
    with open(core_csv, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            url = row.get("Page URL") or ""
            labs = set(x for x in (row.get("Custom label") or "").split(";") if x)
            key = page_key(url)
            if key:
                labels[key] = labs
            if "PAGE_REGION" in labs:
                hub = hub_slug(url)
                regs = [x for x in labs if x.startswith("REG_")]
                if hub and len(regs) == 1:
                    hubs[(hub[0], regs[0])] = hub[1]
    return labels, hubs


# --- per-item attributes and the ladder ------------------------------------

# Platform collection names in custom_label_4, e.g. "Pet Friendly Escapes"
# (all 193 pet stories on 18 Nov 2026). Word match, so "Carpet" never counts.
_PET_COLLECTION = re.compile(r"\bPet\b")


def stay_type(labs):
    """Site subcategory slug for the item's TYPE_ label, or None when it is
    not one of the site's filters (TYPE_BEACH_HOUSE, TYPE_HOTEL...)."""
    for lab in sorted(labs):
        if lab.startswith("TYPE_"):
            sub = lab[5:].lower().replace("_", "-")
            if sub in cfg.SUBCATS:
                return sub
    return None


def item_state(labs, market):
    for lab in labs:
        if lab.startswith("GEO_") and lab[4:] in ("VIC", "NSW", "QLD", "SA", "WA", "TAS", "NT", "ACT"):
            return lab[4:]
    return market


def region_slug(labs, state, hubs):
    for lab in sorted(labs):
        if lab.startswith("REG_") and (state, lab) in hubs:
            return hubs[(state, lab)]
    return None


def search_url(state, region=None, sub=None, pet=False):
    extra = []
    if region:
        extra.append(("regions[]", region))
    if sub:
        extra.append(("subcategories[]", sub))
    if pet:
        extra.append(("petFriendly", "true"))
    return labeller._search_url("AU", state, extra)


def candidates(state, region, sub, pet, joined=True):
    """Ordered [(rung, url)] for one item."""
    if not joined:
        return [("state", search_url(state))]
    out = []
    for rung in (PET_RUNGS if pet else PLAIN_RUNGS):
        parts = rung.split("+")
        if "region" in parts and not region:
            continue
        if "type" in parts and not sub:
            continue
        out.append((rung, search_url(
            state,
            region if "region" in parts else None,
            sub if "type" in parts else None,
            "pet" in parts)))
    return out


def choose(cands, counts, min_results):
    """(rung, url) of the first candidate with a count >= min_results; the
    state search as a last resort when its count is known; else (None, None)."""
    for rung, url in cands:
        n = counts.get(url)
        if n is not None and n >= min_results:
            return rung, url
    for rung, url in cands:
        if rung == "state" and counts.get(url) is not None:
            return "state (below min)", url
    return None, None


# --- pet-friendly harvesting -------------------------------------------------
#
# Verified live 18 Nov 2026 from the Railway container: a /listings page
# embeds its first 24 results only, and none of page=2, after=<cursor>,
# cursor=<cursor> or offset=24 returns the next 24 (page= is ignored, the
# others return no results). So the ids are collected by splitting the
# petFriendly=true search finer instead: state, then every region hub, then
# every region hub x site subcategory where the region has more than one
# page. Every id found is pet-friendly; a search is "complete" when its
# totalCount is no more than the ids it showed.

_RESULT = re.compile(r'"result"\s*:\s*\{\s*"__typename"\s*:\s*"(Listing|Story)"\s*,\s*"id"\s*:\s*"(\d+)"')
_FEATURED_LISTING = re.compile(
    r'"featuredListing"\s*:\s*\{\s*(?:"__typename"\s*:\s*"Listing"\s*,\s*)?"id"\s*:\s*"(\d+)"')


def parse_results(html):
    """Search results embedded in a /listings page, in order:
    [{'type': 'Listing'|'Story', 'id': '1817', 'listing_id': '4262' or None}].
    A stay with a story shows as its Story card, whose node embeds the stay
    as "featuredListing":{"__typename":"Listing","id":"4262",...}."""
    html = html or ""
    starts = list(_RESULT.finditer(html))
    out = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(html)
        listing_id = None
        if m.group(1) == "Story":
            lm = _FEATURED_LISTING.search(html, m.end(), end)
            listing_id = lm.group(1) if lm else None
        elif m.group(1) == "Listing":
            listing_id = m.group(2)
        out.append({"type": m.group(1), "id": m.group(2), "listing_id": listing_id})
    return out


def harvest_pet(regions, fetch=fetcher.get, log=print, sleep=time.sleep):
    """Pet-friendly ids per state from the site's petFriendly=true searches.

    `regions` is {state: [hub slug, ...]}. Returns {state: {'listings': set,
    'stories': set, 'stays': int, 'total': int|None, 'searches': int,
    'complete_searches': int, 'error': str|None, 'counts': {url: total}}}
    where 'stays' is the number of distinct result cards found and 'total'
    the state's pet total; 'counts' lets the ladder skip re-fetching. Never
    raises: an error stops that state's harvest and keeps what was found.
    """
    out = {}
    for state, slugs in sorted(regions.items()):
        found = {"listings": set(), "stories": set(), "stays": 0, "total": None,
                 "searches": 0, "complete_searches": 0, "error": None, "counts": {}}
        out[state] = found
        cards = set()

        def one(url):
            if found["searches"]:
                sleep(PET_DELAY)
            html = fetch(url)
            found["searches"] += 1
            total = fetcher.parse_search_total(html)
            found["counts"][url] = total
            results = parse_results(html)
            for r in results:
                cards.add((r["type"], r["id"]))
                (found["stories"] if r["type"] == "Story" else found["listings"]).add(r["id"])
                if r["listing_id"]:
                    found["listings"].add(r["listing_id"])
            complete = total is not None and total <= len(results)
            found["complete_searches"] += complete
            return total, complete

        try:
            found["total"], done = one(search_url(state, pet=True))
            for slug in ([] if done else sorted(slugs)):
                total, done = one(search_url(state, slug, pet=True))
                if done or not total:
                    continue
                for sub in cfg.SUBCATS:
                    one(search_url(state, slug, sub, pet=True))
        except Exception as e:  # never fail the feed over pet
            found["error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
            log("  pet %s: harvesting stopped, continuing with what was found: %s"
                % (state, found["error"]))
        found["stays"] = len(cards)
        log("  pet %s: %d of %s pet-friendly stays identified (%d searches, %d complete)" % (
            state, found["stays"], found["total"], found["searches"], found["complete_searches"]))
    return out

# --- pages newer than the PMax labels -------------------------------------

def read_page(url, fetch=fetcher.get):
    """Location and stay type from a listing or story page's own title, the
    same parser the monthly run uses (enricher.parse_title). A story page also
    names its featured listing. Returns a dict ({} when the title carries
    nothing usable), or None when the page could not be fetched, so it is
    tried again next run."""
    try:
        body = fetch(url)
    except Exception:
        return None
    m = enricher._TITLE.search(body or "")
    out = enricher.parse_title(m.group(1)) if m else {}
    out = {k: v for k, v in out.items() if k in ("country", "state", "region", "stay")}
    if "/stories/" in url:
        lid = enricher.featured_listing_id(body or "")
        if lid:
            out["listing_id"] = lid
    return out


def labels_from_page(kind, loc, labels, page_locs):
    """The label set the PMax run would give this page, from its own title.
    A story takes its featured listing's stay type (the site's own category)
    and fills a missing region or state from it, like enricher.link_stories."""
    loc = dict(loc or {})
    if kind == "stories" and loc.get("listing_id"):
        key = ("listings", loc["listing_id"])
        listing = labels.get(key)
        if listing is None and key in page_locs:
            listing = labels_from_page("listings", page_locs[key], labels, page_locs)
        listing = listing or set()
        stay = [x for x in listing if x.startswith("TYPE_")]
        if stay:
            loc["stay"] = stay[0]
        for prefix, field in (("REG_", "region"), ("GEO_", "state")):
            if not loc.get(field):
                vals = [x for x in listing if x.startswith(prefix) and (
                    field != "state" or x[4:] in ("VIC", "NSW", "QLD", "SA", "WA", "TAS", "NT", "ACT"))]
                if vals:
                    loc[field] = vals[0]
    labs = set(v for k, v in loc.items() if k in ("country", "state", "region", "stay") and v)
    return labs


def label_new_pages(inputs, labels, out_dir, fetch, log):
    """{key: label set} for feed items missing from the PMax labels, read from
    their own pages (cached in out_dir). Returns (page_labels, report)."""
    cache_path = os.path.join(out_dir, PAGE_CACHE_JSON)
    try:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    wanted = {}
    for name, (header, rows) in inputs.items():
        i_id, i_link = header.index("id"), header.index("link")
        for r in rows:
            key = feed_key(r[i_id])
            if key and key not in labels:
                wanted[key] = r[i_link]
    rep = {"not_in_labels": len(wanted), "read_this_run": 0, "from_cache": 0,
           "unreadable": 0, "labelled": 0}
    page_locs = {}
    for key, link in sorted(wanted.items()):
        ck = "%s/%s" % key
        if ck in cache:
            page_locs[key] = cache[ck]
            rep["from_cache"] += 1
            continue
        if rep["read_this_run"] >= MAX_PAGE_FETCHES:
            continue
        if rep["read_this_run"]:
            time.sleep(PAGE_DELAY)
        loc = read_page(link, fetch)
        rep["read_this_run"] += 1
        if loc is None:
            rep["unreadable"] += 1
            continue
        page_locs[key] = cache[ck] = loc
    # Stories need their featured listing, which may itself be new and not in
    # any feed: read it too (once, cached) so the story gets its stay type.
    for key, loc in list(page_locs.items()):
        lid = loc.get("listing_id")
        lkey = ("listings", lid) if lid else None
        if not lkey or lkey in labels or lkey in page_locs:
            continue
        ck = "listings/%s" % lid
        if ck not in cache and rep["read_this_run"] < MAX_PAGE_FETCHES:
            time.sleep(PAGE_DELAY)
            got = read_page("%s/listings/%s" % (cfg.BASE, lid), fetch)
            rep["read_this_run"] += 1
            if got is not None:
                cache[ck] = got
        if ck in cache:
            page_locs[lkey] = cache[ck]
    page_labels = {}
    for key in wanted:
        if key in page_locs:
            labs = labels_from_page(key[0], page_locs[key], labels, page_locs)
            if labs:
                page_labels[key] = labs
                rep["labelled"] += 1
    keep = {"%s/%s" % k for k in wanted} | {"listings/%s" % (page_locs[k] or {}).get("listing_id")
                                            for k in page_locs if (page_locs[k] or {}).get("listing_id")}
    try:
        write_atomic(cache_path, json.dumps({k: v for k, v in cache.items() if k in keep}, indent=0))
    except Exception as e:
        log("meta: could not save the new-pages cache: %s" % e)
    log("meta: %d item(s) not yet in the PMax labels: %d labelled from their own page "
        "(%d read now, %d cached, %d unreadable)" % (rep["not_in_labels"], rep["labelled"],
                                                     rep["read_this_run"], rep["from_cache"],
                                                     rep["unreadable"]))
    return page_labels, rep


# --- CSV in/out and validation ---------------------------------------------

def parse_feed(text):
    """(header, rows) with rows as lists, the BOM stripped."""
    if text.startswith("﻿"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None)
    if not header:
        raise ValueError("empty feed")
    rows = [r for r in reader if r]
    for r in rows:
        if len(r) != len(header):
            raise ValueError("row with %d fields, header has %d" % (len(r), len(header)))
    return header, rows


def to_csv(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def validate(header, in_rows, out_rows):
    """Raise ValueError unless out_rows is in_rows with only link columns
    changed, and every link is the original or a state-scoped search."""
    if len(in_rows) != len(out_rows):
        raise ValueError("row count %d != input %d" % (len(out_rows), len(in_rows)))
    idx = {c: header.index(c) for c in ("id",) + LINK_COLS}
    keep = [i for i, c in enumerate(header) if c not in LINK_COLS]
    for a, b in zip(in_rows, out_rows):
        if a[idx["id"]] != b[idx["id"]]:
            raise ValueError("id mismatch %s != %s" % (b[idx["id"]], a[idx["id"]]))
        if any(a[i] != b[i] for i in keep):
            raise ValueError("non-link column changed for %s" % a[idx["id"]])
        link = b[idx["link"]]
        if b[idx["applink.ios_url"]] != link:
            raise ValueError("applink.ios_url != link for %s" % a[idx["id"]])
        if link != a[idx["link"]] and not (link.startswith(SEARCH_PREFIX) and "state=" in link):
            raise ValueError("bad link for %s: %s" % (a[idx["id"]], link))


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


# --- build -----------------------------------------------------------------

def build(out_dir=None, log=print, core_csv=None, fetch=fetcher.get,
          totals=fetcher.search_totals, skip_pet=None, min_results=None):
    """Rebuild the four Meta feeds, and the combined one, into out_dir. Returns the report dict
    (also written to out_dir/meta-feed-report.json); report['ok'] is False
    when the core CSV is missing or every feed failed."""
    out_dir = out_dir or default_out_dir()
    core_csv = core_csv or default_core_csv()
    min_results = MIN_RESULTS if min_results is None else min_results
    skip_pet = (not PET_ENABLED) if skip_pet is None else skip_pet
    os.makedirs(out_dir, exist_ok=True)
    report = {"built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "min_results": min_results, "core_csv": core_csv, "ok": False,
              "error": None, "feeds": {}, "pet": {"enabled": not skip_pet}}

    if not os.path.exists(core_csv):
        report["error"] = "core CSV missing: %s" % core_csv
        log("meta: " + report["error"])
        _write_report(out_dir, report)
        return report
    labels, hubs = load_labels(core_csv)
    log("meta: %d labelled pages, %d region hubs" % (len(labels), len(hubs)))

    # 1. fetch and parse the four input feeds
    inputs = {}
    for name, kind, market in FEEDS:
        url = SOURCE_URL.format(kind=kind, market=market)
        try:
            header, rows = parse_feed(fetch(url))
            for c in ("id",) + LINK_COLS:
                if c not in header:
                    raise ValueError("no %s column" % c)
            inputs[name] = (header, rows)
            log("meta: %s %d rows" % (name, len(rows)))
        except Exception as e:
            report["feeds"][name] = {"status": "failed", "error": "fetch: %s: %s" % (type(e).__name__, str(e)[:200]),
                                     "kept_previous": os.path.exists(os.path.join(out_dir, name))}
            log("meta: %s fetch failed: %s" % (name, report["feeds"][name]["error"]))

    # 2. pet-friendly ids
    pet = {"listings": set(), "stories": set()}
    known_counts = {}
    if not skip_pet and inputs:
        markets = sorted({m for n, _, m in FEEDS if n in inputs})
        regions = {m: sorted(s for (st, _), s in hubs.items() if st == m) for m in markets}
        harvested = harvest_pet(regions, fetch=fetch, log=log)
        for st, h in harvested.items():
            pet["listings"] |= h["listings"]
            pet["stories"] |= h["stories"]
            known_counts.update((u, n) for u, n in h["counts"].items() if n is not None)
            report["pet"][st] = {
                "stays_identified": h["stays"], "site_pet_total": h["total"],
                "coverage": round(h["stays"] / h["total"], 3) if h["total"] else None,
                "searches": h["searches"], "complete_searches": h["complete_searches"],
                "error": h["error"]}

    # 2b. items newer than the PMax labels: label them from their own page
    page_labels, report["new_pages"] = label_new_pages(inputs, labels, out_dir, fetch, log)

    # 3. work out every item's candidates, count all searches once
    plans = {}
    for name, (header, rows) in inputs.items():
        kind = dict((n, k) for n, k, _ in FEEDS)[name]
        market = dict((n, m) for n, _, m in FEEDS)[name]
        i_id = header.index("id")
        i_cl4 = header.index("custom_label_4") if "custom_label_4" in header else None
        plan = []
        for r in rows:
            key = feed_key(r[i_id])
            labs = (labels.get(key) or page_labels.get(key)) if key else None
            joined = bool(labs)
            labs = labs or set()
            state = item_state(labs, market)
            num = key[1] if key else None
            is_pet = not skip_pet and bool(
                (num and num in pet[kind])
                or "INT_PET_FRIENDLY" in labs
                or (kind == "stories" and i_cl4 is not None and _PET_COLLECTION.search(r[i_cl4])))
            from_page = bool(key) and key not in labels and joined
            plan.append((joined, is_pet, candidates(
                state, region_slug(labs, state, hubs), stay_type(labs), is_pet, joined), from_page))
        plans[name] = plan

    urls = sorted({u for plan in plans.values() for _, _, cands, _ in plan for _, u in cands})
    to_count = [u for u in urls if u not in known_counts]
    log("meta: counting %d searches (%d already counted while harvesting pet)"
        % (len(to_count), len(urls) - len(to_count)))
    counts = dict(known_counts)
    counts.update(totals(to_count, log) if to_count else {})
    report["searches_counted"] = len(urls)
    report["unknown_counts"] = sum(1 for u in urls if counts.get(u) is None)

    # 4. choose, validate, write
    for name, (header, rows) in inputs.items():
        i_link = header.index("link")
        i_app = header.index("applink.ios_url")
        rungs, kept, unjoined, pets, from_page = Counter(), 0, 0, 0, 0
        out_rows = []
        for r, (joined, is_pet, cands, fp) in zip(rows, plans[name]):
            unjoined += not joined
            from_page += fp
            pets += is_pet
            rung, url = choose(cands, counts, min_results)
            new = list(r)
            if url is None:
                kept += 1
                rungs["original link"] += 1
                new[i_app] = new[i_link]
            else:
                rungs[rung] += 1
                new[i_link] = new[i_app] = url
            out_rows.append(new)
        info = {"rows": len(rows), "rungs": dict(rungs.most_common()), "unjoined": unjoined,
                "labelled_from_page": from_page, "original_link_kept": kept, "pet_identified": pets}
        path = os.path.join(out_dir, name)
        try:
            if not rows:
                raise ValueError("input feed has no rows")
            validate(header, rows, out_rows)
            if kept / len(rows) > MAX_ORIGINAL_RATIO:
                raise ValueError("%d of %d rows kept their original link (counts unknown)" % (kept, len(rows)))
            write_atomic(path, to_csv(header, out_rows))
            info["status"] = "ok"
            log("meta: %s written, %s" % (name, info["rungs"]))
        except Exception as e:
            info.update(status="failed", error="validate: %s" % e, kept_previous=os.path.exists(path))
            log("meta: %s NOT written (%s), previous file %s" % (
                name, e, "kept" if info["kept_previous"] else "absent"))
        report["feeds"][name] = info

    ok_feeds = [n for n, i in report["feeds"].items() if i.get("status") == "ok"]
    report["combined"] = combine(out_dir, report["feeds"], log)
    report["ok"] = bool(ok_feeds) and report["combined"]["status"] == "ok"
    if not ok_feeds:
        report["error"] = "every feed failed"
    elif report["combined"]["status"] != "ok":
        report["error"] = "combined feed: " + report["combined"]["error"]
    _write_report(out_dir, report)
    return report


def combine(out_dir, feeds, log=print):
    """Write COMBINED_CSV from the four files on disk (today's, or the
    previous one where today's failed), adding the market in MARKET_COL.
    All four parts must exist and ids must be unique, otherwise the previous
    combined file is kept: a part missing from the file would delete its
    items from the Meta catalogue."""
    path = os.path.join(out_dir, COMBINED_CSV)
    info = {"rows": 0, "parts": {}, "markets": {}}
    try:
        header, rows, seen = None, [], set()
        for name, _, market in FEEDS:
            part = os.path.join(out_dir, name)
            if not os.path.exists(part):
                raise ValueError("%s has never been built" % name)
            with open(part, encoding="utf-8", newline="") as f:
                h, part_rows = parse_feed(f.read())
            if MARKET_COL in h:
                raise ValueError("%s already has a %s column" % (name, MARKET_COL))
            if header is None:
                header = list(h)
            for c in h:
                if c not in header:
                    header.append(c)
            i_id = h.index("id")
            for r in part_rows:
                if r[i_id] in seen:
                    raise ValueError("duplicate id %s (in %s)" % (r[i_id], name))
                seen.add(r[i_id])
                rec = dict(zip(h, r))
                rec[MARKET_COL] = market
                rows.append(rec)
            info["parts"][name] = {"rows": len(part_rows),
                                   "today": (feeds.get(name) or {}).get("status") == "ok"}
            info["markets"][market] = info["markets"].get(market, 0) + len(part_rows)
        # market label sits next to the other custom labels
        at = header.index("custom_label_1") + 1 if "custom_label_1" in header else len(header)
        header.insert(at, MARKET_COL)
        write_atomic(path, to_csv(header, [[rec.get(c, "") for c in header] for rec in rows]))
        info.update(status="ok", rows=len(rows))
        log("meta: %s written, %d rows %s" % (COMBINED_CSV, len(rows), info["markets"]))
    except Exception as e:
        info.update(status="failed", error=str(e), kept_previous=os.path.exists(path))
        log("meta: %s NOT written (%s), previous file %s" % (
            COMBINED_CSV, e, "kept" if info["kept_previous"] else "absent"))
    return info


def _write_report(out_dir, report):
    os.makedirs(out_dir, exist_ok=True)
    write_atomic(os.path.join(out_dir, REPORT_JSON), json.dumps(report, indent=2, sort_keys=True))


# --- CLI -------------------------------------------------------------------

def offline_fetch(folder):
    """A fetch() that serves <kind>_<MARKET>.csv from a folder for the feed
    URLs, and raises for anything else (so pet harvesting is skipped)."""
    def fetch(url):
        m = re.search(r"/public_api/(\w+)\.csv\?market=(\w+)", url)
        if not m:
            raise fetcher.FetchError("offline: %s" % url)
        with open(os.path.join(folder, "%s_%s.csv" % (m.group(1), m.group(2))), encoding="utf-8") as f:
            return f.read()
    return fetch


def counts_from_json(path):
    """A totals() backed by a saved {url: {"code", "total", ...}} file."""
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)

    def totals(urls, log=print):
        out = {}
        for u in urls:
            s = saved.get(u)
            out[u] = s.get("total") if isinstance(s, dict) and s.get("code") == 200 else None
        return out
    return totals


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="output folder (default <FEED_OUTPUT_DIR>/meta)")
    ap.add_argument("--core", help="PMax core page feed CSV (default the monthly run's)")
    ap.add_argument("--offline-feeds", help="read the 4 input feeds from <kind>_<MARKET>.csv here")
    ap.add_argument("--counts-json", help="take result counts from this saved file, no fetching")
    ap.add_argument("--skip-pet", action="store_true", help="no pet-friendly rungs (the default unless META_PET=on)")
    ap.add_argument("--pet", action="store_true", help="use pet-friendly rungs and harvest pet stays")
    a = ap.parse_args(argv)
    kw = {}
    if a.offline_feeds:
        kw["fetch"] = offline_fetch(a.offline_feeds)
    if a.counts_json:
        kw["totals"] = counts_from_json(a.counts_json)
    skip_pet = True if a.skip_pet else (False if a.pet else None)
    report = build(out_dir=a.out, core_csv=a.core, skip_pet=skip_pet, **kw)
    summary = {n: {k: i.get(k) for k in ("status", "rows", "rungs", "error")}
               for n, i in report["feeds"].items()}
    if "combined" in report:
        summary[COMBINED_CSV] = {k: report["combined"].get(k) for k in ("status", "rows", "markets", "error")}
    print(json.dumps(summary, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
