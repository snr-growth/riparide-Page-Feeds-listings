# Understanding Your Page Feed Labels

Every month, each page on riparide.com gets tagged with a set of labels that
tell Google Ads what the page is, where it is, and how it should be
advertised. Below is what every code you'll see in the feed actually means.

A page's labels are joined together like this:

```
PAGE_LISTING;GEO_AU;GEO_VIC;REG_GREAT_OCEAN_ROAD;TYPE_GLAMPING;PMAX_LONGTAIL
```

which reads as: a property listing, in Australia, in Victoria, in the Great
Ocean Road area, a glamping stay, with no restriction on where it can
advertise.

---

## Page type — what the page is

| Code | Meaning |
|---|---|
| `PAGE_LISTING` | An individual property |
| `PAGE_STORY` | An editorial piece about a stay |
| `PAGE_ADVENTURE` | A "things to do" page, not a bookable stay |
| `PAGE_COUNTRY` | A country hub page — e.g. the Australia page |
| `PAGE_STATE` | A state hub page — e.g. the Victoria page |
| `PAGE_REGION` | A region hub page — e.g. the Great Ocean Road page |
| `PAGE_COLLECTION` | A themed or destination-based grouping of properties |
| `PAGE_COLLECTION_HUB` | The index page listing all collections for a country/state |
| `PAGE_FACET_TYPE` | An auto-generated page such as "all glamping stays in Victoria," so a search lands on the right filtered results instead of one listing |
| `PAGE_CORE` | A brand/info page — About, Contact, etc. — left out of the feed entirely |

## Location — country, state, region

| Code | Meaning |
|---|---|
| `GEO_AU` | Australia |
| `GEO_NZ` | New Zealand |
| `GEO_US` | United States |
| `GEO_VIC` | Victoria |
| `GEO_NSW` | New South Wales |
| `GEO_WA` | Washington State |
| `GEO_OR` | Oregon |
| `REG_...` | The specific region, e.g. `REG_YARRA_VALLEY`, `REG_HIGH_COUNTRY` — named directly after the real area, one for every region on the site |

## Stay type — what kind of place it is

| Code | Meaning |
|---|---|
| `TYPE_CABIN` | Cabin |
| `TYPE_GLAMPING` | Glamping |
| `TYPE_COTTAGE` | Cottage |
| `TYPE_TREEHOUSE` | Treehouse |
| `TYPE_TINY_HOUSE` | Tiny house |
| `TYPE_...` | Plus 17 more of your site's own filter categories (barn, farm, lodge, villa, yurt, and so on) |
| `TYPE_BEACH_HOUSE`, `TYPE_HOUSEBOAT`, etc. | A handful of stay types that don't match your 22 standard categories get their own honest label instead of being forced into the nearest match |

Anything genuinely new that doesn't match an existing label gets flagged for
review rather than guessed at.

## Intent — what kind of trip it is

This is the tag that captures *why* someone wants this specific stay, pulled
from the wording already used in the page's own title or URL:

| Code | Meaning |
|---|---|
| `INT_ROMANTIC` | Romantic getaway |
| `INT_OFFGRID` | Off-grid stay |
| `INT_PET_FRIENDLY` | Pet/dog-friendly |
| `INT_FARM_STAY` | Farm stay |
| `INT_HOT_TUB` | Has a hot tub |
| `INT_SAUNA` | Has a sauna |
| `INT_GROUPS` | Suited to groups |
| `INT_LUXURY` | Positioned as luxury |
| `INT_GETAWAY` | General weekend-getaway framing |

## Boundary — where it's allowed to advertise

This is the tag that actually controls which campaign a page can appear in:

| Code | Meaning |
|---|---|
| `PMAX_LONGTAIL` | No restriction — this is Performance Max's normal, default territory. Most pages carry this one. |
| `SEARCH_HEAD` | Romantic, off-grid, pet-friendly, and getaway-themed pages, where Search has been outperforming Performance Max |
| `NZ_REVIEW` | New Zealand — held back from paid campaigns |
| `US_HOLD` | United States — held back, not currently a paid market |
| `ADV_HOLD` | Adventure pages — held back, editorial content rather than something to advertise directly |

## Where each page ends up

Everything goes into the **main feed**, except adventure pages (their own
**separate feed**) and brand/info pages (**left out entirely**).
