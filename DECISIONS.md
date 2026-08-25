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
