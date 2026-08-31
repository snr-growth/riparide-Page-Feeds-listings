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

---

## D14. Added a Google Sheets integration as the Google-Ads-facing format, separate from the client-shared CSVs/xlsx

**Date:** 27 August 2026
**Status:** Built, pending client-side setup (service account creation, sheet sharing, GitHub secrets)

### The ask

The client wants Google Ads to pull the feed itself rather than being sent a file every month, and separately wants to be able to open something and see the current feed themselves. Across that conversation, three options were weighed: hosting the CSV at a plain URL, a password-protected URL, and Google Sheets. The client chose Google Sheets, specifically because Google Ads' own "Upload new page feed data" dialog lists it as a native source type alongside HTTP/HTTPS/FTP/SFTP — screenshotted directly from their account.

### What was verified before building, and why it changed the design

Before writing any code, Google's own current help documentation was checked rather than assumed, per this file's standing rule. Findings:

- **The 2-column format is confirmed correct as-is.** "For page feeds specifically, download the page feed data template or create your own spreadsheet with at least two columns, including a Page URL column... Format the page feed as a CSV with two columns: Page URL and Custom Label" ([How to use page feeds in Performance Max](https://support.google.com/google-ads/answer/13568488?hl=en-AU), [Use a feed to target Dynamic Search Ads and Performance Max](https://support.google.com/google-ads/answer/7166527?hl=en-GB)). Multiple labels per row are semicolon-separated, exactly matching `labeller.label_string`. No change needed to the existing format.
- **Google Ads' Google Sheets connection only reads the first sheet/tab of the spreadsheet.** "Data Manager can only read data from the first sheet in a Google Sheets spreadsheet" ([Google Sheets - Google Ads Help](https://support.google.com/google-ads/answer/15146000?hl=en-GB)). This was not anticipated when the client first asked for "Core and Adventures as two tabs" — if built that way with Adventures first (or reordered later by anyone), Google Ads would silently start reading the wrong feed with no error surfaced anywhere. `sheets._ensure_tabs()` now actively pins `Page Feed - Core` to sheet index 0 on every single run, not just at setup, specifically to defend against that.
- **Access is per-Google-account, not "public."** Connecting a sheet requires "Editor access to the Google Sheets file" via "Direct connection... through your Google Drive account" (same source) — i.e. whichever human connects it inside Google Ads authenticates as themselves, with their own granted access, not through any API key or service account this project controls. This means the earlier "does the Sheet need to be public" question has a better answer than either side of that debate: it needs to be **shared with (or owned by) whichever Google account manages Google Ads**, which the client's own access already satisfies for both their own viewing and Ads' ingestion. Making it additionally public ("anyone with the link") is optional — useful if other people at Riparide or SNR want drive-by access without being individually added, but not required for either Ads or the client's own use.
- **Column header rules**: "The first row in the spreadsheet must consist of valid headers... must start with a letter or underscore, and must not exceed 256 characters" ([About business data and data feeds](https://support.google.com/google-ads/answer/6072708?hl=en), [Google Sheets - Google Ads Help](https://support.google.com/google-ads/answer/15146000?hl=en-GB)). "Page URL" and "Custom label" both satisfy this trivially.
- **Not confirmed**: the exact automatic refresh cadence for a page feed specifically connected via Google Sheets. Google's documentation describes configurable daily/weekly/first-of-month refresh for ad customizer and dynamic display business data, and separately states new page feed uploads/edits take "2–14 days" to crawl — but nothing found ties those two facts together for a Sheets-connected page feed specifically. **Recommendation, not yet verified**: once the Sheets connection is set up in the account, check the Business Data feed's own schedule/edit screen for a refresh-frequency setting, and confirm it against real crawl behavior rather than assuming either figure applies.

### What was built

`src/sheets.py`, a new, independent delivery path — it does not replace or restructure the two CSVs or the `.xlsx` report (`writer.py`, `report.py`), which remain the **client-shared format**: email attachments, human-readable, unchanged in structure. `sheets.py` writes the exact same `out_rows` data into a client-owned Google Sheet instead, as the **Google-Ads-facing machine format**:

- Authenticates as a Google Cloud service account via the standard OAuth 2.0 JWT-bearer server-to-server flow, signing its own short-lived JWT and exchanging it directly against `oauth2.googleapis.com/token`.
- Every actual Sheets API v4 call after that is plain `urllib` REST — no `google-api-python-client`, no `httplib2`, no `requests` — matching how `fetcher.py` and `emailer.py`'s Resend route already talk to their respective APIs.
- `google-auth` is the one new dependency, used only for RSA-signing the JWT (it requires `cryptography`, confirmed via `pip show google-auth`; there was no pure-stdlib way to do RS256 signing, since the standard library has no asymmetric-crypto primitives at all). It never talks to riparide.com, so — like `openpyxl` in D13 — it carries none of the risk D3/D7 documented for the fetching layer specifically.
- `_ensure_tabs()` creates `Page Feed - Core` / `Page Feed - Adventures` if missing and re-pins Core to index 0 every run (see above).
- `_write_tab()` clears each tab's data columns before writing, so a feed that shrank doesn't leave stale rows below the new data.
- Missing configuration (`GOOGLE_SERVICE_ACCOUNT_JSON` / `GOOGLE_SHEETS_SPREADSHEET_ID`) is treated exactly like unconfigured email: skipped, reported, never a failure.
- A **configured** Sheets update that fails (bad credentials, sheet not shared with the service account, API/network error) is deliberately **not** allowed to block the CSVs, `.xlsx`, or email — a good feed must never be lost over one delivery channel's hiccup, the same principle D5 established for email. But since Sheets may now be how Google Ads actually gets fed, `run.py` still makes the run's overall exit code non-zero in that case, so GitHub Actions marks it failed and sends its own independent notification.
- Verified without live Google credentials: the JWT is signed and independently verified against a throwaway RSA key pair (confirms the signing implementation is actually correct, not just "doesn't crash"), and every Sheets API interaction (auth, tab creation/pinning, clear-and-write, retry-then-fail, retry-then-succeed) is covered by mocked-transport unit tests in `test_sheets.py`.

### What still requires the client, not this codebase

None of the following can be done from here — no Google Cloud or Google Ads account access exists in this environment:

1. Create a Google Cloud project + service account with the Sheets API enabled, and generate a JSON key for it.
2. Create the Google Sheet (or use an existing one), and share Editor access with that service account's email.
3. Paste the full service-account JSON as the `GOOGLE_SERVICE_ACCOUNT_JSON` GitHub Actions secret, and the sheet's ID as `GOOGLE_SHEETS_SPREADSHEET_ID`.
4. In Google Ads, connect that same Sheet as the page feed's source (Business Data → Page feed → Google Sheets), using whichever Google account manages the Ads account and has (or is given) Editor access to the sheet.
5. Decide whether to also share the sheet as "Anyone with the link" for broader viewing — optional, not required for the above to work.

---

## D15. Migrated compute + file hosting from GitHub Actions to a single Railway service

**Date:** 31 August 2026
**Status:** Built and tested as far as possible without Railway account access. Not yet live. GitHub Actions is untouched and still production.

### The ask

The client raised two concerns about the D14 Google Sheets integration in the same conversation: it introduces two independent failure modes (the Sheets API sync, and the service account's access to the sheet — both of which had already failed at least once during this project's own testing), and if the SNR/client relationship ever ends, handing over a Google Cloud project and service account is a heavier, more technical process than handing over a Railway project. Separately, the client asked directly whether to go back to Railway, in the specific context of hosting the feed files rather than syncing to Sheets. Given the client (X) also has a downstream client of their own (Y), a second-hand transfer was explicitly part of the ask, not hypothetical.

### What was verified before building, and why it shaped the design

Two Railway-specific claims were checked live rather than assumed, since getting either wrong would mean designing around a limitation that doesn't exist, or missing one that does:

- **Railway does not support sharing a volume between two services in the same project** ([Railway Central Station](https://station.railway.com/feedback/shared-volumes-a4053215)) — still an open, upvoted feature request as of this check. This rules out the natural-looking split of "one Railway service runs the monthly job and writes to a volume, a second Railway service serves files from that same volume" - that architecture would simply not work.
- **A Railway service supports exactly one volume, and volumes see downtime during that service's own redeploys** ([Railway Docs](https://docs.railway.com/volumes/reference)); automated/manual backups exist on paid plans, which is a real improvement over the completely unverified volume this project relied on before D12.
- **Project ownership genuinely transfers in one native flow**: add the recipient as a project member, "Transfer Ownership," they accept within 24 hours ([Railway Docs](https://docs.railway.com/projects)) — both accounts need an active paid plan. This is materially simpler than a GCP project/service-account handover, which needs `gcloud` CLI commands, a billing-admin role, and an org-level migration wizard ([Google Cloud docs](https://docs.cloud.google.com/resource-manager/docs/organization-setup)) - confirming the client's stated concern was accurate, not just a feeling.
- **`railway.json`'s config-as-code schema** (`build`/`deploy` keys, `RAILPACK` builder, `healthcheckPath`, `restartPolicyType`) was checked against Railway's own current docs rather than guessed, since a wrong field name fails silently rather than erroring.

### What was built

Because of the no-shared-volume constraint, the split that GitHub Actions + a separate host would have given for free had to become **one service**: `src/railway_service.py`, an always-on process that does two things without touching any of the existing pipeline logic:

- Serves `riparide-page-feed-core.csv`, `riparide-page-feed-adventures.csv`, and `riparide-page-feed-report.xlsx` from disk over plain HTTP, at stable paths off the service's Railway-assigned domain. Supports both `GET` and `HEAD` (found missing during a live smoke test - the stdlib `BaseHTTPRequestHandler` returns a bare 501 for `HEAD` unless a handler is defined for it, and a GET-only test would never have caught it; a HEAD-before-GET probe from a real client, potentially Google Ads' own fetcher, is common enough to matter).
- Runs an internal scheduler thread (`should_auto_run`) that checks every 30 minutes whether it's on/after the configured day-of-month and hour (`RAILWAY_RUN_DAY`/`RAILWAY_RUN_HOUR`, defaulting to the 1st at 03:00 UTC - the same schedule `monthly-refresh.yml` uses) and hasn't already run this calendar month, tracked in a small `railway-service-state.json` on the volume. A `POST /run?token=...` endpoint (guarded by the `RUN_TRIGGER_TOKEN` secret) gives the same manual-trigger capability `workflow_dispatch` provides.
- Either path invokes `python src/run.py` as a fresh subprocess - **the exact same script and command GitHub Actions runs**, not a reimplementation - so every processing step (fetch, label, enrich, validate, write, report, Sheets, email) is unchanged and behaves identically on either platform. `config.py`'s existing `FEED_DATA_DIR`/`FEED_REPORT_DIR` environment-variable overrides (already present for testing, see `test_run.py`) are reused to point everything at the Railway volume; no code in the pipeline itself needed to change.
- A run that fails can never remove or overwrite a previously-good file, because that guarantee already lives in `run.py` itself (D-series design: the CSVs/xlsx are written only after `validator.validate()` passes) - the service adds no separate logic for this and doesn't need to.
- `railway.json` configures the Railpack builder, the start command, and an `ON_FAILURE` restart policy with a health check at `/healthz`.

### What was verified, and how

No Railway account, CLI, or API token exists in this environment (confirmed: no `railway` CLI installed, no `RAILWAY_TOKEN`, nothing in the credential manager for `railway.app`, unlike `github.com` which resolves fine) - so nothing above has been deployed or tested against real Railway infrastructure. Everything that could be verified without that access was:

- 17 new unit tests (`test_railway_service.py`): the scheduling decision across day/hour/month boundaries, that a failed or crashing subprocess is recorded in state rather than raised, that a run already in progress isn't started twice, the file server's behaviour before/after a file exists, correct content-type per file, and the `/run` token check (missing, wrong, and correct).
- A live smoke test of the actual entrypoint process (`python src/railway_service.py`, not just the unit-test harness's in-process server): confirmed `/healthz`, `/`, and the 404/403 paths over real HTTP, and let a real scheduled run fire on startup (correct behaviour for a service with no run recorded yet) - it hit this dev machine's already-known Cloudflare block on riparide.com (D3/D7/D12) and failed exactly as expected, while the HTTP server stayed fully responsive throughout and recorded the failure cleanly with no crash and no partial files written. The same was repeated for the manual `/run` trigger.
- File serving was separately verified against the real committed production snapshot (10,215 URLs): regenerated the real CSVs/xlsx locally (`run.py --offline-snapshot data/snapshot.json --skip-status --dry-run`), pointed a service instance at them, and confirmed both CSVs downloaded byte-identical (4,840 and 5,492 data rows, matching exactly) and the xlsx served with the correct content-type.

### What is NOT verified, and why

The parts of the Definition of Done that require an actual Railway deployment - a real scheduled execution, a real public stable URL, real Railway-runner reachability of riparide.com (this project has never actually confirmed Railway's specific network path works, only Railway's *pre-D12* incarnation and GitHub Actions' runners separately), a real volume surviving a real redeploy, and a side-by-side output comparison against a live GitHub Actions run - cannot be done from this environment. This needs one of: a `RAILWAY_TOKEN` for an existing or new Railway project, or direct access to the Railway dashboard to create the project/volume/env vars and share the resulting service URL back for verification.

### Rollback

`main` and `.github/workflows/monthly-refresh.yml` are untouched - GitHub Actions remains the sole production pipeline throughout. The pre-migration state is tagged `pre-railway-migration-github-actions-stable` on `main`, and this work lives entirely on the `railway-migration` branch until Railway access allows it to be tested for real and merged deliberately, not by default.
