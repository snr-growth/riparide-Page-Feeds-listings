# Page Feed Label Reference

A plain-language guide to every label the feed can produce. Each page gets a
handful of these stitched together with semicolons — for example:

```
PAGE_LISTING;GEO_AU;GEO_VIC;REG_GREAT_OCEAN_ROAD;TYPE_GLAMPING;PMAX_LONGTAIL
```

reads as: a property listing, in Australia, in Victoria, in the Great Ocean
Road area, a glamping stay, with no restriction on where it can advertise.

---

## Page type — what the page is

| Label | Meaning |
|---|---|
| Listing | An individual property |
| Story | An editorial piece about a stay |
| Adventure | A "things to do" page, not a bookable stay |
| Country / State / Region page | A hub page, e.g. the Australia, Victoria, or Great Ocean Road page |
| Collection | A themed or destination-based grouping of properties |
| Filtered search page | An auto-generated page like "all glamping stays in Victoria," so a search can land on the right filtered results instead of one listing |
| Brand/info page | About, Contact, etc. — left out of the feed entirely |

## Location — country, state, region

Every page carries a country (Australia, New Zealand, United States), a
state where relevant (Victoria, New South Wales, Washington, Oregon), and
usually a specific region (e.g. Yarra Valley, High Country) generated
directly from the area's real name.

## Stay type — what kind of place it is

Cabin, glamping, cottage, treehouse, tiny house, and 18 others — the same 22
categories your own site's search filters already use. A handful of
listings describe themselves in ways that don't fit those 22 (beach house,
houseboat, converted train carriage) and get their own honest label instead
of being forced into the nearest match. Anything genuinely new gets flagged
for review rather than guessed at.

## Intent — what kind of trip it is

Romantic, off-grid, pet-friendly, farm stay, hot tub, sauna, group-friendly,
luxury, general getaway — pulled from the wording already used in the
page's own title or URL.

## Boundary — where it's allowed to advertise

| Label | Meaning |
|---|---|
| Standard (no restriction) | Performance Max's normal, proven territory |
| Search-priority | Romantic, off-grid, pet-friendly, and getaway-themed pages, where Search has been outperforming Performance Max |
| New Zealand — held back | Not currently running in paid campaigns |
| United States — held back | Not currently a paid market |
| Adventure — held back | Editorial content, not something to run ads against |

**Note on the New Zealand and US holds**: I could not find a documented,
sourced reason for these in this project's records — worth confirming with
whoever set this rule originally before repeating a specific justification
to the client. Happy to add it here once confirmed.

## Which feed it lands in

Everything goes into the **main feed**, except adventure pages (their own
**separate feed**) and brand/info pages (**left out entirely**).
