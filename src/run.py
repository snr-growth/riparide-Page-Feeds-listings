# -*- coding: utf-8 -*-
"""The monthly run.

Order matters. The snapshot is written only after a run has succeeded, so a
failed run leaves last month's baseline intact and the next run picks up
exactly where this one should have.
"""
import argparse
import os
import sys
import traceback
from datetime import datetime, timezone

import config as cfg
import fetcher
import labeller
import store
import attributes
import enricher
import validator
import writer
import report
import emailer

LINE = "-" * 72


def log(msg=""):
    print(msg, flush=True)


def build_rows(urls_by_group):
    """Label every sitemap URL, then add the built facet URLs."""
    rows = []
    for group, urls in urls_by_group.items():
        for u in urls:
            rows.append(labeller.label_url(u, group))
    rows.extend(labeller.build_facet_rows())

    seen, unique = set(), []
    for r in rows:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        unique.append(r)
    return unique


def main(argv=None):
    ap = argparse.ArgumentParser(description="Riparide page feed monthly refresh")
    ap.add_argument("--dry-run", action="store_true",
                    help="do everything except writing the snapshot and sending email")
    ap.add_argument("--skip-status", action="store_true",
                    help="skip the HTTP status checks")
    ap.add_argument("--full-status", action="store_true",
                    help="status check every URL, not only the changed ones "
                         "(happens automatically every 6 months regardless of this flag, see D4)")
    ap.add_argument("--skip-location", action="store_true",
                    help="skip reading location from listing and story pages")
    ap.add_argument("--offline-snapshot", default=None,
                    help="use this snapshot json as the current URL list instead of fetching")
    args = ap.parse_args(argv)

    started = datetime.now(timezone.utc)
    summary = {"run_at": started.strftime("%Y-%m-%d %H:%M UTC"), "failed": None}

    try:
        # 1. current URL list ------------------------------------------------
        log(LINE)
        if args.offline_snapshot:
            import json
            with open(args.offline_snapshot, encoding="utf-8") as f:
                raw = json.load(f)
            current = raw.get("urls_by_group", raw)
            log("offline mode: loaded %d urls from %s"
                % (sum(len(v) for v in current.values()), args.offline_snapshot))
        else:
            log("fetching sitemaps")
            current, _ = fetcher.fetch_all_urls(log)
        total_now = sum(len(v) for v in current.values())
        if total_now == 0:
            raise RuntimeError("no URLs were found, refusing to continue")

        # 2. compare against last month -------------------------------------
        log(LINE)
        previous = store.load_snapshot()
        d = store.diff(previous["urls_by_group"] if previous else None, current)
        summary["diff"] = d
        log("previous snapshot: %s" % (previous["taken_at"] if previous else "none, first run"))
        log("added %d, removed %d, unchanged %d" %
            (len(d["added"]), len(d["removed"]), d["unchanged_count"]))

        # 3. label -----------------------------------------------------------
        log(LINE)
        rows = build_rows(current)
        log("labelled %d rows" % len(rows))

        collisions = labeller.find_region_collisions(rows)
        summary["collisions"] = collisions
        if collisions:
            log("WARNING: %d region label collision(s) detected" % len(collisions))
            for label, urls in collisions.items():
                log("  %s -> %s" % (label, ", ".join(urls)))

        # 4. recover location from the pages themselves ----------------------
        log(LINE)
        if args.skip_location:
            log("location enrichment skipped by flag")
            summary["location"] = {"skipped": True}
        else:
            summary["location"] = enricher.enrich(
                rows, limit=cfg.MAX_LOCATION_FETCHES, log=log)
            loc = summary["location"]
            log("location: %d row(s) filled, %d cached, %d still without"
                % (loc["applied"], loc["cached_total"], loc["still_without_location"]))
            if loc.get("unmapped_stay_wordings"):
                log("stay-type wordings seen in titles but not in the subcategory list: %s"
                    % ", ".join("%s (%d)" % (k, v)
                                for k, v in loc["unmapped_stay_wordings"].items()))

        # 5. merge supplied attributes file, if one was provided -------------
        log(LINE)
        by_id, attr_report = attributes.load(log=log)
        summary["attributes"] = attr_report
        summary["merge"] = attributes.apply(rows, by_id, log=log)
        log("attributes: %s" % ("not supplied" if not attr_report["present"]
                                else "%d usable rows" % attr_report["usable"]))
        log("rows given a location: %d, still without: %d"
            % (summary["merge"]["rows_filled"], summary["merge"]["still_without_location"]))

        # 6. status check ----------------------------------------------------
        log(LINE)
        status = {"checked": 0, "excluded": 0, "unchecked": 0, "examples": []}
        by_url = {r["url"]: r for r in rows}
        if args.skip_status:
            log("status checks skipped by flag")
        else:
            auto_full = started.month in cfg.FULL_STATUS_MONTHS
            full_status = args.full_status or auto_full
            if full_status:
                if auto_full and not args.full_status:
                    log("%s is a full-status safety-net month (D4), checking every URL"
                        % started.strftime("%B"))
                targets = [r["url"] for r in rows if r["url"] in by_url]
            else:
                # Facet URLs are synthesised in build_rows(), never fetched
                # from a sitemap, so they never appear in d["added"] and a
                # diff-only check would never notice one has started
                # redirecting. They are cheap (~130 URLs), so they are
                # checked every run regardless of the diff.
                facet_urls = [r["url"] for r in rows if r["page_type"] == "PAGE_FACET_TYPE"]
                seen = set()
                targets = []
                for u in facet_urls + [u for u in d["added"] if u in by_url]:
                    if u not in seen:
                        seen.add(u)
                        targets.append(u)
            if len(targets) > cfg.MAX_STATUS_CHECKS:
                status["unchecked"] = len(targets) - cfg.MAX_STATUS_CHECKS
                targets = targets[:cfg.MAX_STATUS_CHECKS]
                log("capped at %d checks, %d left unchecked"
                    % (cfg.MAX_STATUS_CHECKS, status["unchecked"]))
            log("status checking %d url(s)" % len(targets))
            results = fetcher.status_check(targets, log)
            status["checked"] = len(results)
            dead = [(u, c) for u, c in results.items() if c not in (0, 200)]
            failed_request = [u for u, c in results.items() if c == 0]
            if failed_request:
                log("%d url(s) could not be reached, keeping them rather than guessing"
                    % len(failed_request))
            dead_set = {u for u, _ in dead}
            if dead_set:
                rows = [r for r in rows if r["url"] not in dead_set]
                status["excluded"] = len(dead_set)
                status["examples"] = dead[:20]
                log("removed %d url(s) that did not return 200" % len(dead_set))
        summary["status"] = status

        # 6b. robots.txt / AdsBot check ---------------------------------------
        log(LINE)
        summary["robots"] = fetcher.check_adsbot_access(cfg.ADSBOT_CHECK_PATHS, log)

        # 7. validate --------------------------------------------------------
        log(LINE)
        out_rows = [{"url": r["url"], "label": labeller.label_string(r),
                     "feed": labeller.feed_of(r)} for r in rows]
        feed_rows = [r for r in out_rows if r["feed"] != cfg.FEED_EXCLUDE]
        previous_counts = (previous or {}).get("feed_counts")
        passed, checks = validator.validate(feed_rows, previous_counts=previous_counts)
        summary["checks"] = checks
        log(validator.format_results(checks))
        if not passed:
            raise RuntimeError("validation failed, no files were written")

        # 8. write output ----------------------------------------------------
        log(LINE)
        outputs = writer.write_all(out_rows)
        summary["outputs"] = outputs
        for feed, (path, n) in outputs.items():
            log("wrote %-11s %6d rows -> %s" % (feed, n, path))

        # 8b. write the xlsx report -------------------------------------------
        log(LINE)
        summary["report_path"] = report.write_report(out_rows, checks, summary)
        log("wrote report -> %s" % summary["report_path"])

        # 9. save the snapshot ----------------------------------------------
        if args.dry_run:
            log("dry run: snapshot not written")
        else:
            feed_counts = {feed: n for feed, (_, n) in outputs.items()}
            saved = store.save_snapshot(current, feed_counts=feed_counts)
            log("snapshot saved: %d urls at %s" % (saved["total"], saved["taken_at"]))
            summary["snapshot_path"] = cfg.SNAPSHOT_FILE

    except Exception as e:
        summary["failed"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        log(LINE)
        log("RUN FAILED: %s" % summary["failed"])
        traceback.print_exc()

    # 10. report --------------------------------------------------------------
    log(LINE)
    body = emailer.build_report(summary)
    log(body)

    attachments = [p for p, _ in (summary.get("outputs") or {}).values()]
    if summary.get("report_path"):
        attachments.append(summary["report_path"])
    if summary.get("snapshot_path"):
        # Insurance against losing the baseline: if wherever this runs loses
        # its persistent storage, the last-known-good snapshot can be
        # recovered from this month's email rather than starting over.
        attachments.append(summary["snapshot_path"])
    subject = "Riparide page feed refresh %s%s" % (
        started.strftime("%b %Y"), " FAILED" if summary["failed"] else "")
    if args.dry_run:
        log(LINE)
        log("dry run: email not sent")
    else:
        emailer.send(subject, body, attachments, log)

    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
