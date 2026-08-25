# -*- coding: utf-8 -*-
"""Proof that the refresh notices what changed on the site.

Change detection is the whole point of the system, and waiting a month to
find out whether it works is not a test. This script takes a known list of
pages, makes a deliberate change to it, and checks that the comparison
reports exactly that change: no misses, and nothing invented.

Three cases are checked, because a change detector can fail in two opposite
directions and both matter:

    1. Nothing changed          -> it must report nothing
    2. Pages added and removed  -> it must report exactly those
    3. First ever run           -> everything counts as new

Run it with:

    python src/prove_diff.py

It reads the stored snapshot if one is present, so the numbers are real, and
it never writes to it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import store
import labeller

LINE = "=" * 70

# Pages invented for this test only, one per sitemap group so the labelling
# of each kind is exercised too. They are not on riparide.com, which is the
# point: the system has to spot them arriving. Every slug carries "test-" so
# it can never collide with a real page.
PRETEND_NEW = {
    "listings": [
        "https://www.riparide.com/au/vic/listings/test-new-cabin-in-the-pines",
        "https://www.riparide.com/au/nsw/listings/test-new-cottage-by-the-river",
    ],
    "destinations": [
        "https://www.riparide.com/au/vic/test-new-valley-region",
    ],
}

# Used only when no snapshot is stored, so the proof still runs on a fresh
# clone of the repository.
FALLBACK = {
    "listings": [
        "https://www.riparide.com/au/vic/listings/1152-country-house-retreat",
        "https://www.riparide.com/au/nsw/listings/884-hinterland-hideaway",
        "https://www.riparide.com/au/vic/listings/2210-forest-a-frame",
        "https://www.riparide.com/nz/listings/331-lakeside-cabin",
        "https://www.riparide.com/us/listings/77-cascade-treehouse",
        "https://www.riparide.com/au/nsw/listings/990-coastal-cottage",
        "https://www.riparide.com/au/vic/listings/1401-vineyard-studio",
        "https://www.riparide.com/au/nsw/listings/612-river-barn",
    ],
    "destinations": [
        "https://www.riparide.com/au/vic/great-ocean-road",
        "https://www.riparide.com/au/nsw/south-coast",
        "https://www.riparide.com/us/oregon/north-coast",
    ],
    "collections": [
        "https://www.riparide.com/au/nsw/collections/byron-bay",
        "https://www.riparide.com/au/vic/collections/daylesford",
    ],
}


def load_base():
    """The 'last month' page list. Real if a snapshot exists, else built in."""
    snap = store.load_snapshot()
    if snap:
        return {k: list(v) for k, v in snap["urls_by_group"].items()}, \
            "the stored snapshot taken at %s" % snap.get("taken_at", "unknown")
    return {k: list(v) for k, v in FALLBACK.items()}, \
        "a built in sample, because no snapshot is stored yet"


def total(groups):
    return sum(len(v) for v in groups.values())


def make_changed(base, remove_count=5):
    """Return a copy of base with some pages gone and some new ones added."""
    changed = {k: list(v) for k, v in base.items()}

    # Take the removals from the largest group so the test works whatever
    # the snapshot happens to contain.
    biggest = max(changed, key=lambda k: len(changed[k]))
    removed = changed[biggest][:remove_count]
    changed[biggest] = changed[biggest][remove_count:]

    already = {u for urls in base.values() for u in urls}
    added = []
    for group, urls in PRETEND_NEW.items():
        for u in urls:
            if u in already:
                raise SystemExit(
                    "test page %s already exists on the site, so it cannot "
                    "stand in for a new one. Change it in PRETEND_NEW." % u)
            changed.setdefault(group, []).append(u)
            added.append(u)
    return changed, removed, added


def show(name, expected, reported):
    ok = set(expected) == set(reported)
    print("  %-26s expected %-5d reported %-5d  %s"
          % (name, len(expected), len(reported), "correct" if ok else "WRONG"))
    return ok


def case_no_change(base):
    print(LINE)
    print("CASE 1  Nothing changed on the site")
    print("        A change detector that invents changes is as bad as one")
    print("        that misses them, so this is checked first.")
    print()
    d = store.diff(base, base)
    ok = show("added", [], d["added"]) & show("removed", [], d["removed"])
    same = d["unchanged_count"] == total(base)
    print("  %-26s expected %-5d reported %-5d  %s"
          % ("unchanged", total(base), d["unchanged_count"],
             "correct" if same else "WRONG"))
    print()
    print("  RESULT: %s" % ("PASS" if ok and same else "FAIL"))
    return ok and same


def case_real_change(base):
    print(LINE)
    print("CASE 2  Pages were added and removed")
    print()
    changed, removed, added = make_changed(base)
    print("  Deliberately removed %d page(s):" % len(removed))
    for u in removed:
        print("      %s" % u)
    print("  Deliberately added %d page(s):" % len(added))
    for u in added:
        print("      %s" % u)
    print()

    d = store.diff(base, changed)
    ok = show("added", added, d["added"]) & show("removed", removed, d["removed"])

    expected_unchanged = total(base) - len(removed)
    same = d["unchanged_count"] == expected_unchanged
    print("  %-26s expected %-5d reported %-5d  %s"
          % ("unchanged", expected_unchanged, d["unchanged_count"],
             "correct" if same else "WRONG"))

    # The added pages also have to come out of the labeller with usable
    # labels, otherwise detecting them would not help anyone.
    print()
    print("  Labels produced for the new pages:")
    labelled_ok = True
    for u in added:
        row = labeller.label_url(u, d["group_of"].get(u, "listings"))
        label = labeller.label_string(row)
        if not label:
            labelled_ok = False
        print("      %-58s %s" % (u.replace(cfg.REQUIRED_PREFIX, ""), label))
    print()
    print("  RESULT: %s" % ("PASS" if ok and same and labelled_ok else "FAIL"))
    return ok and same and labelled_ok


def case_first_run(base):
    print(LINE)
    print("CASE 3  The very first run, with nothing stored to compare against")
    print("        Every page must count as new, so none is skipped.")
    print()
    d = store.diff(None, base)
    ok = len(d["added"]) == total(base) and not d["removed"] and d["first_run"]
    print("  %-26s expected %-5d reported %-5d  %s"
          % ("added", total(base), len(d["added"]), "correct" if ok else "WRONG"))
    print("  %-26s expected %-5d reported %-5d  %s"
          % ("removed", 0, len(d["removed"]),
             "correct" if not d["removed"] else "WRONG"))
    print()
    print("  RESULT: %s" % ("PASS" if ok else "FAIL"))
    return ok


def main():
    base, source = load_base()
    print(LINE)
    print("CHANGE DETECTION PROOF")
    print("Riparide monthly page feed refresh")
    print()
    print("Last month's page list comes from %s." % source)
    print("It holds %d page(s) across %d sitemap group(s)."
          % (total(base), len(base)))
    print("Nothing on disk is modified by this script.")
    print()

    results = [case_no_change(base), case_real_change(base), case_first_run(base)]

    print(LINE)
    passed = sum(1 for r in results if r)
    print("OVERALL: %d of %d cases passed" % (passed, len(results)))
    print(LINE)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
