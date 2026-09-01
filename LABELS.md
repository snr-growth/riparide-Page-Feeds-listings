# Understanding Your Page Feed Labels

Every month, the system looks at every page on riparide.com and tags it with
a set of labels — think of them as sticky notes that tell Google Ads what
each page is, where it is, and how it should (or shouldn't) be advertised.
This document walks through what those labels actually mean, in plain
language, so you can look at any label and understand exactly what it's
telling Google.

You don't need to be technical to read this. If you ever open the feed and
see something like:

```
PAGE_LISTING;GEO_AU;GEO_VIC;REG_GREAT_OCEAN_ROAD;TYPE_GLAMPING;PMAX_LONGTAIL
```

...this guide is what turns that into: *"This is a property listing, in
Australia, in Victoria, in the Great Ocean Road area, it's a glamping stay,
and there's nothing special holding it back from advertising."*

Each page gets a handful of these tags stitched together, one for each thing
that applies to it. A page only gets the tags that are relevant to it, so
most labels you'll see are shorter than the example above.

---

## 1. What kind of page is this?

Every page starts with a tag saying what it fundamentally *is*:

- **A property listing** — one specific place someone can stay
- **A story** — an editorial piece about a stay
- **An adventure** — a "things to do" page, not a place to book
- **A country, state, or region page** — a hub page like the Australia page, the Victoria page, or the Great Ocean Road page
- **A collection page** — a themed or destination-based grouping (e.g. a curated list of properties)
- **A filtered search page** — a page like "all glamping stays in Victoria," which we generate automatically so Google can send someone straight to the right filtered results instead of a single listing
- **A brand/informational page** — things like your About or Contact pages, which are deliberately left out of the feed entirely since there's nothing to advertise there

---

## 2. Where is it?

Every page carries a location, at whatever level of detail it has: country
(Australia, New Zealand, United States), and where relevant, a state
(Victoria, New South Wales, Washington, Oregon).

Beyond that, most pages also carry a specific **region** — the actual named
area, like "Yarra Valley" or "High Country." These are generated
automatically from the region's real name, so as new regions get added to
the site, they pick up a sensible label without anyone needing to update
anything by hand.

One small detail worth knowing: three region names happen to exist in two
different places (there's a "North Coast" in both New South Wales and
Oregon, for example). For those specific cases, we add the state or country
onto the label so the two don't get confused with each other. Every other
region is just its plain name.

---

## 3. What kind of stay is it?

Each listing gets tagged with its stay type — cabin, glamping, cottage,
treehouse, tiny house, and so on, pulled directly from the same categories
your own site uses to let people filter search results. There are 22 of
these in total, matching your site's existing filters exactly.

A handful of listings describe themselves in ways that don't quite match
those 22 categories — a beach house, a houseboat, a converted train
carriage, that kind of thing. Rather than forcing those into the nearest
official category (which could easily mislabel a listing), we give them
their own honest label instead.

And if a listing ever describes itself in a way nobody's seen before, the
system doesn't guess — it flags it in the monthly report as "seen but not
yet labelled," so it can be added properly rather than risking a wrong
guess slipping quietly into the feed.

---

## 4. What is the person looking for?

Beyond the basic stay type, some listings speak to a specific kind of trip:
romantic getaways, pet-friendly stays, off-grid escapes, farm stays, places
with a hot tub or sauna, group-friendly stays, luxury stays, or general
weekend getaways. These come straight from the wording already used in your
own page titles and URLs, so they reflect how the property is actually
described.

Four of these — **romantic, off-grid, pet-friendly, and getaway** — get
special treatment in the next section, because your own campaign
performance data showed Google Search ads doing noticeably better than
Performance Max specifically for these kinds of searches.

---

## 5. Where should this actually be advertised?

This is the label that matters most for how your ad spend gets used — it
decides which campaign a page is even eligible to appear in.

- **Most pages** are simply in Performance Max's normal, proven territory — no restrictions, business as usual.
- **A smaller set of pages** — the romantic, off-grid, pet-friendly, and getaway-themed ones mentioned above, plus a few of the most-searched stay types on the filtered search pages — are flagged so Search campaigns can take priority over Performance Max for them, since that's where the data says they perform better.
- **New Zealand pages** are held back from paid campaigns for now, while performance there is under review.
- **US pages** are held back entirely, since the US isn't currently a market you're advertising into.
- **Adventure pages** are held back too — they're editorial "things to do" content, not something to run ads against directly.

If any of these holds ever needs to change — say, NZ performance improves
and you want to switch it back on — that's a one-line change on our end,
not a rebuild.

---

## Where each page actually lands

Every page ends up in exactly one of three places: the **main feed**
(almost everything), the **adventures feed** (kept separate since it's a
different kind of content), or **left out entirely** (your brand and
informational pages, which have no place in a page feed anyway).

---

## Any questions?

If you ever look at a label and it's not obvious what it means, this
document should cover it — but if something looks off, or a stay type or
region seems to be missing a label it should have, that's worth flagging to
us directly rather than guessing. The system is built to report anything it
isn't confident about rather than make a silent guess, so a genuine gap is
usually a quick, deliberate fix once we know about it.
