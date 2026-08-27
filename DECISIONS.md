# Decisions log

Every decision that shapes the feed, with the reason and the evidence behind it.
Anything not verified is marked as such.

---

## D1. Region labels are built from the URL slug, not hand written

**Date:** 25 August 2026
**Status:** Agreed

### What was found

The v2 feed carried two different naming styles for the same dimension, depending on whether a URL had appeared in the earlier hand-built sample:

| URL | Label in v2 | Origin |
|---|---|---|
| `/au/vic/mornington-peninsula` | `REG_MORNINGTON_PEN` | hand written |
| other Mornington rows | `REG_MORNINGTON_PENINSULA` | derived from the slug |
| `/au/nsw/central-coast` | `REG_CENTRAL_COAST` | derived |
| `/us/oregon/central-coast` | `REG_CENTRAL_COAST_OR` | hand written |

47 rows in the core feed differed for this reason.

### The real problem underneath

Three region slugs exist under more than one state. Verified against the destinations sitemap on 25 August 2026:

| Slug | Australia | United States |
|---|---|---|
| `north-coast` | `/au/nsw/north-coast` | `/us/oregon/north-coast` |
| `south-coast` | `/au/nsw/south-coast` | `/us/oregon/south-coast` |
| `central-coast` | `/au/nsw/central-coast` | `/us/oregon/central-coast` |

A label built from the slug alone gives both pages the same value. An asset group selecting the New South Wales region would then also pull in Oregon pages, in a market that is explicitly on hold.

### Decision

1. Region labels are always derived from the URL slug, in full. An automated monthly job cannot reproduce hand written abbreviations, so consistency has to come from a rule.
2. Where a slug is ambiguous, the state code is appended: `REG_NORTH_COAST_NSW` and `REG_NORTH_COAST_OR`. This matches the convention already used in the earlier sample for those specific rows.
3. The ambiguous slug list lives in `config.AMBIGUOUS_REGION_SLUGS`.
4. Every run re-detects collisions through `labeller.find_region_collisions`. If a newly published region clashes with an existing label, the run reports it rather than silently merging two regions into one label.

### Verified after the change

- 0 collisions across all 56 region hubs
- All 56 region labels unique
- Point of interest collections that reference those regions follow the corrected labels, for example `/au/nsw/collections/byron-bay` now carries `REG_NORTH_COAST_NSW`
- Unaffected regions unchanged, for example `REG_YARRA_VALLEY` and `REG_HIGH_COUNTRY`

### Consequence to be aware of

The already generated v2 CSV files still contain the older mixed naming. They have not been uploaded, so they should be regenerated from this system before any upload. If they had already been live, the label change would need to be coordinated with the asset groups that select on those labels.

---

## D2. Location for listings, stories and adventures comes from a supplied file

**Date:** 25 August 2026
**Status:** Agreed, file pending

Listing URLs follow `/listings/{id}-{slug}` and carry no location. Verified across the full sitemap: 0 of 3,464 listing URLs, 0 of 1,077 story URLs and 0 of 5,479 adventure URLs contain a country or state segment. 264 listing slugs, which is 7.6 percent, happen to contain a place name inside free text written by hand, which is not a reliable data field.

The system therefore reads country, state and region for these pages from a supplied CSV, joined on the listing id taken from the URL. Until that file exists those rows carry every other label but no location, which is safe: they simply do not match a location scoped asset group.

---

## D3. Requests carry a browser user agent

**Date:** 25 August 2026
**Status:** Verified and implemented

Tested from a Railway container in us-west2:

| Request | Result |
|---|---|
| Default command line agent | 403 Forbidden |
| Browser agent | 200 OK |
| HEAD with browser agent | 200 OK |
| Ten rapid requests | All 200, no rate limiting observed |

The site rejects requests that identify as tooling. No JavaScript rendering is required, so no headless browser, crawler licence or paid service is needed. The agent string is configurable through an environment variable so it can be changed without a code change.

---

## D4. Only changed URLs are status checked

**Date:** 25 August 2026
**Status:** Agreed

Checking all 10,313 URLs every month is slow and unnecessary. Only added and removed URLs are checked.

Known gap: a page can start returning 404 while still being listed in the sitemap, and a difference only check will not notice it. Recommendation on record is a full status check every six months as a safety net. This is a scheduling decision, not additional build work.

A single sitemap snapshot cannot predict how large the monthly difference will be. Sitemap timestamps record content edits rather than additions and removals, so they are not a substitute. The first scheduled run establishes the real figure. The check volume is capped by `config.MAX_STATUS_CHECKS` so a very large difference cannot make a run overrun.

---

## D5. Upload to Google Ads stays manual

**Date:** 25 August 2026
**Status:** Agreed

The system produces the two CSV files and emails them. A person uploads them. The upload step is kept as a separate module so it can be automated later without touching the rest.

Not confirmed: whether a page feed asset set can be attached to a Performance Max campaign through the Google Ads API. Google's API documentation covers page feed asset sets under Dynamic Search Ads, and the Performance Max documentation does not describe attaching one. This has no effect while upload is manual.

---

## D6. URL expansion is set to off

**Date:** 25 August 2026
**Status:** Agreed, action outside this system

With expansion off, Performance Max serves only URLs in the feed and asset groups, so the feed acts as a restriction rather than a hint.

Two consequences worth recording:

1. Expansion is on by default in Performance Max, so it has to be turned off deliberately inside the Google Ads account. This system does not control that setting.
2. With expansion off, the "exclude some URLs from search ads" control does not apply. The Search and Performance Max boundary is therefore enforced by leaving `SEARCH_HEAD` URLs out of the asset groups instead.

---

## D7. The site's block is at least partly IP/ASN-based, not purely a client-library fingerprint

**Date:** 27 August 2026
**Status:** Verified, refines D3

D3 concluded the site's protection layer rejects `requests` and `curl` while accepting `urllib`, all from the same Railway container, and attributed this to client fingerprinting. That conclusion is not wrong, but it is incomplete.

### What was found

From a residential/office IP (Pakistan Telecom range) on 27 August 2026, using the exact same `urllib` client and the exact same browser user agent that gets 200 OK from Railway:

| URL | Result |
|---|---|
| `https://www.riparide.com/` | 403, `Server: cloudflare` |
| `https://www.riparide.com/robots.txt` | 403, `Server: cloudflare` |
| `https://www.riparide.com/sitemaps/sitemap.xml` | 403, `Server: cloudflare` |

Every URL was blocked, including `robots.txt` — a resource Cloudflare's managed bot rules do not typically gate behind challenge/fingerprint checks. This pattern (blanket block regardless of path, same client that works elsewhere) is more consistent with an IP or ASN reputation rule than a per-request client fingerprint.

### Consequence

The client-library choice (D3) still stands — keep using `urllib` only. But "it worked from a Railway container" is not sufficient evidence that it will work from **any** cloud runner. This directly matters for D12 (the move to GitHub Actions): GitHub-hosted runner IP ranges are well-known and are exactly the kind of range a "block hosting providers/VPNs" Cloudflare rule targets. The `monthly-refresh.yml` workflow's "Check the site answers" step exists specifically to catch this early and loudly rather than assume it, but it has not yet been proven by an actual run on GitHub's infrastructure — that is the one verification this document cannot complete on its own. Confirm it with a real `workflow_dispatch` run before relying on the schedule.

---

## D8. Two SEARCH_HEAD boundary gaps found against the SNR spec

**Date:** 27 August 2026
**Status:** One fixed, one flagged unconfirmed

The SNR spec names four query-intent clusters where Search Generic beats PMax 2x+: romantic, getaways, off-grid, pet-friendly. Cross-checking the built taxonomy against that list found two problems.

### Fixed: "getaway" had no keyword at all

`INTENT_KEYWORDS` and `SEARCH_HEAD_INTENTS` only covered three of the four clusters (romantic, off-grid, pet-friendly). Getaway-type listings/stories could never be excluded from PMax under Option B, silently defeating the reason the boundary dimension exists. Added `("getaway", "INT_GETAWAY")` to `INTENT_KEYWORDS` (substring match also covers "getaways" and "weekend-getaway") and `INT_GETAWAY` to `SEARCH_HEAD_INTENTS`. Covered by `test_labeller.IntentTests`.

### Unconfirmed, left as-is pending client/SNR sign-off: `SEARCH_HEAD_TYPES`

`config.SEARCH_HEAD_TYPES` (`TYPE_TINY_HOUSE`, `TYPE_CABIN`, `TYPE_GLAMPING`, `TYPE_COTTAGE`) marks synthetic facet-type pages as `SEARCH_HEAD` by stay *type*. Nothing in the SNR spec discusses stay types for this purpose — the spec's own SEARCH_HEAD rationale is entirely about query-intent clusters. This constant appears to have been inferred by whoever first wrote `config.py`, with no citation and no DECISIONS.md entry, which breaks this file's own rule that nothing here is guessed. It has been left in place (removing it without direction is just as much a guess as leaving it) but is now flagged in `config.py` directly. **Needs an explicit answer from SNR/the client** before the Option A/B split goes live: either confirm the stay-type inference, or replace it with nothing until a real basis exists.

---

## D9. Facet URLs were never actually checked for 200-vs-redirect status

**Date:** 27 August 2026
**Status:** Fixed

### What was found

The spec is emphatic that a feed with mis-ordered facet parameters is "a feed of redirects... a feed of disapprovals," and its QA checklist requires "facet URLs return 200 directly, not a 301." But `run.py`'s default monthly path only status-checks `d["added"]` — URLs new in the sitemap diff. The ~132 facet URLs are synthesised in `build_rows()` *after* that diff is computed (they are not part of any sitemap), so they never appeared in `d["added"]` and were never HTTP-checked except when someone manually ran `--full-status`. `validator.py`'s facet-order check only verifies the parameter order in the URL string — a static check that cannot catch the site itself starting to redirect a combination it used to serve directly.

### Decision

`run.py`'s status-check step now always includes every `PAGE_FACET_TYPE` row's URL in its targets, merged with the diff-based targets, regardless of `--full-status`. This is cheap (~130 URLs) and closes the gap the spec cares most about. Verified end to end: a run against a blocked network correctly excluded all facet rows as dead rather than shipping them (see D11's row-collapse guard for what stopped that same run from shipping an empty feed).

Not fixed, and deliberately left as a documented gap rather than a guessed implementation: nothing confirms that a given geo × subcategory combination actually has ≥1 live listing before including it. Verifying "empty results" would mean scraping page content for a specific no-results marker, and this repo has no working access to riparide.com from which to observe that marker's real text (see D7). Whoever next has verified site access should determine the exact marker and wire in a real check rather than have this guess at it.

---

## D10. robots.txt / AdsBot-Google check added

**Date:** 27 August 2026
**Status:** Fixed, non-blocking by design

The spec's QA checklist requires confirming `robots.txt` does not block `AdsBot-Google` or `AdsBot-Google-Mobile`. Nothing checked this at all. `fetcher.check_adsbot_access()` now fetches and parses `robots.txt`, and reports (via the run summary and email) whether either AdsBot agent is blocked from any of `config.ADSBOT_CHECK_PATHS`.

Two things worth knowing:

1. Per Google Ads' documented AdsBot behaviour, AdsBot does not fall back to a bare `User-agent: *` block — only a group naming it explicitly applies. If robots.txt has no AdsBot-specific group, the check reports "not blocked" on that basis. Re-verify this against Google's current help documentation if it is ever load-bearing for a real disapproval investigation.
2. This check is deliberately **non-blocking** — a fetch failure or a detected block is reported as a warning, not a validation failure that stops the run. Given D7's finding that this exact fetch already fails outright from some networks, making it hard-block the entire monthly run would mean an unrelated network hiccup could stop a good feed from shipping. Covered by `test_fetcher.py` (both the parser and the failure-handling paths).

---

## D11. Two resilience gaps closed: the D4 safety net was never automatic, and nothing caught a collapsed feed

**Date:** 27 August 2026
**Status:** Fixed

### D4's "full status check every 6 months" was a recommendation on record, not code

Nothing ever actually ran it — it required someone to remember to pass `--full-status` by hand. `config.FULL_STATUS_MONTHS` (`{1, 7}`, January and July) now makes `run.py` check every URL automatically in those months regardless of any flag, closing the exact gap D4 described (a page returning 404 while still listed in the sitemap, invisible to a diff-only check).

### A network failure could silently ship a near-empty feed

Found while testing the above from a network that gets blocked outright (D7): when every status check fails, every checked URL is treated as dead and excluded. Before this fix, nothing stopped the run from writing and emailing a 0-row or near-0-row CSV over a good one — every existing validation check passes vacuously on an empty feed. Reproduced directly: a run against a simulated prior baseline of 250 core rows, with the network unreachable, wrote 3 rows and would have shipped them.

`store.save_snapshot()` now records each feed's row count alongside the URL snapshot. `validator.validate()` takes an optional `previous_counts` and fails — writing nothing, exactly like any other validation failure — if a feed's row count falls below `config.MIN_ROW_RATIO` (0.5) of last run's. Verified end to end: the same simulated scenario now fails validation with `CORE: 250 -> 3`, exits non-zero, and leaves the previous snapshot and output files untouched. Under D12's GitHub Actions migration, a non-zero exit also means GitHub marks the workflow run failed and emails repo watchers by default — a second, independent alert channel on top of this project's own email report.

---

## D12. Migrated from Railway to GitHub Actions

**Date:** 27 August 2026
**Status:** Built, pending one live verification (see D7)

### Why

Railway required an unverified volume mount (`/data`) for the snapshot and location cache to survive between runs, and unverified environment variables for email — both open questions from the initial review that were never confirmed against the live Railway project. Moving to GitHub Actions removes a paid dependency and, more importantly, replaces an opaque platform volume with ordinary, reviewable git history.

### What changed

- `.github/workflows/monthly-refresh.yml` replaces both `railway.json` (deleted) and the old manual-only `build-feed.yml` (deleted, superseded). It runs on the same `0 3 1 * *` schedule, plus `workflow_dispatch` for manual runs.
- State persistence: after a successful (or partially-successful) run, the workflow commits `data/snapshot.json`, `data/snapshot.json.previous` and `data/location-cache.json` back to the repository as `github-actions[bot]`. `.gitignore` was updated to stop excluding these files — they are now the source of truth, not a build artifact. `data/output/*.csv` remains ignored; it is fully derived and distributed via the workflow's artifact upload and the report email instead.
- Email configuration moves from Railway environment variables to GitHub Actions repository secrets (`EMAIL_FROM`, `EMAIL_TO`, `RESEND_API_KEY` or the `SMTP_*` quartet) — same variable names, different platform.
- `concurrency: group: monthly-page-feed-refresh` prevents a manual run from racing the scheduled one and both trying to commit/push state at once.
- A failed run's non-zero exit code now surfaces as a red workflow run with GitHub's default failure-notification email — free redundancy Railway's cron jobs don't provide out of the box.

### What is not yet verified

D7's finding — that this dev machine gets blocked by Cloudflare on every URL, in a way D3's original testing didn't anticipate — means GitHub Actions' own runner IPs have not actually been proven to get through, only assumed to, on the basis that `build-feed.yml` (the workflow this replaces) was written with a reachability-check step already in it. **The first real `workflow_dispatch` run of `monthly-refresh.yml` is the actual test of this.** If it fails at the "Check the site answers" step, the migration's core assumption is wrong and needs a different plan (e.g. a residential-proxy egress, or staying on Railway specifically for its network path rather than its volume).

---

## D13. Added an .xlsx report, and with it, one deliberate dependency

**Date:** 27 August 2026
**Status:** Built

### The ask

The client wants a proper spreadsheet alongside the raw upload CSVs — something closer to the original manual `Riparide_PMax_Page_Feed_Example.xlsx` (Summary, QA Checks, Label Taxonomy tabs) than a bare 2-column CSV — generated every run, stored in this repo (not just emailed), and attached to the report email.

### Why `openpyxl`, breaking the "no third-party packages" rule

Every previous decision in this document about staying stdlib-only (D3, D7) is about the *fetching* layer: the site's protection rejects `requests`/`curl`, and possibly the requesting IP itself. `openpyxl` never makes a network call — it only writes a local `.xlsx` file — so it carries none of that risk. The realistic alternative, hand-rolling the OOXML zip/XML format with only `zipfile` and `xml.etree`, is a well-known rabbit hole: multiple interdependent XML parts (workbook, sheets, styles, shared strings, relationships) that are easy to get subtly wrong in a way that produces a file Excel refuses to open. Given the goal is a reliable monthly artifact, not proving a point about dependencies, `openpyxl` (pure Python, MIT licensed, no native extensions, no network access) is the pragmatic choice. `requirements.txt` documents this exception explicitly so it doesn't read as an accidental violation of the stated rule.

### What was built

`src/report.py` builds `reports/riparide-page-feed-report.xlsx` with five sheets:

- **Summary** — the same content as the plain-text email report (changes, status checks, location, robots/AdsBot result, files written), in a readable table.
- **QA Checks** — every validator result, colour-coded pass (green) / fail (red).
- **Label Taxonomy** — generated directly from `config.py`'s constants (subcategories, intent keywords, boundaries), not hand-maintained, so it cannot drift out of sync with the code the way a manually-written reference sheet would.
- **Page Feed - Core** / **Page Feed - Adventures** — the exact same rows as the two CSVs, as real filterable sheets.

Unlike the CSVs (`data/output/`, gitignored, fully derived, regenerated every run), the report lives at `reports/riparide-page-feed-report.xlsx` — **not** gitignored, committed by the same `monthly-refresh.yml` step that persists the snapshot and location cache (D12), so every month's report is a reviewable point in git history rather than something that only ever existed in an email inbox. It is also attached to the report email alongside the two CSVs and `snapshot.json`.

Deliberately left out of scope: an "Asset Group Map" or "Build Sequence" tab. Those describe one-time, human-decided Google Ads account structure, not something this run regenerates monthly — including them would mean either leaving them permanently stale or fabricating content this codebase has no basis for. If they're wanted, they belong in the original manually-maintained workbook, not the automated one.
