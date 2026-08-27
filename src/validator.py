# -*- coding: utf-8 -*-
"""The pre-upload checks from the page feed specification.

Every check must pass before any file is written. A failing run reports the
failure and emits nothing, because a broken feed is worse than a stale one.
"""
from collections import Counter
from urllib.parse import urlsplit

import config as cfg

CANONICAL_ORDER = ["country", "state", "subcategories", "type"]


def _param_names(url):
    q = urlsplit(url).query
    if not q:
        return []
    return [p.split("=", 1)[0].replace("%5B%5D", "").replace("[]", "")
            for p in q.split("&") if p]


def _check(name, passed, detail, threshold):
    return {"check": name, "passed": bool(passed), "detail": detail, "threshold": threshold}


def validate(rows, status_by_url=None, previous_counts=None):
    """rows = [{'url':..,'label':..,'feed':..}, ...] across BOTH feeds.

    Returns (all_passed, [check dicts]). status_by_url is optional; when given,
    any URL whose recorded status is a real non-200 is reported. previous_counts
    is optional, e.g. {"CORE": 3812, "ADVENTURES": 1077} from last month's
    snapshot; when given, a feed whose row count collapsed versus last month
    (a network outage marking every URL dead, for example) fails validation
    instead of silently shipping a near-empty file.
    """
    status_by_url = status_by_url or {}
    results = []
    urls = [r["url"] for r in rows]

    dupes = [u for u, n in Counter(urls).items() if n > 1]
    results.append(_check("Duplicate URLs across both feeds", not dupes,
                          "%d duplicated%s" % (len(dupes), (": " + dupes[0]) if dupes else ""), "0"))

    unlabelled = [r["url"] for r in rows if not r.get("label", "").strip()]
    results.append(_check("Rows with no label", not unlabelled,
                          "%d rows" % len(unlabelled), "0"))

    worst, worst_url = 0, ""
    for r in rows:
        n = len([p for p in r.get("label", "").split(";") if p])
        if n > worst:
            worst, worst_url = n, r["url"]
    results.append(_check("Labels on any single URL", worst <= cfg.MAX_LABELS_PER_URL,
                          "max %d (%s)" % (worst, worst_url.rsplit("/", 1)[-1][:40] if worst_url else "-"),
                          "%d or fewer" % cfg.MAX_LABELS_PER_URL))

    tracked = [u for u in urls if any(t in u for t in cfg.TRACKING_PARAMS)]
    results.append(_check("URLs containing tracking parameters", not tracked,
                          "%d found" % len(tracked), "0"))

    offsite = [u for u in urls if not u.startswith(cfg.REQUIRED_PREFIX)]
    results.append(_check("URLs not on the riparide.com domain", not offsite,
                          "%d found" % len(offsite), "0"))

    bad_order = []
    for u in urls:
        names = _param_names(u)
        if not names:
            continue
        ordered = [n for n in CANONICAL_ORDER if n in names]
        if [n for n in names if n in CANONICAL_ORDER] != ordered or names != sorted(names):
            bad_order.append(u)
    facet_total = sum(1 for u in urls if "?" in u)
    results.append(_check("Facet URLs with parameters out of canonical order", not bad_order,
                          "%d of %d facet URLs bad" % (len(bad_order), facet_total), "0"))

    bad_status = [(u, s) for u, s in status_by_url.items()
                  if u in set(urls) and s not in (0, 200)]
    results.append(_check("Checked URLs in output returning a status other than 200",
                          not bad_status,
                          "%d remaining%s" % (len(bad_status),
                                              (", e.g. %d" % bad_status[0][1]) if bad_status else ""),
                          "0"))

    bad_label_chars = [r["url"] for r in rows
                       if any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_;"
                              for c in r.get("label", ""))]
    results.append(_check("Labels using only A-Z, 0-9, underscore and semicolon",
                          not bad_label_chars, "%d bad" % len(bad_label_chars), "0"))

    bad_sep = [r["url"] for r in rows
               if ";;" in r.get("label", "") or r.get("label", "").startswith(";")
               or r.get("label", "").endswith(";")]
    results.append(_check("No empty label slots or stray semicolons",
                          not bad_sep, "%d bad" % len(bad_sep), "0"))

    if previous_counts:
        counts = Counter(r["feed"] for r in rows)
        collapsed = []
        for feed, prev in previous_counts.items():
            if prev <= 0:
                continue
            now = counts.get(feed, 0)
            if now < prev * cfg.MIN_ROW_RATIO:
                collapsed.append("%s: %d -> %d" % (feed, prev, now))
        results.append(_check("Feed size has not collapsed versus last run", not collapsed,
                              "; ".join(collapsed) if collapsed else "within range of last run",
                              ">= %d%% of last run's row count" % int(cfg.MIN_ROW_RATIO * 100)))
    else:
        results.append(_check("Feed size has not collapsed versus last run", True,
                              "no prior run to compare against", "n/a"))

    return all(c["passed"] for c in results), results


def format_results(results):
    lines = []
    for c in results:
        lines.append("%-4s %-58s %s" % ("PASS" if c["passed"] else "FAIL",
                                        c["check"], c["detail"]))
    return "\n".join(lines)
