# -*- coding: utf-8 -*-
"""Turn a riparide URL into its six taxonomy dimensions.

Dimensions: page type, geo (country + state), region, stay type, intent,
boundary. Blank dimensions are simply skipped when the label string is built.
"""
import re
import unicodedata

import config as cfg

# Longest first so "treehouse" and "luxury-house" win over "house".
_TYPE_KEYS = sorted(cfg.SUBCATS, key=len, reverse=True)

_LISTING_ID = re.compile(r"/listings/(\d+)-")


def listing_id(url):
    """The numeric id in /listings/{id}-{slug}, or None."""
    m = _LISTING_ID.search(url)
    return m.group(1) if m else None


def slug_of(url):
    return url.rstrip("/").rsplit("/", 1)[-1].lower()


def slugify(text):
    """Lower-case ASCII slug: accents are folded and apostrophes dropped, so
    "Taupo" with a macron gives taupo and "Hawke's Bay" gives hawkes-bay,
    not the taup and hawke-s-bay a plain [^a-z0-9] replace produced."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = re.sub(r"['‘’`]", "", folded)
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def region_slug(name):
    """Slug for a region name read off a listing title or attributes file."""
    slug = slugify(name)
    return cfg.REGION_SLUG_ALIASES.get(slug, slug)


# Stay wordings with a label but no facet page, matched as whole words in a
# slug (plural allowed). Only the multi-word ones: a bare "hotel" or "cave"
# in a slug is as likely to be scenery as the stay type, and the listing
# title (enricher) is the authority for those.
_SLUG_EXTRA_WORDINGS = ("beach house", "train carriage")
_EXTRA_STAY_RES = [
    (re.compile(r"(?<![a-z0-9])%ss?(?![a-z0-9])" % slugify(w)), cfg.EXTRA_STAY_WORDINGS[w])
    for w in _SLUG_EXTRA_WORDINGS
]


def stay_type_from(slug):
    for rx, label in _EXTRA_STAY_RES:
        if rx.search(slug):
            return label
    for k in _TYPE_KEYS:
        if k in slug:
            return "TYPE_" + k.upper().replace("-", "_")
    return ""


def intents_from(slug):
    found = []
    for keyword, label in cfg.INTENT_KEYWORDS:
        if keyword in slug and label not in found:
            found.append(label)
    return found[:2]


def region_label(slug, country="", state=""):
    """Build the REG_ label for a region slug.

    Some slugs exist under more than one state or country, for example
    north-coast is both /au/nsw/north-coast and /us/oregon/north-coast.
    For those the state or country code is appended so the label stays unique.
    """
    base = "REG_" + slug.upper().replace("-", "_")
    if slug in cfg.AMBIGUOUS_REGION_SLUGS:
        code = cfg.REGION_SUFFIX.get(state) or cfg.REGION_SUFFIX_BY_COUNTRY.get(country, "")
        if code:
            base += "_" + code
    return base


def find_region_collisions(rows):
    """Return {label: [urls]} for any REG_ label used by more than one hub.

    Called on every run so a newly added region that clashes is reported
    instead of silently merging two regions into one label.
    """
    from collections import defaultdict
    by_label = defaultdict(list)
    for r in rows:
        if r.get("page_type") == "PAGE_REGION" and r.get("region"):
            by_label[r["region"]].append(r["url"])
    return {k: v for k, v in by_label.items() if len(v) > 1}


def _geo_boundary(country, fallback="PMAX_LONGTAIL"):
    if country == "GEO_NZ":
        return "NZ_REVIEW"
    if country == "GEO_US":
        return "US_HOLD"
    return fallback


def _row(url, page_type, country="", state="", region="", stay="",
         i1="", i2="", boundary="", notes=""):
    return {
        "url": url, "page_type": page_type, "country": country, "state": state,
        "region": region, "stay": stay, "intent1": i1, "intent2": i2,
        "boundary": boundary, "notes": notes,
    }


def label_url(url, group):
    """Classify one URL. `group` is the sitemap it came from."""
    path = url[len(cfg.BASE):].strip("/") if url.startswith(cfg.BASE) else url.strip("/")
    parts = [p for p in path.split("/") if p]
    slug = slug_of(url)

    if group == "core":
        return _row(url, "PAGE_CORE", notes="brand or information page, excluded from both feeds")

    if group == "adventures":
        i1, i2 = (intents_from(slug) + ["", ""])[:2]
        return _row(url, "PAGE_ADVENTURE", i1=i1, i2=i2, boundary="ADV_HOLD",
                    notes="editorial page, held out of asset groups")

    if group in ("listings", "stories"):
        page_type = "PAGE_LISTING" if group == "listings" else "PAGE_STORY"
        stay = stay_type_from(slug)
        ints = intents_from(slug)
        i1, i2 = (ints + ["", ""])[:2]
        boundary = "SEARCH_HEAD" if set(ints) & cfg.SEARCH_HEAD_INTENTS else "PMAX_LONGTAIL"
        return _row(url, page_type, stay=stay, i1=i1, i2=i2, boundary=boundary,
                    notes="location pending attributes file")

    # destinations and collections both live under /{country}[/{state}]/...
    country = cfg.COUNTRY_OF.get(parts[0], "") if parts else ""

    if len(parts) == 1:
        return _row(url, "PAGE_COUNTRY", country, boundary=_geo_boundary(country))

    state = cfg.STATE_OF.get(parts[1], "")

    if len(parts) == 2:
        if state:
            return _row(url, "PAGE_STATE", country, state, boundary=_geo_boundary(country))
        if parts[1] == "collections":
            return _row(url, "PAGE_COLLECTION_HUB", country, boundary=_geo_boundary(country),
                        notes="collection index page")
        region = region_label(parts[1], country, "")
        return _row(url, "PAGE_REGION", country, "", region, boundary=_geo_boundary(country))

    # three or more segments
    if parts[1] == "collections":                       # /{country}/collections/{slug}
        return _collection(url, country, "", parts[2])
    if parts[2] == "collections":
        if len(parts) >= 4:                             # /{country}/{state}/collections/{slug}
            return _collection(url, country, state, parts[3])
        return _row(url, "PAGE_COLLECTION_HUB", country, state,
                    boundary=_geo_boundary(country), notes="collection index page")

    region = region_label(parts[2], country, state)  # /{country}/{state}/{region}
    return _row(url, "PAGE_REGION", country, state, region, boundary=_geo_boundary(country))


def _collection(url, country, state, slug):
    ints = intents_from(slug)
    i1, i2 = (ints + ["", ""])[:2]
    region = cfg.POI_REGION.get(slug, "")
    head = "SEARCH_HEAD" if set(ints) & cfg.SEARCH_HEAD_INTENTS else "PMAX_LONGTAIL"
    notes = "collection landing page"
    if slug in cfg.POI_REGION:
        notes += ", point of interest"
    elif not region and "-" in slug and not ints:
        notes += ", region to confirm"
    return _row(url, "PAGE_COLLECTION", country, state, region, stay_type_from(slug),
                i1, i2, _geo_boundary(country, head), notes)


def build_facet_rows():
    """The stay-type facet URLs. Parameters stay in alphabetical order:
    country, state, subcategories, type. Any other order 301s."""
    rows = []
    for cc, ss, country, state in cfg.FACET_SCOPES:
        for sub in cfg.SUBCATS:
            q = "country=%s&" % cc
            if ss:
                q += "state=%s&" % ss
            q += "subcategories%%5B%%5D=%s&type=accommodation" % sub
            url = "%s/listings?%s" % (cfg.BASE, q)
            stay = "TYPE_" + sub.upper().replace("-", "_")
            head = "SEARCH_HEAD" if stay in cfg.SEARCH_HEAD_TYPES else "PMAX_LONGTAIL"
            rows.append(_row(url, "PAGE_FACET_TYPE", country, state, "", stay,
                             boundary=_geo_boundary(country, head),
                             notes="parameters in canonical alphabetical order"))
    return rows


def _search_url(country_code, state_code, extra=()):
    """A /listings search URL. Parameter names are sorted alphabetically
    (country, petFriendly, regions[], state, type), the only order that does
    not 301. `extra` is a list of (name, value) pairs."""
    params = [("country", country_code), ("type", "accommodation")]
    if state_code:
        params.append(("state", state_code))
    params.extend(extra)
    params.sort(key=lambda kv: kv[0])
    q = "&".join("%s=%s" % (k.replace("[]", "%5B%5D"), v) for k, v in params)
    return "%s/listings?%s" % (cfg.BASE, q)


def build_search_rows(rows):
    """Search-results pages that carry real traffic but have no sitemap entry.

    Three kinds: every stay in a country or state (no stay-type filter),
    pet-friendly stays in each scope, and one per region hub found in `rows`
    (the regions[] search that mirrors the region page). Every URL is
    status-checked each run (run.select_status_check_targets) without
    following redirects, so one that 301s or errors is dropped. A parameter
    the site ignores still returns 200, so the formats here were taken from
    the client's own traffic report, not proven by that check.
    """
    out = []
    for cc, ss, country, state in cfg.FACET_SCOPES:
        out.append(_row(_search_url(cc, ss), "PAGE_SEARCH", country, state,
                        boundary=_geo_boundary(country),
                        notes="all stays search, no stay-type filter"))
        out.append(_row(_search_url(cc, ss, [("petFriendly", "true")]), "PAGE_SEARCH",
                        country, state, i1="INT_PET_FRIENDLY",
                        boundary=_geo_boundary(country, "SEARCH_HEAD"),
                        notes="pet-friendly search"))
    # Pet-friendly searches also arrive with no country or state at all.
    out.append(_row("%s/listings?petFriendly=true&type=accommodation" % cfg.BASE,
                    "PAGE_SEARCH", i1="INT_PET_FRIENDLY", boundary="SEARCH_HEAD",
                    notes="pet-friendly search, no geography"))

    code_of_country = {v: k for k, _s, v, _g in cfg.FACET_SCOPES}
    code_of_state = {g: s for _k, s, _v, g in cfg.FACET_SCOPES if g}
    for r in rows:
        if r.get("page_type") != "PAGE_REGION" or not r.get("region"):
            continue
        cc = code_of_country.get(r["country"])
        if not cc:
            continue
        ss = code_of_state.get(r["state"]) if r["state"] else None
        if r["state"] and not ss:
            continue
        out.append(_row(_search_url(cc, ss, [("regions[]", slug_of(r["url"]))]),
                        "PAGE_SEARCH", r["country"], r["state"], r["region"],
                        boundary=_geo_boundary(r["country"]),
                        notes="region search, mirrors the region page"))
    return out


def feed_of(row):
    if row["page_type"] == "PAGE_CORE":
        return cfg.FEED_EXCLUDE
    if row["page_type"] == "PAGE_ADVENTURE":
        return cfg.FEED_ADVENTURES
    return cfg.FEED_CORE


def label_string(row):
    """Join the dimensions into the semicolon-separated Custom label value."""
    parts = [row["page_type"], row["country"], row["state"], row["region"],
             row["stay"], row["intent1"], row["intent2"], row["boundary"]]
    return ";".join(p for p in parts if p)
