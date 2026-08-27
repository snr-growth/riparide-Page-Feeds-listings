# -*- coding: utf-8 -*-
"""Send the monthly report.

Two delivery routes are supported so the client can use whichever they have:
an email service API key, or the SMTP details of an existing mailbox. If
neither is configured the run still completes and simply reports that the
email was not sent. A missing key must never lose a good feed.
"""
import base64
import mimetypes
import os
import smtplib
from email.message import EmailMessage

import config as cfg


def _attach_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _send_smtp(subject, body, attachments):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.EMAIL_FROM
    msg["To"] = ", ".join(cfg.EMAIL_TO)
    msg.set_content(body)
    for path in attachments:
        data = _attach_bytes(path)
        ctype, _ = mimetypes.guess_type(path)
        maintype, subtype = (ctype or "text/csv").split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype,
                           filename=os.path.basename(path))
    with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=60) as s:
        s.ehlo()
        try:
            s.starttls()
            s.ehlo()
        except smtplib.SMTPNotSupportedError:
            pass  # server already on an implicit TLS port
        s.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
        s.send_message(msg)
    return "sent over SMTP to %d recipient(s)" % len(cfg.EMAIL_TO)


def _send_resend(subject, body, attachments):
    import json
    import urllib.request
    payload = {
        "from": cfg.EMAIL_FROM,
        "to": cfg.EMAIL_TO,
        "subject": subject,
        "text": body,
        "attachments": [
            {"filename": os.path.basename(p),
             "content": base64.b64encode(_attach_bytes(p)).decode("ascii")}
            for p in attachments
        ],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + cfg.RESEND_API_KEY,
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.status >= 300:
            raise RuntimeError("email API returned %d" % r.status)
    return "sent over the email API to %d recipient(s)" % len(cfg.EMAIL_TO)


def send(subject, body, attachments=None, log=print):
    """Returns (sent, detail). Never raises: a delivery failure is reported,
    not thrown, so a completed run is not lost because of the mail step."""
    attachments = [p for p in (attachments or []) if p and os.path.exists(p)]

    if not cfg.email_configured():
        missing = []
        if not cfg.EMAIL_FROM:
            missing.append("EMAIL_FROM")
        if not cfg.EMAIL_TO:
            missing.append("EMAIL_TO")
        if not cfg.RESEND_API_KEY and not cfg.SMTP_HOST:
            missing.append("RESEND_API_KEY or SMTP_HOST/SMTP_USER/SMTP_PASSWORD")
        detail = "not configured, missing: " + ", ".join(missing)
        log("email: " + detail)
        return False, detail

    try:
        if cfg.RESEND_API_KEY:
            detail = _send_resend(subject, body, attachments)
        else:
            detail = _send_smtp(subject, body, attachments)
        log("email: " + detail)
        return True, detail
    except Exception as e:
        detail = "delivery failed: %s: %s" % (type(e).__name__, str(e)[:200])
        log("email: " + detail)
        return False, detail


def build_report(summary):
    """Plain text body for the monthly email."""
    L = []
    L.append("Riparide page feed refresh")
    L.append("Run: %s" % summary["run_at"])
    L.append("")

    if summary.get("failed"):
        L.append("RUN FAILED. No files were produced.")
        L.append("")
        L.append("Reason: %s" % summary["failed"])
        L.append("")

    d = summary.get("diff") or {}
    if d:
        if d.get("first_run"):
            L.append("This was the first run, so there was no previous snapshot")
            L.append("to compare against. Every URL counts as new.")
            L.append("")
        L.append("Changes")
        L.append("  Added:     %d" % len(d.get("added", [])))
        L.append("  Removed:   %d" % len(d.get("removed", [])))
        L.append("  Unchanged: %d" % d.get("unchanged_count", 0))
        L.append("  Feed size: %d -> %d" % (d.get("previous_total", 0), d.get("current_total", 0)))
        L.append("")

    st = summary.get("status") or {}
    if st:
        L.append("Status checks")
        L.append("  Checked:   %d" % st.get("checked", 0))
        L.append("  Excluded:  %d (did not return 200)" % st.get("excluded", 0))
        if st.get("unchecked"):
            L.append("  Unchecked: %d (above the per-run cap)" % st["unchecked"])
        for u, code in (st.get("examples") or [])[:10]:
            L.append("    %s  %s" % (code, u))
        L.append("")

    loc = summary.get("location") or {}
    if loc and not loc.get("skipped"):
        L.append("Location")
        L.append("  Read from the page:   %d row(s)" % loc.get("applied", 0))
        L.append("  Pages read this run:  %d" % loc.get("fetched", 0))
        L.append("  Cached in total:      %d" % loc.get("cached_total", 0))
        if loc.get("deferred"):
            L.append("  Deferred to next run: %d (above the per-run cap)" % loc["deferred"])
        L.append("  Still without location: %d" % loc.get("still_without_location", 0))
        um = loc.get("unmapped_stay_wordings") or {}
        if um:
            L.append("  Stay-type wordings seen in titles that are not in the")
            L.append("  subcategory list, recorded rather than guessed:")
            for k, v in um.items():
                L.append("    %-24s %d" % (k, v))
        L.append("")

    a = summary.get("attributes") or {}
    if a:
        L.append("Listing attributes")
        if not a.get("present"):
            L.append("  File not supplied. Location labels are blank on those rows.")
        else:
            L.append("  Rows read:   %d" % a.get("rows", 0))
            L.append("  Usable:      %d" % a.get("usable", 0))
            if a.get("inactive"):
                L.append("  Skipped as inactive: %d" % a["inactive"])
        for p in a.get("problems", []):
            L.append("  Note: %s" % p)
        if summary.get("merge"):
            m = summary["merge"]
            L.append("  Rows given a location: %d" % m.get("rows_filled", 0))
            L.append("  Still without location: %d" % m.get("still_without_location", 0))
        L.append("")

    rb = summary.get("robots") or {}
    if rb:
        L.append("robots.txt / AdsBot check")
        if not rb.get("fetched"):
            L.append("  Could not check: %s" % rb.get("note", "unknown reason"))
        elif rb.get("blocked"):
            L.append("  WARNING: AdsBot appears blocked on %d path(s):" % len(rb["blocked"]))
            for p, d in rb["blocked"]:
                L.append("    %s blocked by Disallow: %s" % (p, d))
        elif rb.get("adsbot_group_found"):
            L.append("  AdsBot-Google / AdsBot-Google-Mobile: not blocked")
        else:
            L.append("  %s" % rb.get("note", ""))
        L.append("")

    sh = summary.get("sheets") or {}
    if sh:
        L.append("Google Sheets (Google-Ads-facing feed)")
        if not sh.get("configured"):
            L.append("  Not configured: %s" % sh.get("error", ""))
        elif sh.get("ok"):
            for tab, n in (sh.get("updated") or {}).items():
                L.append("  %-24s %6d rows" % (tab, n))
        else:
            L.append("  FAILED: %s" % sh.get("error", "unknown error"))
            L.append("  The CSVs/xlsx above are still correct - only the Sheets update failed.")
        L.append("")

    if summary.get("collisions"):
        L.append("Region label collisions detected")
        for label, urls in summary["collisions"].items():
            L.append("  %s is used by %d hubs:" % (label, len(urls)))
            for u in urls:
                L.append("    %s" % u)
        L.append("")

    checks = summary.get("checks") or []
    if checks:
        L.append("Validation")
        for c in checks:
            L.append("  %-4s %-56s %s" % ("PASS" if c["passed"] else "FAIL",
                                          c["check"], c["detail"]))
        L.append("")

    out = summary.get("outputs") or {}
    if out:
        L.append("Files")
        for feed, (path, count) in out.items():
            L.append("  %-11s %6d rows  %s" % (feed, count, os.path.basename(path)))
        L.append("")
        L.append("Next step: upload both files in Google Ads under")
        L.append("Tools, Business data, Page feed.")

    return "\n".join(L)
