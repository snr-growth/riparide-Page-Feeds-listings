# -*- coding: utf-8 -*-
"""Merge the supplied listing attributes into the labelled rows.

Listing URLs carry no location, so country, state and region for listings,
stories and adventures have to come from a file. The exact column names in
that file are not fixed yet, so a set of common spellings is accepted and the
run reports which columns it actually matched.
"""
import csv
import os
import re

import config as cfg
import labeller

# Accepted spellings for each column we care about, lower-cased and stripped
# of spaces, underscores and hyphens before matching.
ALIASES = {
    "id": ["id", "listingid", "listing", "productid", "pid"],
    "slug": ["slug", "urlslug", "url", "handle", "path"],
    "country": ["country", "countrycode", "geocountry"],
    "state": ["state", "statecode", "region1", "province"],
    "region": ["region", "regionname", "area", "destination", "subregion"],
    "subcategory": ["subcategory", "subcategories", "type", "staytype", "category", "propertytype"],
    "amenities": ["amenities", "amenity", "features", "facilities"],
    "active": ["active", "isactive", "status", "published", "live"],
}

COUNTRY_CODES = {
    "au": "GEO_AU", "aus": "GEO_AU", "australia": "GEO_AU",
    "nz": "GEO_NZ", "newzealand": "GEO_NZ",
    "us": "GEO_US", "usa": "GEO_US", "unitedstates": "GEO_US",
}
STATE_CODES = {
    "vic": "GEO_VIC", "victoria": "GEO_VIC",
    "nsw": "GEO_NSW", "newsouthwales": "GEO_NSW",
    "wa": "GEO_WA", "washington": "GEO_WA",
    "or": "GEO_OR", "oregon": "GEO_OR",
}
INACTIVE = {"0", "false", "no", "inactive", "unpublished", "archived", "delisted"}


def _norm(s):
    return re.sub(r"[\s_\-]", "", (s or "").strip().lower())


def _map_columns(fieldnames):
    """Return {canonical: actual_column_name} for whatever we could match."""
    found = {}
    normalised = {_norm(f): f for f in (fieldnames or [])}
    for canonical, options in ALIASES.items():
        for opt in options:
            if opt in normalised:
                found[canonical] = normalised[opt]
                break
    return found


def load(path=None, log=print):
    """Read the attributes file. Returns (by_id, report).

    Missing file is not an error. The run continues with location blank and
    says so, rather than failing.
    """
    path = path or cfg.ATTRIBUTES_FILE
    report = {"path": path, "present": False, "rows": 0, "columns": {},
              "usable": 0, "inactive": 0, "problems": []}
    if not os.path.exists(path):
        report["problems"].append("file not found, location labels will stay blank")
        return {}, report

    report["present"] = True
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = _map_columns(reader.fieldnames)
        report["columns"] = cols
        if "id" not in cols:
            report["problems"].append(
                "no id column found, saw: %s" % ", ".join(reader.fieldnames or []))
            return {}, report

        by_id = {}
        for raw in reader:
            report["rows"] += 1
            rid = (raw.get(cols["id"]) or "").strip()
            if not rid:
                continue
            rid = rid.split("-")[0].strip()          # tolerate "97-pebble-point"
            if not rid.isdigit():
                continue

            if "active" in cols:
                if _norm(raw.get(cols["active"])) in INACTIVE:
                    report["inactive"] += 1
                    continue

            rec = {}
            if "country" in cols:
                rec["country"] = COUNTRY_CODES.get(_norm(raw.get(cols["country"])), "")
            if "state" in cols:
                rec["state"] = STATE_CODES.get(_norm(raw.get(cols["state"])), "")
            if "region" in cols:
                rg = (raw.get(cols["region"]) or "").strip()
                if rg:
                    slug = re.sub(r"[^a-z0-9]+", "-", rg.lower()).strip("-")
                    rec["region"] = labeller.region_label(slug, rec.get("country", ""),
                                                          rec.get("state", ""))
            if "subcategory" in cols:
                sc = _norm(raw.get(cols["subcategory"])).replace(" ", "")
                for s in cfg.SUBCATS:
                    if _norm(s) == sc:
                        rec["stay"] = "TYPE_" + s.upper().replace("-", "_")
                        break
            if "amenities" in cols:
                text = (raw.get(cols["amenities"]) or "").lower()
                ints = []
                for keyword, label in cfg.INTENT_KEYWORDS:
                    if keyword.replace("-", " ") in text.replace("-", " ") and label not in ints:
                        ints.append(label)
                if ints:
                    rec["intents"] = ints[:2]

            if any(rec.values()):
                by_id[rid] = rec
                report["usable"] += 1

    if not by_id:
        report["problems"].append("file read but no usable rows were produced")
    return by_id, report


def apply(rows, by_id, log=print):
    """Fill location and type on listing rows. Returns a small summary."""
    filled = 0
    listing_rows = 0
    for r in rows:
        if r["page_type"] not in ("PAGE_LISTING", "PAGE_STORY", "PAGE_ADVENTURE"):
            continue
        listing_rows += 1
        rid = labeller.listing_id(r["url"])
        if not rid:
            m = re.search(r"/(?:stories|adventures)/(\d+)-", r["url"])
            rid = m.group(1) if m else None
        rec = by_id.get(rid) if rid else None
        if not rec:
            continue

        before = (r["country"], r["state"], r["region"], r["stay"])
        r["country"] = r["country"] or rec.get("country", "")
        r["state"] = r["state"] or rec.get("state", "")
        r["region"] = r["region"] or rec.get("region", "")
        r["stay"] = r["stay"] or rec.get("stay", "")
        for lab in rec.get("intents", []):
            if lab not in (r["intent1"], r["intent2"]):
                if not r["intent1"]:
                    r["intent1"] = lab
                elif not r["intent2"]:
                    r["intent2"] = lab

        # boundary depends on geo, so recompute once location is known
        if r["page_type"] != "PAGE_ADVENTURE":
            if r["country"] == "GEO_NZ":
                r["boundary"] = "NZ_REVIEW"
            elif r["country"] == "GEO_US":
                r["boundary"] = "US_HOLD"

        if (r["country"], r["state"], r["region"], r["stay"]) != before:
            filled += 1
            r["notes"] = "location from attributes file"

    still_blank = sum(1 for r in rows
                      if r["page_type"] in ("PAGE_LISTING", "PAGE_STORY", "PAGE_ADVENTURE")
                      and not r["country"])
    return {"rows_considered": listing_rows, "rows_filled": filled,
            "still_without_location": still_blank}
