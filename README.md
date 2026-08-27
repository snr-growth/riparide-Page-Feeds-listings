# Riparide page feed monthly refresh

Rebuilds the Riparide Performance Max page feed every month so it stays accurate without anyone maintaining it by hand.

Runs on a schedule, produces two upload ready CSV files, and emails a report of what changed.

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
| 8 | Write both CSV files |
| 9 | Save the new snapshot |
| 10 | Email the report with both files attached |

If any validation check fails the run stops before writing anything. A broken feed is worse than a stale one.

The only manual step left is uploading the two CSV files in Google Ads under Tools, Business data, Page feed.

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
  writer.py      CSV output
  emailer.py     report delivery, API key or SMTP
  run.py         the run itself
  prove_diff.py  proof that change detection works (see below)
  test_*.py      unit tests for the individual modules (see below)
DECISIONS.md     every decision, with its reason and evidence
PROJECT_STATUS.md  plain-language status snapshot for non-technical readers
```

No third party packages are used. See the note on client fingerprinting below.

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
merge, the location parser, the robots.txt/AdsBot check) live alongside them
as `test_*.py`. Run the whole suite with:

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
| `FEED_ATTRIBUTES_FILE` | `data/listing-attributes.csv` | optional supplied attributes |
| `FEED_MAX_STATUS_CHECKS` | `1500` | per run cap on status checks |
| `FEED_MAX_LOCATION_FETCHES` | `1200` | per run cap on pages read for location |
| `FEED_REQUEST_DELAY` | `0.15` | seconds between requests |
| `FEED_STATUS_WORKERS` | `6` | concurrent requests |
| `FEED_USER_AGENT` | a browser agent | see the note below |
| `EMAIL_FROM`, `EMAIL_TO` | none | sender, and recipients separated by commas |
| `RESEND_API_KEY` | none | email service route |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | none | SMTP route |

Without email settings the run still completes and reports that the email was not sent.

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

A second finding, from a residential/office IP on 27 August 2026: the exact same `urllib` client and browser user agent got a flat Cloudflare 403 on *every* URL, including `robots.txt`. That means the block is not purely a client-library fingerprint as first concluded — IP/ASN reputation is at least part of it. See DECISIONS.md D9 for what this means for where this job can run.

**Facet parameters must stay in alphabetical order** (`country`, `state`, `subcategories`, `type`). Any other order redirects, and a page feed of redirects is a page feed of disapprovals.

---

## Deployment

Runs on GitHub Actions (`.github/workflows/monthly-refresh.yml`), not Railway. See DECISIONS.md D11 for why.

| Item | Value |
|---|---|
| Schedule | `0 3 1 * *`, 03:00 UTC on the 1st of each month, plus manual dispatch any time |
| State persistence | `data/snapshot.json`, `data/snapshot.json.previous` and `data/location-cache.json` are committed back into this repo by the workflow after a successful run — no external volume |
| Concurrency | one refresh at a time (`concurrency: group: monthly-page-feed-refresh`), so a manual run can't race the scheduled one |
| Secrets required | `EMAIL_FROM`, `EMAIL_TO`, and either `RESEND_API_KEY` or the `SMTP_*` quartet, set as GitHub Actions repository secrets |
| Failure visibility | a failed run exits non-zero, which GitHub marks as a failed workflow run and emails repo watchers by default — independent of this project's own email delivery |

### Every run's checked URLs and email attachments

Both output CSVs are attached to the workflow's own artifact upload (90-day retention) and to the report email, along with `data/snapshot.json` itself — the latter purely as recovery insurance in case the repo's committed state is ever lost or reverted.
