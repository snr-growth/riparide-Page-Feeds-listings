# Riparide page feed monthly refresh

Rebuilds the Riparide Performance Max page feed every month so it stays accurate without anyone maintaining it by hand.

Runs on a schedule (currently: a Railway service, see Deployment below) and
produces two CSVs plus a reviewable `.xlsx` report every run. The CSVs are
hosted at stable URLs Google Ads can pull directly (Business Data → Page
feed → HTTP/HTTPS source) — this is the confirmed, live delivery path as of
1 September 2026, which is when the very first fully automatic scheduled
run succeeded with no one watching it. A Google Sheets delivery path also
exists in the code (`sheets.py`, DECISIONS.md D14) as an alternative, but
it was deprioritized in favour of the Railway-hosted CSVs and is not
currently configured — see "Setting up the Google Sheet" below only if you
specifically want that path instead.

---

## What one run does

| Step | Action |
|---|---|
| 1 | Fetch the sitemap index and its six child sitemaps |
| 2 | Compare against last month's stored snapshot |
| 3 | Label every URL across the six taxonomy dimensions, then add the built stay-type facet URLs and search-page URLs (`PAGE_SEARCH`: all stays, pet-friendly, one per region) |
| 4 | Read location from each listing and story page, cached after the first read. A story page also names the one listing it features, and the story takes that listing's stay type |
| 5 | Merge an optional supplied attributes file |
| 5b | Read Riparide's open stories feed (`/public_api/stories.csv`) for each market and take each story's intents from the platform collections it belongs to (Pet Friendly Escapes, Outdoor Baths and so on). A failed fetch is reported and the run carries on |
| 6 | Status check the changed URLs plus every facet and search URL, and drop anything that is not 200 |
| 7 | Run the validation checks |
| 8 | Write both CSV files, then the `.xlsx` report — these get served directly at stable URLs by the Railway service (see Deployment) |
| 8c | Update the Google Sheet, only if the Sheets delivery path is configured (it currently isn't — see the intro above) |
| 9 | Save the new snapshot |
| 10 | Email the report with the CSVs, the `.xlsx` report, and the snapshot attached |

If any validation check fails the run stops before writing anything. A broken feed is worse than a stale one. A Sheets-update failure (step 8c) is the one exception to "nothing else happens" — the CSVs/xlsx/email still complete, since a good feed must never be lost over one delivery channel's hiccup, but the run still exits non-zero so it's never silently missed.

Once Google Ads is pointed at the Railway-hosted CSV URLs as the page feed's source (Tools → Business data → Page feed → HTTP/HTTPS source, a one-time setup — confirm with whoever manages the Ads account whether this step has actually been done), there is no manual upload step left at all.

---

## Layout

```
src/
  config.py      every setting in one place
  fetcher.py     sitemap fetching and status checks
  labeller.py    URL to the six taxonomy dimensions
  enricher.py    reads location out of listing and story pages
  attributes.py  optional supplied attributes file
  catalog.py     intents and region for stories, from the platform's stories feed
  store.py       snapshot storage and the month to month diff
  validator.py   the pre upload checks
  writer.py      CSV output (client-shared format)
  report.py      the .xlsx report - Summary, QA Checks, Label Taxonomy, both feeds (client-shared format)
  sheets.py      writes the feed into a Google Sheet (Google-Ads-facing format, D14)
  emailer.py     report delivery, API key or SMTP
  run.py         the run itself
  prove_diff.py  proof that change detection works (see below)
  test_*.py      unit tests for the individual modules (see below)
DECISIONS.md     every decision, with its reason and evidence
PROJECT_STATUS.md  plain-language status snapshot for non-technical readers
LABELS.md        plain-English reference for every label the feed can produce
reports/         local dev output only — in production this lives on the Railway volume, not git (see Deployment). The copy committed here is a frozen snapshot from the last GitHub Actions run (28 Aug 2026) and won't update.
```

No third party packages are used anywhere that talks to riparide.com — see
the note on client fingerprinting below. `openpyxl` and `google-auth` (see
`requirements.txt`) are the two deliberate exceptions: `report.py` uses
openpyxl purely to build a local `.xlsx` file, and `sheets.py` uses
google-auth purely to sign a request to Google's own API — neither ever
touches riparide.com. See DECISIONS.md D13 and D14.

---

## Running it

```
python src/run.py
```

Useful flags while testing:

| Flag | Effect |
|---|---|
| `--dry-run` | do everything except writing the snapshot and sending email |
| `--skip-status` | skip the HTTP status checks |
| `--full-status` | status check every URL, not only the changed ones |
| `--skip-location` | skip reading location from pages |
| `--skip-catalog` | skip the stories feed (step 5b) |
| `--offline-snapshot PATH` | use a saved URL list instead of fetching |

---

## Proving that change detection works

```
python src/prove_diff.py
```

Noticing what changed is the point of the system, so it can be checked on
demand rather than waited a month for. The script takes a known page list,
changes it deliberately, and confirms the comparison reports exactly that
change: nothing changed must report nothing, an added and removed set must be
reported exactly, and a first run must count every page as new. Added pages
are also put through the labeller. It reads the stored snapshot when one is
present, and writes nothing.

Unit tests for the individual modules (labelling, validation, the attributes
merge, the location parser, the robots.txt/AdsBot check, the Google Sheets
integration) live alongside them as `test_*.py` — the Sheets tests use a
throwaway RSA key and a mocked transport, no real Google credentials or
network access needed. Run the whole suite with:

```
cd src
python -m unittest discover -p "test_*.py"
```

Both this and `prove_diff.py` run automatically on every push in
`.github/workflows/proof.yml`.

---

## Configuration

All optional except the email settings.

| Variable | Default | Purpose |
|---|---|---|
| `FEED_DATA_DIR` | `data` | where the snapshot and cache live |
| `FEED_OUTPUT_DIR` | `data/output` | where the CSV files are written |
| `FEED_REPORT_DIR` | `reports` | where the `.xlsx` report is written |
| `FEED_ATTRIBUTES_FILE` | `data/listing-attributes.csv` | optional supplied attributes |
| `FEED_CATALOG_MARKETS` | `VIC,NSW` | markets read from the stories feed, comma separated |
| `FEED_MAX_STATUS_CHECKS` | `1500` | per run cap on status checks |
| `FEED_MAX_LOCATION_FETCHES` | `1200` | per run cap on pages read for location |
| `FEED_REQUEST_DELAY` | `0.15` | seconds between requests |
| `FEED_STATUS_WORKERS` | `6` | concurrent requests |
| `FEED_USER_AGENT` | a browser agent | see the note below |
| `EMAIL_FROM`, `EMAIL_TO` | none | sender, and recipients separated by commas |
| `RESEND_API_KEY` | none | email service route |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | none | SMTP route |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | none | full contents of the service-account key file, see D14 |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | none | the spreadsheet's ID (from its URL) |

Without email settings the run still completes and reports that the email was not sent. Same for the two `GOOGLE_*` settings and the Sheets update — see DECISIONS.md D14 for the one-time setup needed (service account, sheet sharing) before these can be filled in.

Two safety behaviours are set in `config.py` rather than by environment
variable, since they're policy rather than per-environment config:
`FULL_STATUS_MONTHS` (default January and July) forces a full status check
every 6 months regardless of flags, and `MIN_ROW_RATIO` (default 0.5) fails
validation — writing nothing — if a feed's row count falls below half of
last run's, which is what catches a run where the site was unreachable
instead of letting it silently ship a near-empty feed.

---

## Two things worth knowing before changing the fetching code

**The site fingerprints the client, not just the user agent — and possibly the origin IP too.** Verified from a Railway container on 25 August 2026, all sending the same browser user agent:

| Client | Result |
|---|---|
| `urllib`, standard library | 200 OK |
| `requests` library | 403 Forbidden |
| `curl` in that container | 403 Forbidden |

That is why this project deliberately uses only the standard library, and why it has no dependencies. Swapping in an HTTP client will break it.

A second finding, from a residential/office IP on 27 August 2026: the exact same `urllib` client and browser user agent got a flat Cloudflare 403 on *every* URL, including `robots.txt`. That means the block is not purely a client-library fingerprint as first concluded — IP/ASN reputation is at least part of it. See DECISIONS.md D7 for what this means for where this job can run.

**Facet parameters must stay in alphabetical order** (`country`, `state`, `subcategories`, `type`). Any other order redirects, and a page feed of redirects is a page feed of disapprovals.

---

## Meta catalogue feed

A second, daily job (`src/meta_feed.py`, DECISIONS.md D21) rebuilds Riparide's four Meta catalogue feeds so that each item's `link` opens a riparide.com **search-results page** that matches the stay and shows at least 6 stays, instead of the stay's own page.

**What it does, every day:**

1. Downloads the four client feeds: `https://www.riparide.com/public_api/{listings,stories}.csv?market={VIC,NSW}`.
2. Joins each item (`listing_106`, `story_47`) to the labels the monthly PMax run wrote to `riparide-page-feed-core.csv` (region `REG_*`, stay type `TYPE_*`). Region labels become site slugs through the region-hub rows of the same file (`/au/<state>/<slug>`, never landmark pages). An item newer than the monthly labels is labelled on day one from its own page title ("Glamping for Rent in Halls Gap, Grampians, VIC, AU"), the same parser the monthly run uses; a new story takes its featured listing's stay type. Each such page is read once and cached in `meta-new-pages-cache.json` until the monthly run labels it. A page that can't be read is retried the next day.
3. **Pet-friendly is off** (client decision, 19 Nov 2026): no item is treated as pet-friendly and no pet searches are made, so every item uses the ordinary ladder below. Setting `META_PET=on` brings it back. When on, the job works out which stays are pet-friendly, since the feeds do not say: the ids shown by the site's own `petFriendly=true` searches (a search page only shows its first 24 results and cannot be paged, so the job searches per state, then per region hub, then per region hub and stay type for regions with more than 24; a Story card counts for both the story and its featured listing), stories whose `custom_label_4` holds the `Pet Friendly Escapes` collection, and the `INT_PET_FRIENDLY` label. The report's `pet` section shows coverage against the site's pet total per state. The counts seen while harvesting are reused, not fetched twice.
4. Counts the results of every candidate search live, and picks the first rung with at least `META_MIN_RESULTS` results:
   - pet-friendly stay: region + type + pet → region + pet → region + type → region → state + pet → state
   - other stay: region + type → region → state + type → state
   - a stay whose own page could not be read or names no location: state
   - type rungs only when the stay type is one of the site's 22 filters; an unknown count never wins; if even the state count is unknown the original link is kept.
5. Writes four CSVs that are identical to the inputs (same columns, order, rows) except `link` and `applink.ios_url`, plus `meta-feed-report.json` (rung counts, items labelled from their own page, items left unlabelled, pet coverage, errors).

A feed that fails to download or validate keeps yesterday's file and the report says so. The job fails as a whole only when the PMax core CSV is missing or all four feeds failed. Pet harvesting failing never fails the feed; it is built without pet rungs.

**URLs** (served by the same Railway service, `Cache-Control: no-store`):

| Feed | URL |
|---|---|
| Listings, VIC | https://feed-refresh-production.up.railway.app/meta-listings-vic.csv |
| Listings, NSW | https://feed-refresh-production.up.railway.app/meta-listings-nsw.csv |
| Stories, VIC | https://feed-refresh-production.up.railway.app/meta-stories-vic.csv |
| Stories, NSW | https://feed-refresh-production.up.railway.app/meta-stories-nsw.csv |
| Run report | https://feed-refresh-production.up.railway.app/meta-feed-report.json |

**Schedule:** once per UTC day, on the first scheduler poll (every 30 minutes) at or after `META_RUN_HOUR` (default 18 UTC, about 5am AEDT / 4am AEST). It shares the monthly run's lock: if the monthly PMax run is going, the Meta job waits for the next poll. On the 1st of the month the monthly run goes first, so the Meta job uses fresh labels. `GET /` shows the last Meta run (`last_meta_run`). Manual run: `curl -X POST "https://feed-refresh-production.up.railway.app/run-meta?token=<RUN_TRIGGER_TOKEN>"` (same token as `/run`, redacted from logs the same way).

**Environment variables** (all optional):

| Variable | Default | Meaning |
|---|---|---|
| `META_RUN_HOUR` | `18` | UTC hour from which the daily run fires |
| `META_MIN_RESULTS` | `6` | minimum results a landing search must show |
| `META_MAX_ORIGINAL_RATIO` | `0.5` | a feed where more than this share of rows had to keep their original link (counts unknown, site not answering) is not written; yesterday's file stays |
| `META_MAX_PAGE_FETCHES` | `300` | per-run cap on reading new pages that the monthly labels don't cover yet |
| `META_PAGE_DELAY` | `0.5` | seconds between those page reads |
| `META_PET` | `off` | `on` turns pet-friendly landing pages back on (client chose to skip them, 19 Nov 2026) |
| `META_PET_DELAY` | `1.0` | seconds between pet-harvesting requests |
| `META_SOURCE_URL` | `https://www.riparide.com/public_api/{kind}.csv?market={market}` | input feed URL template |

Run it locally (offline, from saved files): `python src/meta_feed.py --offline-feeds DIR --core CORE.csv --counts-json COUNTS.json --out DIR`. `DIR` holds `listings_VIC.csv`, `listings_NSW.csv`, `stories_VIC.csv`, `stories_NSW.csv`.

**Client's one-time setup in Meta Commerce Manager** (we have no Meta access): for each of the four catalogues, open Commerce Manager → the catalogue → **Catalogue → Data sources → Add items → Data feed → Use a URL** (or edit the existing scheduled feed's URL), enter the matching URL from the table above, choose **Scheduled feed**, set it to repeat **daily** (a time after about 6am AEDT so the day's file is ready), currency AUD, and save. Run "Request update now" once and check the upload shows no errors. Item ids are unchanged, so existing ads and product sets keep working.

**Caveat — A/B test it before rolling out:** Meta describes the `link` field as the URL of the product's own page. Sending people to a search page is a deliberate deviation. It may change how Meta reviews or optimises the ads, so run it as a test (one catalogue or one ad set against the original feed) before switching every campaign.

---

## Deployment

Runs as a single always-on Railway service (`src/railway_service.py` + `railway.json`), not GitHub Actions. See DECISIONS.md D12 for why it was on GitHub Actions before, and D15/D16 for the move to Railway and why.

**GitHub Actions has been fully removed** (`.github/workflows/` deleted on 31 August 2026) — see "Rolling back to GitHub Actions" below if this ever needs to be undone.

**Confirmed live in production.** The first fully automatic scheduled run (no one triggering it manually) succeeded on 1 September 2026 — see "Deploying the Railway service" below if you need to redeploy this from scratch (e.g. moving it to a new Railway account as part of a handover).

| Item | Value |
|---|---|
| Schedule | internal scheduler thread, checks every 30 minutes, fires on/after the 1st of the month at 03:00 UTC by default (`RAILWAY_RUN_DAY`/`RAILWAY_RUN_HOUR`), plus `POST /run?token=...` any time |
| State persistence | `data/snapshot.json`, `data/snapshot.json.previous`, `data/location-cache.json`, the output CSVs, and `reports/riparide-page-feed-report.xlsx` all live on a Railway volume (`FEED_DATA_DIR`) — no git commit-back, unlike the old GitHub Actions setup |
| Concurrency | a single in-process lock (`railway_service._lock`) refuses to start a second run while one is in progress, whether triggered by the schedule or manually |
| Secrets required | `RUN_TRIGGER_TOKEN` to authorize the manual trigger; `EMAIL_FROM`, `EMAIL_TO`, and either `RESEND_API_KEY` or the `SMTP_*` quartet for email. `GOOGLE_SERVICE_ACCOUNT_JSON`/`GOOGLE_SHEETS_SPREADSHEET_ID` only if using the optional Sheets path instead of/alongside the CSV URLs — not currently set. All as Railway service variables. |
| Failure visibility | a failed run is recorded in `railway-service-state.json` and visible at `GET /`; unlike GitHub Actions, nothing currently emails anyone automatically on a pipeline failure — this is a real gap versus the old setup, see D16. **Check `GET /` yourself after the 1st of each month** until this is closed. |

### Rolling back to GitHub Actions

Everything GitHub-Actions-based is fully recoverable from git history, not kept side-by-side in the live codebase:

- Tag `pre-railway-migration-github-actions-stable` marks the last commit where GitHub Actions was the complete, working, tested production pipeline (31 August 2026, before this removal).
- To restore it: check out that tag, or restore just `.github/workflows/monthly-refresh.yml` and `.github/workflows/proof.yml` from it into the current branch.

### Deploying the Railway service (this is the live, confirmed path)

Requires a Railway account with an active Hobby or Pro plan (needed for volumes). None of this can be done from inside this repo — it needs Railway dashboard access.

1. Create a new Railway project from this repo, **`main` branch** (not `railway-migration` — that branch was merged into `main` on 31 August 2026 and can be deleted). `railway.json` at the repo root configures the build/start commands and health check automatically.
2. Add a **Volume**, mounted at `/data` (Railway's dashboard, not `railway.json` — volumes aren't configurable as code). This is where `snapshot.json`, `location-cache.json`, the output CSVs, and the xlsx report all persist between runs and redeploys.
3. Set these service variables:
   - `FEED_DATA_DIR` = `/data`
   - `FEED_REPORT_DIR` = `/data/reports`
   - `RUN_TRIGGER_TOKEN` = a random secret, used to authorize `POST /run` (manual trigger)
   - `EMAIL_FROM`, `EMAIL_TO`, `RESEND_API_KEY` for the report email (currently configured on the live service)
   - Optionally `RAILWAY_RUN_DAY` / `RAILWAY_RUN_HOUR` to change the schedule from its default (1st of the month, 03:00 UTC)
   - Add `GOOGLE_SERVICE_ACCOUNT_JSON`/`GOOGLE_SHEETS_SPREADSHEET_ID` only if you also want the optional Sheets path below — not required for the CSV URLs to work
4. Once deployed, Railway assigns a public domain (or attach a custom one). The feed files are then available at, for example:
   - `https://<your-railway-domain>/riparide-page-feed-core.csv`
   - `https://<your-railway-domain>/riparide-page-feed-adventures.csv`
   - `https://<your-railway-domain>/riparide-page-feed-report.xlsx`

   Point Google Ads' page feed source at the two CSV URLs directly (Business Data → Page feed → HTTP/HTTPS URL). **Confirm with whoever manages the Ads account whether this connection has actually been made** — the feed being live doesn't guarantee Ads has been pointed at it yet.
5. Check `GET /` for the last run's status, and `GET /healthz` for the health check Railway itself polls.
6. To trigger a run immediately rather than waiting for the schedule: `curl -X POST "https://<your-railway-domain>/run?token=<RUN_TRIGGER_TOKEN>"`.

### Setting up the Google Sheet instead (optional, not currently used)

The feed also supports writing into a Google Sheet as an alternative or additional delivery path (`sheets.py`, DECISIONS.md D14) — not currently configured, since the Railway-hosted CSV URLs above are the path actually in use. Only follow this if you specifically want Sheets instead of (or alongside) the CSV URLs. None of this can be done from inside this repo — it needs a Google account with access to Google Cloud and to the Google Ads account.

1. In Google Cloud Console, create (or reuse) a project, enable the **Google Sheets API**, and create a **service account**. Generate a JSON key for it and download the file.
2. Create the Google Sheet (or use an existing one you want to become the feed). Share it with **Editor** access to the service account's email address (it looks like `something@project-id.iam.gserviceaccount.com` — found in the downloaded JSON as `client_email`).
3. Set `GOOGLE_SERVICE_ACCOUNT_JSON` (the entire contents of the downloaded JSON file, unmodified) and `GOOGLE_SHEETS_SPREADSHEET_ID` (the long ID in the sheet's URL, between `/d/` and `/edit`) as Railway service variables.
4. In Google Ads, go to Tools → Business data → Page feed, and connect **that same Sheet** as the source (using whichever Google account manages Ads — it needs Editor access too, either because it owns the sheet or because you've shared it with that account as well).
5. Optional: also share the sheet as "Anyone with the link can view" if other people should be able to open it without being individually added. Not required for steps 2–4 to work.

After that, every monthly run keeps the sheet's `Page Feed - Core` tab (pinned as the first tab, since Google Ads only reads the first one) and `Page Feed - Adventures` tab up to date automatically.

### Every run's outputs and email attachments

Both output CSVs and the `.xlsx` report are attached to the workflow's own artifact upload (90-day retention) and to the report email, along with `data/snapshot.json` itself — the latter purely as recovery insurance in case the repo's committed state is ever lost or reverted. Unlike the CSVs, the `.xlsx` report is also committed to the repo (`reports/`), so every month's report is a reviewable point in git history, not just a file that passed through an inbox.
