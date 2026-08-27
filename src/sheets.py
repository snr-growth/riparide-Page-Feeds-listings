# -*- coding: utf-8 -*-
"""Write the Core and Adventures feeds into a client-owned Google Sheet.

This is the Google-Ads-facing machine format (see DECISIONS.md D14). The two
CSVs and the .xlsx report (writer.py, report.py) remain the client-shared
format for email/backup/manual reference — this module doesn't replace them,
it's a third, independent delivery path writing the same `out_rows` data.

Auth: a service account JSON key (GOOGLE_SERVICE_ACCOUNT_JSON) signs its own
short-lived JWT and exchanges it for an access token directly against
Google's OAuth2 token endpoint (the standard "OAuth 2.0 for Server to Server
Applications" flow) - no Google API client library, no `requests`, no
`httplib2`. Every actual Sheets API call is a plain urllib REST call, the
same pattern fetcher.py and emailer.py already use for riparide.com and
Resend. `google-auth` (and the `cryptography` it requires) is the one
network-adjacent dependency this needs, used ONLY for RSA-signing the JWT -
it never talks to riparide.com, so it carries none of the risk DECISIONS.md
D3/D7 documented for the fetching layer. See DECISIONS.md D14 for the
research this design is based on, in particular: Google Ads' Google Sheets
connection only ever reads the FIRST sheet/tab of a spreadsheet, which is
why _ensure_tabs() actively pins the Core tab to index 0 on every run.

This module's own write access (the service account) is entirely separate
from whichever human Google account later connects this same spreadsheet
inside Google Ads - that connection authenticates as that person, with
their own Editor access, not through anything this module does.
"""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from google.auth.crypt import RSASigner

import config as cfg

TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
RETRIES = 2
RETRYABLE_HTTP_CODES = (429, 500, 502, 503, 504)


class SheetsError(Exception):
    pass


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_jwt(info):
    """Build and sign the JWT assertion for the service-account grant."""
    signer = RSASigner.from_service_account_info(info)
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    if info.get("private_key_id"):
        header["kid"] = info["private_key_id"]
    claims = {
        "iss": info["client_email"],
        "scope": SCOPE,
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = _b64url(json.dumps(header).encode("utf-8")) + "." + \
        _b64url(json.dumps(claims).encode("utf-8"))
    signature = signer.sign(signing_input.encode("ascii"))
    return signing_input + "." + _b64url(signature)


def _urlopen(req, timeout=30):
    """Thin wrapper so tests can substitute the transport without touching
    the network. Never used directly outside this module."""
    return urllib.request.urlopen(req, timeout=timeout)


def _get_access_token(info):
    assertion = _sign_jwt(info)
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with _urlopen(req) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SheetsError("token exchange failed: HTTP %d: %s"
                          % (e.code, e.read().decode("utf-8", "replace")[:300]))
    return payload["access_token"]


def _call(method, url, token, body=None):
    """One Sheets API call, with retry on transient errors. Raises
    SheetsError with a readable message on final failure."""
    data = json.dumps(body).encode("utf-8") if body is not None else b"{}"
    headers = {"Authorization": "Bearer %s" % token, "Content-Type": "application/json"}
    last = None
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            with _urlopen(req) as r:
                raw = r.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            last = "HTTP %d: %s" % (e.code, detail)
            if e.code in RETRYABLE_HTTP_CODES and attempt < RETRIES:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise SheetsError(last)
        except SheetsError:
            raise
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
            if attempt < RETRIES:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise SheetsError(last)
    raise SheetsError(last)


def _quote(range_a1):
    return urllib.parse.quote(range_a1, safe="")


def _get_sheet_properties(spreadsheet_id, token):
    url = "%s/%s?fields=sheets.properties" % (SHEETS_API, spreadsheet_id)
    data = _call("GET", url, token)
    return [s["properties"] for s in data.get("sheets", [])]


def _ensure_tabs(spreadsheet_id, token, tab_names):
    """Create any of tab_names that don't exist yet, then pin tab_names[0]
    to index 0. Safe to call every run: a no-op when nothing needs to change.
    """
    existing = _get_sheet_properties(spreadsheet_id, token)
    by_title = {p["title"]: p for p in existing}

    additions = [{"addSheet": {"properties": {"title": name}}}
                 for name in tab_names if name not in by_title]
    if additions:
        result = _call("POST", "%s/%s:batchUpdate" % (SHEETS_API, spreadsheet_id), token,
                        {"requests": additions})
        for reply in result.get("replies", []):
            props = reply.get("addSheet", {}).get("properties")
            if props:
                by_title[props["title"]] = props

    core_sheet_id = by_title[tab_names[0]]["sheetId"]
    _call("POST", "%s/%s:batchUpdate" % (SHEETS_API, spreadsheet_id), token, {
        "requests": [{"updateSheetProperties": {
            "properties": {"sheetId": core_sheet_id, "index": 0},
            "fields": "index",
        }}]
    })


def _write_tab(spreadsheet_id, token, tab_name, rows):
    """Clear the tab's data columns, then write a fresh header + rows.
    Clearing first means a feed that shrank doesn't leave stale rows behind.
    """
    clear_range = "'%s'!A:B" % tab_name
    _call("POST", "%s/%s/values/%s:clear" % (SHEETS_API, spreadsheet_id, _quote(clear_range)), token)

    values = [list(cfg.CSV_HEADER)] + [[r["url"], r["label"]] for r in rows]
    update_range = "'%s'!A1" % tab_name
    _call("PUT", "%s/%s/values/%s?valueInputOption=RAW" %
          (SHEETS_API, spreadsheet_id, _quote(update_range)), token, {"values": values})
    return len(rows)


def update_feed_sheets(out_rows, log=print):
    """Write Core + Adventures into the configured spreadsheet.

    Never raises: a missing config, auth failure, or API error is caught
    and reported, never allowed to take down an otherwise-good run (the
    CSVs, xlsx report, and email must still complete). Returns
    {"configured": bool, "ok": bool, "updated": {tab: row_count}, "error": str|None}.
    """
    report = {"configured": False, "ok": False, "updated": {}, "error": None}
    if not cfg.google_sheets_configured():
        report["error"] = "not configured (GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_SHEETS_SPREADSHEET_ID missing)"
        log("Google Sheets: " + report["error"])
        return report

    report["configured"] = True
    try:
        info = json.loads(cfg.GOOGLE_SERVICE_ACCOUNT_JSON)
        token = _get_access_token(info)
        tab_names = [cfg.SHEET_TAB_CORE, cfg.SHEET_TAB_ADVENTURES]
        _ensure_tabs(cfg.GOOGLE_SHEETS_SPREADSHEET_ID, token, tab_names)

        core_rows = [r for r in out_rows if r["feed"] == cfg.FEED_CORE]
        adv_rows = [r for r in out_rows if r["feed"] == cfg.FEED_ADVENTURES]
        report["updated"][cfg.SHEET_TAB_CORE] = _write_tab(
            cfg.GOOGLE_SHEETS_SPREADSHEET_ID, token, cfg.SHEET_TAB_CORE, core_rows)
        report["updated"][cfg.SHEET_TAB_ADVENTURES] = _write_tab(
            cfg.GOOGLE_SHEETS_SPREADSHEET_ID, token, cfg.SHEET_TAB_ADVENTURES, adv_rows)
        report["ok"] = True
        log("Google Sheets: updated %s" %
            ", ".join("%s (%d rows)" % (k, v) for k, v in report["updated"].items()))
    except json.JSONDecodeError as e:
        report["error"] = "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: %s" % e
        log("Google Sheets: FAILED - " + report["error"])
    except KeyError as e:
        report["error"] = "service account JSON is missing required field %s" % e
        log("Google Sheets: FAILED - " + report["error"])
    except Exception as e:
        report["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        log("Google Sheets: FAILED - " + report["error"])
    return report
