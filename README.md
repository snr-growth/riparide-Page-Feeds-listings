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
DECISIONS.md     every decision, with its reason and evidence
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

---

## Two things worth knowing before changing the fetching code

**The site fingerprints the client, not just the user agent.** Verified from one container on 25 August 2026, all sending the same browser user agent:

| Client | Result |
|---|---|
| `urllib`, standard library | 200 OK |
| `requests` library | 403 Forbidden |
| `curl` in that container | 403 Forbidden |

That is why this project deliberately uses only the standard library, and why it has no dependencies. Swapping in an HTTP client will break it.

**Facet parameters must stay in alphabetical order** (`country`, `state`, `subcategories`, `type`). Any other order redirects, and a page feed of redirects is a page feed of disapprovals.

---

## Deployment

Runs on Railway as a scheduled service.

| Item | Value |
|---|---|
| Schedule | `0 3 1 * *`, 03:00 UTC on the 1st of each month |
| Restart policy | `NEVER`, the job runs once and exits |
| Volume | mounted at `/data`, holds the snapshot and the location cache between runs |

Both are set in `railway.json`.
