# -*- coding: utf-8 -*-
"""Stay type, region and intent for stories, from Riparide's own stories feed.

A story's URL is a headline ("cosy-cubby-in-the-hills") and its page title
carries no "X for Rent" wording, so neither says what kind of stay it is. The
platform's open stories feed does: stories are products there, each with a
category, region and pet_friendly flag. See config.CATALOG_STORIES_PATH.

Rows are keyed by story id in a table of their own, so a story can never pick
up a listing's data just because the two share a number.

Nothing here can fail a run. A fetch error or a header without the columns
below is recorded in the report and the stories keep the labels they had.
"""
import csv
import io
import re

import config as cfg
import fetcher
import labeller

# Accepted spellings for each column, compared after lower-casing and removing
# spaces, underscores and hyphens. The first set mirrors the product fields in
# the API's own JSON sample (product_id, url, category, region, pet_friendly).
ALIASES = {
    "url": ["url", "producturl", "link", "permalink", "storyurl"],
    "id": ["productid", "storyid", "id"],
    "category": ["category", "subcategory", "subcategories", "staytype", "propertytype"],
    "region": ["region", "regionname"],
    "pet_friendly": ["petfriendly", "pets", "petsallowed", "dogfriendly"],
    "amenities": ["amenities", "amenity", "features", "facilities"],
}

TRUE_VALUES = {"true", "1", "yes", "y", "t"}

_STORY_URL_ID = re.compile(r"/stories/(\d+)-")
_LETTERS = re.compile(r"[^a-z]")


def _norm(s):
    return re.sub(r"[\s_\-]", "", (s or "").strip().lower())


def _map_columns(fieldnames):
    normalised = {_norm(f): f for f in (fieldnames or [])}
    found = {}
    for canonical, options in ALIASES.items():
        for opt in options:
            if opt in normalised:
                found[canonical] = normalised[opt]
                break
    return found


def stay_from_category(category):
    """'Tiny house' -> TYPE_TINY_HOUSE. Returns "" for a wording that is in
    neither the facet list nor EXTRA_STAY_WORDINGS, so it can be reported
    rather than guessed, the same rule the title parser follows."""
    want = _LETTERS.sub("", (category or "").lower())
    if not want:
        return ""
    for sub in cfg.SUBCATS:
        if _LETTERS.sub("", sub) == want:
            return "TYPE_" + sub.upper().replace("-", "_")
    for wording, label in cfg.EXTRA_STAY_WORDINGS.items():
        if _LETTERS.sub("", wording) == want:
            return label
    return ""


def _story_id(raw, cols):
    if "url" in cols:
        m = _STORY_URL_ID.search(raw.get(cols["url"]) or "")
        if m:
            return m.group(1)
    if "id" in cols:
        digits = re.sub(r"^\D+", "", (raw.get(cols["id"]) or "").strip())  # "story_774" -> "774"
        if digits.isdigit():
            return digits
    return None


def parse(text, market):
    """Parse one market's stories CSV. Returns (by_id, report)."""
    report = {"market": market, "rows": 0, "usable": 0, "columns": {}, "problems": [],
              "unmapped_categories": {}}
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    cols = _map_columns(reader.fieldnames)
    report["columns"] = cols
    if "url" not in cols and "id" not in cols:
        report["problems"].append("%s: no story url or id column, saw: %s"
                                  % (market, ", ".join(reader.fieldnames or [])))
        return {}, report
    if not ({"category", "pet_friendly", "amenities", "region"} & set(cols)):
        report["problems"].append("%s: no category, region, pet_friendly or amenities column, saw: %s"
                                  % (market, ", ".join(reader.fieldnames or [])))
        return {}, report

    country, state = cfg.CATALOG_MARKET_GEO.get(market, ("", ""))
    by_id = {}
    for raw in reader:
        report["rows"] += 1
        sid = _story_id(raw, cols)
        if not sid:
            continue
        rec = {"country": country, "state": state}

        if "category" in cols:
            category = (raw.get(cols["category"]) or "").strip()
            stay = stay_from_category(category)
            if stay:
                rec["stay"] = stay
            elif category:
                um = report["unmapped_categories"]
                um[category] = um.get(category, 0) + 1

        if "region" in cols:
            rg = (raw.get(cols["region"]) or "").strip()
            if rg:
                rec["region"] = labeller.region_label(labeller.region_slug(rg), country, state)

        ints = []
        if "pet_friendly" in cols and _norm(raw.get(cols["pet_friendly"])) in TRUE_VALUES:
            ints.append("INT_PET_FRIENDLY")
        if "amenities" in cols:
            text_a = (raw.get(cols["amenities"]) or "").lower().replace("-", " ")
            for keyword, label in cfg.INTENT_KEYWORDS:
                if keyword.replace("-", " ") in text_a and label not in ints:
                    ints.append(label)
        if ints:
            rec["intents"] = ints

        by_id[sid] = rec
        report["usable"] += 1
    return by_id, report


def load(log=print):
    """Fetch and parse every configured market. Returns (by_id, report)."""
    by_id = {}
    report = {"markets": [], "rows": 0, "usable": 0, "problems": [], "unmapped_categories": {}}
    for market in cfg.CATALOG_MARKETS:
        url = cfg.BASE + cfg.CATALOG_STORIES_PATH % market
        try:
            text = fetcher.get(url)
        except Exception as e:
            report["problems"].append("%s: could not fetch (%s)" % (market, str(e)[:160]))
            continue
        part, rep = parse(text, market)
        report["markets"].append(market)
        report["rows"] += rep["rows"]
        report["usable"] += rep["usable"]
        report["problems"].extend(rep["problems"])
        for k, v in rep["unmapped_categories"].items():
            report["unmapped_categories"][k] = report["unmapped_categories"].get(k, 0) + v
        by_id.update(part)
        log("stories feed %s: %d rows, %d usable" % (market, rep["rows"], rep["usable"]))
    for p in report["problems"]:
        log("stories feed: %s" % p)
    return by_id, report


def apply(rows, by_id, log=print):
    """Merge the feed into story rows. Returns a summary.

    The feed's category is the platform's own stay type, so it replaces the
    slug guess. Location only fills blanks, because a story's location read
    off its own page is already the platform's. Intents are added into empty
    slots, then the boundary is recomputed so a newly pet-friendly story
    moves to SEARCH_HEAD like any other.
    """
    summary = {"stories": 0, "matched": 0, "stay_set": 0, "intent_added": 0,
               "now_search_head": 0, "stories_without_stay": 0}
    for r in rows:
        if r["page_type"] != "PAGE_STORY":
            continue
        summary["stories"] += 1
        m = _STORY_URL_ID.search(r["url"])
        rec = by_id.get(m.group(1)) if m else None
        if rec:
            summary["matched"] += 1
            if rec.get("stay") and rec["stay"] != r["stay"]:
                r["stay"] = rec["stay"]
                summary["stay_set"] += 1
            for k in ("country", "state", "region"):
                r[k] = r[k] or rec.get(k, "")
            for lab in rec.get("intents", []):
                if lab in (r["intent1"], r["intent2"]):
                    continue
                if not r["intent1"]:
                    r["intent1"] = lab
                elif not r["intent2"]:
                    r["intent2"] = lab
                else:
                    break
                summary["intent_added"] += 1
            before = r["boundary"]
            r["boundary"] = labeller.boundary_for(r)
            if r["boundary"] == "SEARCH_HEAD" and before != "SEARCH_HEAD":
                summary["now_search_head"] += 1
        if not r["stay"]:
            summary["stories_without_stay"] += 1
    log("stories feed: %d of %d stories matched, stay type set on %d, %d intent(s) added, "
        "%d moved to SEARCH_HEAD" % (summary["matched"], summary["stories"], summary["stay_set"],
                                     summary["intent_added"], summary["now_search_head"]))
    return summary
