#!/usr/bin/env python3
"""Look up missing DOIs on Crossref and add them to the .bib files.

For every entry without a `doi`, Crossref is searched with the title and the
first author. A DOI is added automatically only for a confident match: same
normalised title, first author's family name among the result's authors, and
year within one year. Near misses are listed for manual review in
data/crossref_report.json and are never applied.

    python3 scripts/crossref_dois.py --dry-run   # only report
    python3 scripts/crossref_dois.py             # add confident DOIs

Uses the public Crossref API (no key; one request per second).
"""
import argparse
import difflib
import html
import json
import re
import time
import urllib.parse
import urllib.request

from bibtools import (BIB_FILES, ROOT, ascii_fold, last_name, latex_to_text, normalize_title,
                      read_bib, split_authors, write_bib)

API = "https://api.crossref.org/works"
REPORT = ROOT / "data" / "crossref_report.json"
# Crossref record types that are never the paper itself.
SKIP_TYPES = {"peer-review", "component", "grant", "database", "dataset"}


def search(entry):
    authors = split_authors(entry.get("author"))
    params = {
        "query.bibliographic": latex_to_text(entry.get("title")),
        "rows": 5,
        "select": "DOI,title,author,issued,type,container-title",
    }
    if authors:
        params["query.author"] = last_name(authors[0])
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}",
                                 headers={"User-Agent": "score-following-bibliography/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["message"]["items"]
        except OSError:
            if attempt == 2:
                raise
            time.sleep(5)


def family(name):
    return re.sub(r"[^a-z]", "", ascii_fold(name).lower())


def item_title(item):
    """Crossref titles may contain HTML tags and (doubly) escaped entities."""
    title = (item.get("title") or [""])[0]
    return re.sub(r"<[^>]+>", "", html.unescape(html.unescape(title)))


def assess(entry, item):
    """Return (confident, similarity, year, author_ok) for a Crossref item."""
    title = item_title(item)
    similarity = difflib.SequenceMatcher(None, normalize_title(entry.get("title")), normalize_title(title)).ratio()
    year = (item.get("issued", {}).get("date-parts") or [[None]])[0][0]
    authors = split_authors(entry.get("author"))
    first = family(last_name(authors[0])) if authors else ""
    families = {family(a.get("family", "")) for a in item.get("author", [])}
    author_ok = bool(first) and any(first in f or (f and f in first) for f in families)
    year_ok = bool(year) and entry.get("year").isdigit() and abs(int(entry.get("year")) - year) <= 1
    confident = similarity == 1.0 and author_ok and year_ok and item.get("type") not in SKIP_TYPES
    return confident, similarity, year, author_ok


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="report only, do not change the .bib files")
    args = parser.parse_args()

    lists = {name: read_bib(path) for name, path in BIB_FILES.items()}
    used_dois = {e.get("doi").lower() for es in lists.values() for e in es if e.get("doi")}
    todo = [(name, e) for name, es in lists.items() for e in es if not e.get("doi")]
    print(f"{len(todo)} entries without DOI")

    applied, review = [], []
    for i, (name, entry) in enumerate(todo, 1):
        best = None
        for item in search(entry):
            confident, similarity, year, author_ok = assess(entry, item)
            if best is None or (confident, similarity) > best[0]:
                best = ((confident, similarity), item, year, author_ok)
        time.sleep(1)
        if not best:
            continue
        (confident, similarity), item, year, author_ok = best
        doi = item["DOI"]
        record = {"key": entry.key, "list": name, "doi": doi, "similarity": round(similarity, 3),
                  "type": item.get("type"), "year": year, "author_match": author_ok,
                  "title": latex_to_text(entry.get("title")), "crossref_title": item_title(item),
                  "venue": (item.get("container-title") or [""])[0]}
        if confident and doi.lower() not in used_dois:
            entry.fields["doi"] = doi
            used_dois.add(doi.lower())
            applied.append(record)
            print(f"[{i}/{len(todo)}] + {entry.key}: {doi}")
        elif similarity >= 0.85:
            review.append(record)
            print(f"[{i}/{len(todo)}] ? {entry.key}: {doi} (similarity {similarity:.2f}, "
                  f"author {'ok' if author_ok else 'differs'}, year {year})")

    REPORT.write_text(json.dumps({"applied": applied, "review": review}, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(applied)} DOIs {'found' if args.dry_run else 'added'}, {len(review)} to review "
          f"-> {REPORT.relative_to(ROOT)}")
    if not args.dry_run and applied:
        for name, entries in lists.items():
            write_bib(BIB_FILES[name], entries)


if __name__ == "__main__":
    main()
