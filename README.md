# Riparide page feed monthly refresh

Rebuilds the Riparide Performance Max page feed every month so it stays accurate without anyone maintaining it by hand.

Runs on a schedule and produces the feed in two parallel formats: two CSVs plus a reviewable `.xlsx` report as the **client-shared format** (emailed, human-facing, unchanged structurally since first built), and a Google Sheet as the **Google-Ads-facing format** (what Google Ads actually reads from, see DECISIONS.md D14). Both come from the exact same labelled data every run.

---

## What one run does

| Step | Action |
|---|---|
| 1 | Fetch the sitemap index and its six child sitemaps |
| 2 | Compare against last month's stored snapshot |
| 3 | Label every URL across the six taxonomy dimensions |
| 4 | Read location from each listing and story page, cached after the first read |
| 5 | Merge an optional supplied attributes file |
| 6 | Status check the changed URLs and drop anything that is not 200 |
| 7 | Run the validation checks |
| 8 | Write both CSV files, then the `.xlsx` report (client-shared format) |
| 8c | Update the Google Sheet Google Ads reads from (Google-Ads-facing format) |
| 9 | Save the new snapshot |
| 10 | Email the report with the CSVs, the `.xlsx` report, and the snapshot attached |

If any validation check fails the run stops before writing anything. A broken feed is worse than a stale one. A Sheets-update failure (step 8c) is the one exception to "nothing else happens" — the CSVs/xlsx/email still complete, since a good feed must never be lost over one delivery channel's hiccup, but the run still exits non-zero so it's never silently missed.

Once the Google Sheet is connected as the page feed's source in Google Ads (a one-time setup, see DECISIONS.md D14), there is no manual upload step left at all. Until then, the CSVs remain uploadable by hand under Tools, Business data, Page feed.

---

## Layout

```
src/
  config.py      every setting in one place
  fetcher.py     sitemap fetching and status checks
  labeller.py    URL to the six taxonomy dimensions
  enricher.py    reads location out of listing and story pages
  attributes.py  optional supplied attributes file
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
reports/         the monthly .xlsx report, committed here (see Deployment)
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

## Deployment

Runs as a single always-on Railway service (`src/railway_service.py` + `railway.json`), not GitHub Actions. See DECISIONS.md D12 for why it was on GitHub Actions before, and D15/D16 for the move to Railway and why.

**GitHub Actions has been fully removed** (`.github/workflows/` deleted on 31 August 2026) — see "Rolling back to GitHub Actions" below if this ever needs to be undone.

**Not yet actually deployed on live Railway infrastructure as of this removal** — no Railway account/CLI/token exists in the environment that built this, so nothing here has run against real Railway hardware yet. See "Deploying the Railway service" below for the exact steps needed once someone with Railway account access does this.

| Item | Value |
|---|---|
| Schedule | internal scheduler thread, checks every 30 minutes, fires on/after the 1st of the month at 03:00 UTC by default (`RAILWAY_RUN_DAY`/`RAILWAY_RUN_HOUR`), plus `POST /run?token=...` any time |
| State persistence | `data/snapshot.json`, `data/snapshot.json.previous`, `data/location-cache.json`, the output CSVs, and `reports/riparide-page-feed-report.xlsx` all live on a Railway volume (`FEED_DATA_DIR`) — no git commit-back, unlike the old GitHub Actions setup |
| Concurrency | a single in-process lock (`railway_service._lock`) refuses to start a second run while one is in progress, whether triggered by the schedule or manually |
| Secrets required | `RUN_TRIGGER_TOKEN` to authorize the manual trigger; `EMAIL_FROM`, `EMAIL_TO`, and either `RESEND_API_KEY` or the `SMTP_*` quartet for email; `GOOGLE_SERVICE_ACCOUNT_JSON` and `GOOGLE_SHEETS_SPREADSHEET_ID` for the Google Sheets update — all as Railway service variables |
| Failure visibility | a failed run is recorded in `railway-service-state.json` and visible at `GET /`; unlike GitHub Actions, nothing currently emails anyone automatically on a pipeline failure — this is a real gap versus the old setup, see D16 |

### Rolling back to GitHub Actions

Everything GitHub-Actions-based is fully recoverable from git history, not kept side-by-side in the live codebase:

- Tag `pre-railway-migration-github-actions-stable` marks the last commit where GitHub Actions was the complete, working, tested production pipeline (31 August 2026, before this removal).
- To restore it: check out that tag, or restore just `.github/workflows/monthly-refresh.yml` and `.github/workflows/proof.yml` from it into the current branch.

### Setting up the Google Sheet (one-time, client-side)

None of this can be done from inside this repo — it needs a Google account with access to Google Cloud and to the Google Ads account.

1. In Google Cloud Console, create (or reuse) a project, enable the **Google Sheets API**, and create a **service account**. Generate a JSON key for it and download the file.
2. Create the Google Sheet (or use an existing one you want to become the feed). Share it with **Editor** access to the service account's email address (it looks like `something@project-id.iam.gserviceaccount.com` — found in the downloaded JSON as `client_email`).
3. In this repo's GitHub settings → Secrets and variables → Actions, add:
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — paste the **entire contents** of the downloaded JSON file, unmodified.
   - `GOOGLE_SHEETS_SPREADSHEET_ID` — the long ID in the sheet's URL, between `/d/` and `/edit`.
4. In Google Ads, go to Tools → Business data → Page feed, and connect **that same Sheet** as the source (using whichever Google account manages Ads — it needs Editor access too, either because it owns the sheet or because you've shared it with that account as well).
5. Optional: also share the sheet as "Anyone with the link can view" if other people should be able to open it without being individually added. Not required for steps 2–4 to work.

After that, every monthly run keeps the sheet's `Page Feed - Core` tab (pinned as the first tab, since Google Ads only reads the first one) and `Page Feed - Adventures` tab up to date automatically — no more manual uploads.

### Deploying the Railway service (railway-migration branch, not yet live)

Requires a Railway account with an active Hobby or Pro plan (needed for volumes). None of this can be done from inside this repo:

1. Create a new Railway project from this repo, `railway-migration` branch. `railway.json` at the repo root configures the build/start commands and health check automatically.
2. Add a **Volume**, mounted at `/data` (Railway's dashboard, not `railway.json` — volumes aren't configurable as code). This is where `snapshot.json`, `location-cache.json`, the output CSVs, and the xlsx report all persist between runs and redeploys.
3. Set these service variables:
   - `FEED_DATA_DIR` = `/data`
   - `FEED_REPORT_DIR` = `/data/reports`
   - `RUN_TRIGGER_TOKEN` = a random secret, used to authorize `POST /run` (manual trigger, equivalent to `workflow_dispatch`)
   - The same email/Sheets secrets as the GitHub Actions setup above (`EMAIL_FROM`, `EMAIL_TO`, `RESEND_API_KEY` or `SMTP_*`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEETS_SPREADSHEET_ID`) if those delivery channels are still wanted — the underlying `run.py` is unchanged and reads them exactly the same way.
   - Optionally `RAILWAY_RUN_DAY` / `RAILWAY_RUN_HOUR` to change the schedule from its default (1st of the month, 03:00 UTC).
4. Once deployed, Railway assigns a public domain (or attach a custom one). The feed files are then available at:
   - `https://<your-railway-domain>/riparide-page-feed-core.csv`
   - `https://<your-railway-domain>/riparide-page-feed-adventures.csv`
   - `https://<your-railway-domain>/riparide-page-feed-report.xlsx`

   Point Google Ads' page feed source at the two CSV URLs directly (Business Data → Page feed → HTTP/HTTPS URL) instead of the Google Sheets connection, if delivering that way instead of/alongside Sheets.
5. Check `GET /` for the last run's status, and `GET /healthz` for the health check Railway itself polls.
6. To trigger a run immediately rather than waiting for the schedule: `curl -X POST "https://<your-railway-domain>/run?token=<RUN_TRIGGER_TOKEN>"`.

### Every run's outputs and email attachments

Both output CSVs and the `.xlsx` report are attached to the workflow's own artifact upload (90-day retention) and to the report email, along with `data/snapshot.json` itself — the latter purely as recovery insurance in case the repo's committed state is ever lost or reverted. Unlike the CSVs, the `.xlsx` report is also committed to the repo (`reports/`), so every month's report is a reviewable point in git history, not just a file that passed through an inbox.
