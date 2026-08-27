# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A standalone Python job (stdlib-only except for one deliberate exception, see
below) that rebuilds Riparide's Google Ads Performance Max **page feed**
every month: it crawls riparide.com's sitemaps, labels every URL across six
taxonomy dimensions, diffs against last month's snapshot, validates the
result, writes two upload-ready CSVs plus a reviewable `.xlsx` report, and
emails all of it. Deployed on **GitHub Actions** (`.github/workflows/monthly-refresh.yml`)
as a scheduled job, independent of the actual Riparide site build. It used to
run on Railway — see DECISIONS.md D12 for why it moved and D7 for the one
thing about that move that still needs a live-run confirmation.

This repo is **deliberately separate** from `../escape-wizard` (the live
Escape Wizard quiz app — Next.js/Fastify monorepo, Vercel + Railway) and from
`../project-simon-client` (the original planning/scope repo). Different
product, different deploy target, different constraints (no third-party
dependencies at all, by design — see below). Do not merge configs, docs, or
conventions across them; treat this as its own project root.

Mechanical detail (running it, flags, config vars, deployment) lives in
[`README.md`](./README.md) — read that first. Every non-obvious decision, with
the evidence behind it, lives in [`DECISIONS.md`](./DECISIONS.md) — read that
before changing fetching, labelling, or region-naming logic, since several
things that look like bugs are deliberate and evidence-backed. A
plain-language snapshot for non-technical readers (e.g. a client update) is
[`PROJECT_STATUS.md`](./PROJECT_STATUS.md) — keep it in sync with reality when
you make a change significant enough to affect what it claims.

## Ground truth over assumption

Same rule as the sibling repos: riparide.com's real behavior (which slugs
exist, what a page title actually renders as, which param order 301s) takes
priority over anything that seems more sensible in the abstract. `config.py`
and `DECISIONS.md` both timestamp what was verified and when — if you change
fetching, labelling, or facet-URL logic, re-verify against the live site
rather than trusting the comment, since the site can change after the date
recorded there. D7 is a concrete example of why this matters: D3's original
conclusion ("urllib works, requests/curl don't") turned out to be *true but
incomplete* — a second network's `urllib` request got blocked outright, which
D3's testing never covered. Re-verifying from a genuinely different vantage
point is what caught that; assuming D3 covered every case would not have.

## Keep `DECISIONS.md` and this file honest

It's a log of decisions with their reasoning, not a static doc — treat a stale
entry as seriously as a bug. D2's "location comes from a supplied file" claim
was already found stale once (superseded by `enricher.py`'s page-title
parsing) and left uncorrected for a while; don't let that happen again. Before
touching an area DECISIONS.md discusses, check the claim against the current
code first.

## Non-negotiable technical constraints (from DECISIONS.md, don't relitigate without new evidence)

- **stdlib `urllib` only, no `requests`, no third-party HTTP client, for
  anything that talks to riparide.com.** Verified from a Railway container:
  `urllib` gets 200, `requests` and `curl` (same UA) get 403 (D3). This rule
  is specifically about the fetching layer, not the whole project — see the
  next point.
- **`openpyxl` is the one deliberate dependency, and it stays scoped to
  `report.py`** (D13). It never makes a network call, so it doesn't carry
  D3/D7's risk. Don't use it as precedent for adding another dependency
  anywhere that touches the network — that's a different risk entirely.
- **The block is not purely a client fingerprint — IP/ASN reputation is at
  least part of it** (D7). Don't assume "it worked from platform X" transfers
  to platform Y without testing. This is exactly why `monthly-refresh.yml`
  has a "check the site answers" step before doing any real work.
- **Facet query params must stay alphabetical**: `country`, `state`,
  `subcategories`, `type`. Any other order 301-redirects, and a page feed of
  redirects is a page feed of disapprovals in Google Ads. Facet URLs are now
  status-checked every run regardless of `--full-status` (D9) — don't
  reintroduce the gap where they were only checked on a manual flag.
- **Region labels are derived from the URL slug**, never hand-written, because
  a monthly automated job can't reproduce ad-hoc abbreviations. Ambiguous
  slugs (`north-coast`, `south-coast`, `central-coast` — each exists under both
  AU and US) get a state/country suffix (`config.AMBIGUOUS_REGION_SLUGS`,
  `labeller.region_label`). `labeller.find_region_collisions` re-checks this
  on every run.
- **A failed validation check blocks output entirely** (`validator.py`, called
  from `run.py` step 7) — a broken feed is treated as worse than a stale one.
  Don't add a bypass for this. This now also covers a feed whose row count
  collapsed versus last run (D11) — don't loosen `MIN_ROW_RATIO` without a
  real reason, it exists specifically to catch a silent network failure.
- **The snapshot is written only after a full successful run.** A failed run
  must leave the previous month's baseline untouched, or the next diff would
  be wrong. Preserve this ordering in `run.py` if you touch the run sequence.
- **State lives in git now, not a platform volume** (D12). `data/snapshot.json`,
  `data/snapshot.json.previous` and `data/location-cache.json` are
  deliberately un-ignored in `.gitignore` and get committed back by the
  workflow. Don't re-add them to `.gitignore` and don't treat them as
  build artifacts — they're the source of truth for next month's diff.

## Where things stand (as of this review, 27 Aug 2026)

Connected to `github.com/snr-growth/riparide-Page-Feeds-listings` and pushed
(the real history, 9 original commits, is preserved — this repo was
`git init`'d fresh locally at one point and had to be rebuilt onto the real
remote history rather than force-pushed over it; if you ever find local work
here with no `.git`, check `git log` on the actual GitHub repo before
assuming it's safe to treat as a fresh init again).

Fully implemented and unit-tested (100+ tests across `test_*.py`, plus
`prove_diff.py`, all run in CI on every push via
`.github/workflows/proof.yml`): sitemap fetch, status-checking (now including
every facet URL every run, D9), all six labelling dimensions + facet URL
generation, page-title location enrichment with a version-tagged cache,
optional attributes-file merge, snapshot diff, a validator that now also
guards against feed collapse (D11) and an automatic 6-monthly full-status
safety net (D11), a robots.txt/AdsBot-Google check (D10), CSV writer, an
`.xlsx` report (`report.py`, D13) committed to `reports/` and emailed
alongside the CSVs, and email delivery (Resend or SMTP, fails open with a
clear report line if unconfigured, plus `snapshot.json` attached as recovery
insurance).

Open items:

1. **The GitHub Actions migration's core network assumption is unverified**
   (D7, D12). Nothing has actually proven a GitHub-hosted runner can reach
   riparide.com — it's inferred from the old `build-feed.yml` having a
   reachability check, not demonstrated. **Run `monthly-refresh.yml` via
   `workflow_dispatch` once, for real, before trusting the schedule.** If the
   "Check the site answers" step fails, the whole migration needs rethinking.
2. **Verify GitHub Actions repository secrets are actually set**
   (`EMAIL_FROM`, `EMAIL_TO`, and either `RESEND_API_KEY` or the `SMTP_*`
   quartet). Missing config fails open (run completes, report says "email not
   sent") rather than failing the job.
3. **`data/listing-attributes.csv` doesn't exist yet.** Given `enricher.py`
   already covers most location needs from page titles, confirm with the
   client/SNR whether this file is still needed, and if so, whoever supplies
   it can now do so as a normal commit/PR to this repo instead of needing
   platform-level file access.
4. **`config.SEARCH_HEAD_TYPES` is an unconfirmed inference** (D8) — needs an
   explicit answer from SNR/the client before the Option A/B split goes live.
5. **No live production run has happened yet.** All URL-count figures in
   `config.py`/`DECISIONS.md` are from manual verification on 25 Aug 2026, not
   a real scheduled run.
6. **The old Railway cron service still needs to be paused/deleted by hand**
   once the GitHub Actions run is confirmed working, so the job doesn't run
   twice a month from two platforms. This repo has no access to Railway's
   dashboard to do that itself.
7. **If you add a new label/dimension to `config.py`, update `report.py`'s
   Label Taxonomy sheet too if it's not already generated generically** —
   most of that sheet is built by iterating `config` constants directly, but
   the boundary list is hand-written and can drift.
