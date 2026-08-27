# -*- coding: utf-8 -*-
"""Fetch and parse the riparide sitemaps, and status-check URLs.

Client choice matters here and was settled by testing, not preference.
From one Railway container (egress 52.8.185.56) on 25 Aug 2026, all sending
the same browser user agent:

    urllib  (standard library)  -> 200 OK
    requests library            -> 403 Forbidden
    curl in that container      -> 403 Forbidden

The site's protection layer fingerprints the client, not just the user agent,
so this module deliberately uses only the standard library. That also leaves
the project with no third-party dependencies at all.
"""
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import config as cfg

SM_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

ROBOTS_URL = cfg.BASE + "/robots.txt"
ADSBOT_AGENTS = {"adsbot-google", "adsbot-google-mobile"}


class FetchError(Exception):
    pass


def _request(url, method="GET"):
    return urllib.request.Request(url, headers=dict(cfg.HEADERS), method=method)


def get(url, retries=None):
    """GET a URL and return its text. Raises FetchError after all retries."""
    tries = cfg.REQUEST_RETRIES if retries is None else retries
    last = None
    for attempt in range(tries + 1):
        try:
            with urllib.request.urlopen(_request(url), timeout=cfg.REQUEST_TIMEOUT) as r:
                if r.status == 200:
                    charset = r.headers.get_content_charset() or "utf-8"
                    return r.read().decode(charset, "replace")
                last = "HTTP %d" % r.status
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
        except Exception as e:
            last = type(e).__name__ + ": " + str(e)[:120]
        if attempt < tries:
            time.sleep(1.5 * (attempt + 1))
    raise FetchError("%s -> %s" % (url, last))


def parse_sitemap(xml_text):
    """Return the list of <loc> values in a sitemap or sitemap index."""
    root = ET.fromstring(xml_text.strip())
    locs = [e.text.strip() for e in root.iter(SM_NS + "loc") if e.text and e.text.strip()]
    if not locs:  # tolerate a sitemap served without the namespace
        locs = [e.text.strip() for e in root.iter("loc") if e.text and e.text.strip()]
    return locs


def fetch_all_urls(log=print):
    """Fetch the sitemap index and every child sitemap.

    Returns (urls_by_group, child_sitemap_urls).
    """
    index_xml = get(cfg.SITEMAP_INDEX)
    children = parse_sitemap(index_xml)
    if not children:
        raise FetchError("sitemap index contained no child sitemaps")
    log("sitemap index: %d child sitemaps" % len(children))

    by_group = {}
    for child in children:
        name = child.rsplit("/", 1)[-1].replace("sitemap-", "").replace(".xml", "")
        urls = parse_sitemap(get(child))
        seen, clean = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                clean.append(u)
        by_group[name] = clean
        log("  %-14s %5d urls" % (name, len(clean)))
    return by_group, children


def _status(url):
    """HEAD the URL and return its status code, or 0 if the request failed.

    Redirects are not followed: a page feed URL that redirects is a problem in
    its own right, so the redirect status is reported rather than hidden.
    """
    for attempt in range(cfg.REQUEST_RETRIES + 1):
        try:
            opener = urllib.request.build_opener(_NoRedirect)
            with opener.open(_request(url, "HEAD"), timeout=cfg.REQUEST_TIMEOUT) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:
            if attempt < cfg.REQUEST_RETRIES:
                time.sleep(1.0 * (attempt + 1))
    return 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_robots(text):
    """Parse robots.txt into groups: [{'agents': {ua, ...}, 'rules': [(kind, path), ...]}].

    A run of consecutive `User-agent:` lines shares the rule block that
    follows it, per the standard robots.txt grouping convention. Wildcards
    (`*`, `$`) inside a path are not expanded; matching below is a plain
    prefix check, which is conservative (it can only over-report a block,
    never miss one caused by a plain path prefix).
    """
    groups = []
    current = {"agents": [], "rules": []}

    def flush():
        if current["agents"]:
            groups.append({"agents": {a.lower() for a in current["agents"]},
                            "rules": list(current["rules"])})

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if current["rules"]:
                flush()
                current = {"agents": [], "rules": []}
            current["agents"].append(value)
        elif field in ("disallow", "allow"):
            current["rules"].append((field, value))
    flush()
    return groups


def check_adsbot_access(paths, log=print):
    """Check whether robots.txt blocks AdsBot-Google / AdsBot-Google-Mobile
    from any of the given path prefixes.

    Per Google Ads' documented AdsBot behaviour, AdsBot-Google and
    AdsBot-Google-Mobile do not fall back to a bare `User-agent: *` group —
    only a group naming one of them explicitly applies. Re-verify this against
    Google's current help documentation if it is ever load-bearing for a
    disapproval investigation; this check is a QA nicety, not proof.

    Never raises: a network hiccup fetching robots.txt should not fail an
    otherwise good monthly run. Returns a report dict instead.
    """
    report = {"fetched": False, "adsbot_group_found": False, "blocked": [], "note": ""}
    try:
        text = get(ROBOTS_URL, retries=1)
    except Exception as e:
        report["note"] = "could not fetch robots.txt: %s" % e
        log("robots.txt: " + report["note"])
        return report

    report["fetched"] = True
    groups = parse_robots(text)
    adsbot_groups = [g for g in groups if g["agents"] & ADSBOT_AGENTS]

    if not adsbot_groups:
        report["note"] = ("no AdsBot-specific group found; AdsBot does not follow the "
                          "generic User-agent: * block, so it is not blocked")
        log("robots.txt: " + report["note"])
        return report

    report["adsbot_group_found"] = True
    disallowed = [value for g in adsbot_groups for kind, value in g["rules"]
                  if kind == "disallow" and value]

    for p in paths:
        for d in disallowed:
            if d == "/" or p.startswith(d):
                report["blocked"].append((p, d))
                break

    if report["blocked"]:
        log("robots.txt: WARNING, AdsBot appears blocked: %s" %
            ", ".join("%s by Disallow: %s" % (p, d) for p, d in report["blocked"]))
    else:
        log("robots.txt: AdsBot-Google / AdsBot-Google-Mobile not blocked for %d checked path(s)"
            % len(paths))
    return report


def status_check(urls, log=print):
    """Status-check a list of URLs. Returns {url: status_code}.

    0 means the request could not be completed after retries. Callers must
    treat 0 as unknown, never as dead.
    """
    urls = list(urls)
    if not urls:
        return {}
    results = {}

    def work(u):
        time.sleep(cfg.REQUEST_DELAY)
        return u, _status(u)

    done = 0
    with ThreadPoolExecutor(max_workers=cfg.STATUS_CHECK_WORKERS) as pool:
        for u, code in pool.map(work, urls):
            results[u] = code
            done += 1
            if done % 250 == 0:
                log("  status-checked %d/%d" % (done, len(urls)))
    return results
