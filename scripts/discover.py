#!/usr/bin/env python3
"""Find candidate papers via OpenAlex and propose them for the Unverified list.

1. Every entry of the core and related lists is looked up in OpenAlex (by DOI,
   else by exact title); matches are cached in data/openalex_ids.json.
2. All works published since --since that cite at least one core entry are
   collected, together with works matching a few title searches.
3. Each candidate is scored: +2 for each core entry it cites, +1 for each
   related entry, +3 if its title contains a score-following phrase.
4. Candidates not yet in any .bib file are written to data/candidates.json
   (a review report); with --add, those scoring at least --min-score are
   appended to ScoreFollowing-Unverified.bib with suggested keywords.

    python3 scripts/discover.py --since 2025-01-01            # report only
    python3 scripts/discover.py --since 2025-01-01 --add      # also add to Unverified

Uses only the standard library and the OpenAlex API. Requests without an API
key share a tiny daily budget per IP address, so get a free key at
https://help.openalex.org/api/authentication/ and put OPENALEX_API_KEY=... into
~/.config/openalex/credentials (or set the environment variable).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from bibtools import BIB_FILES, ROOT, Entry, latex_to_text, normalize_title, read_bib, write_bib
from zotero_import import make_key, suggest_keywords

API = "https://api.openalex.org"
CACHE = ROOT / "data" / "openalex_ids.json"
REPORT = ROOT / "data" / "candidates.json"

TITLE_SEARCHES = ["score following", "music alignment real-time", "music tracking real-time",
                  "automatic accompaniment", "audio-to-score alignment", "online time warping music",
                  "lyrics alignment real-time", "page turning music"]
TITLE_PHRASE = re.compile(r"score[- ]follow|music(al)? (performance )?(tracking|alignment|following)"
                          r"|audio[- ]to[- ]score|accompani|real[- ]time.*align|on-?line.*align"
                          r"|page[- ]turn|opera tracking|lyrics? alignment", re.I)

TYPE_MAP = {"article": "article", "review": "article", "preprint": "misc", "book-chapter": "incollection",
            "dissertation": "phdthesis", "book": "book", "report": "techreport"}


def api_key():
    if os.environ.get("OPENALEX_API_KEY"):
        return os.environ["OPENALEX_API_KEY"]
    path = Path.home() / ".config" / "openalex" / "credentials"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip().startswith("OPENALEX_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


class BudgetExhausted(Exception):
    pass


def get(path, params):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    headers = {"Authorization": f"Bearer {KEY}"} if KEY else {}
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as err:
            if err.code == 429 and int(err.headers.get("Retry-After") or 0) > 60:
                raise BudgetExhausted(json.loads(err.read() or b"{}").get("message", "rate limit exceeded"))
            if err.code not in (429, 500, 502, 503) or attempt == 3:
                raise
            time.sleep(2 ** attempt)


def get_all(path, params, limit=2000):
    """Cursor-paginate through a works listing."""
    params, results, cursor = dict(params, per_page=200), [], "*"
    while cursor and len(results) < limit:
        page = get(path, dict(params, cursor=cursor))
        results.extend(page["results"])
        cursor = page["meta"].get("next_cursor")
        if not page["results"]:
            break
    return results


def resolve_ids(entries):
    """Map citation key -> OpenAlex work id, using and updating the cache."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [e for e in entries if e.key not in cache]
    with_doi = [e for e in todo if e.get("doi")]
    try:
        _resolve(todo, with_doi, cache)
    finally:  # keep whatever was resolved, so a rerun continues where this one stopped
        CACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=1) + "\n")
    return {k: v.rsplit("/", 1)[-1] for k, v in cache.items() if v}


def _resolve(todo, with_doi, cache):
    for i in range(0, len(with_doi), 50):
        batch = with_doi[i:i + 50]
        found = get("/works", {"filter": "doi:" + "|".join(e.get("doi") for e in batch),
                               "select": "id,doi", "per_page": 50})["results"]
        by_doi = {w["doi"].lower().removeprefix("https://doi.org/"): w["id"] for w in found if w.get("doi")}
        for e in batch:
            cache[e.key] = by_doi.get(e.get("doi").lower())
    for e in todo:
        if cache.get(e.key):
            continue
        title = latex_to_text(e.get("title"))
        query = re.sub(r"[,:|]", " ", title)
        found = get("/works", {"filter": f"title.search:{query}", "select": "id,title,publication_year",
                               "per_page": 5})["results"]
        cache[e.key] = next((w["id"] for w in found if w.get("title")
                             and normalize_title(w["title"]) == normalize_title(e.get("title"))), None)
        time.sleep(0.1)


def to_entry(work):
    """Build a BibTeX entry from an OpenAlex work."""
    loc = work.get("primary_location") or {}
    source = (loc.get("source") or {}).get("display_name", "")
    kind = TYPE_MAP.get(work.get("type"), "misc")
    if kind == "article" and (loc.get("source") or {}).get("type") == "conference":
        kind = "inproceedings"
    fields = {
        "author": " and ".join(
            (lambda n: f"{n[-1]}, {' '.join(n[:-1])}" if len(n) > 1 else n[0])(a["author"]["display_name"].split())
            for a in work.get("authorships", []) if a.get("author", {}).get("display_name")) or "Anonymous",
        "title": work.get("title") or work.get("display_name") or "",
        "year": str(work.get("publication_year") or ""),
    }
    if source:
        fields["booktitle" if kind in ("inproceedings", "incollection") else
               "journal" if kind == "article" else "note"] = source
    if work.get("doi"):
        fields["doi"] = work["doi"].removeprefix("https://doi.org/")
    elif loc.get("landing_page_url"):
        fields["url"] = loc["landing_page_url"]
    return Entry(kind, "", {k: v.replace("{", "").replace("}", "") for k, v in fields.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--since", required=True, help="only works published on/after this date (YYYY-MM-DD)")
    parser.add_argument("--add", action="store_true", help="append candidates to the Unverified list")
    parser.add_argument("--min-score", type=int, default=5, help="minimum score for --add (default 5)")
    args = parser.parse_args()

    lists = {name: read_bib(path) for name, path in BIB_FILES.items()}
    known = [e for entries in lists.values() for e in entries]
    known_titles = {normalize_title(e.get("title")) for e in known}
    known_dois = {e.get("doi").lower() for e in known if e.get("doi")}

    ids = resolve_ids(lists["core"] + lists["related"])
    core_ids = {ids[e.key] for e in lists["core"] if e.key in ids}
    related_ids = {ids[e.key] for e in lists["related"] if e.key in ids}
    print(f"OpenAlex matches: {len(core_ids)}/{len(lists['core'])} core, "
          f"{len(related_ids)}/{len(lists['related'])} related")

    select = ("id,doi,title,display_name,publication_year,publication_date,type,authorships,"
              "primary_location,referenced_works,cited_by_count")
    date_filter = f"from_publication_date:{args.since}"
    works = {}
    seeds = sorted(core_ids)
    for i in range(0, len(seeds), 50):
        for w in get_all("/works", {"filter": f"cites:{'|'.join(seeds[i:i + 50])},{date_filter}", "select": select}):
            works[w["id"]] = w
    for query in TITLE_SEARCHES:
        for w in get_all("/works", {"filter": f"title.search:{query},{date_filter}", "select": select}, limit=400):
            works[w["id"]] = w

    candidates = []
    for w in works.values():
        title = w.get("title") or ""
        doi = (w.get("doi") or "").lower().removeprefix("https://doi.org/")
        if not title or normalize_title(title) in known_titles or (doi and doi in known_dois):
            continue
        refs = {r.rsplit("/", 1)[-1] for r in w.get("referenced_works", [])}
        n_core, n_related = len(refs & core_ids), len(refs & related_ids)
        phrase = bool(TITLE_PHRASE.search(title))
        score = 2 * n_core + n_related + 3 * phrase
        if score:
            candidates.append({"score": score, "cites_core": n_core, "cites_related": n_related,
                               "title_match": phrase, "title": title, "year": w.get("publication_year"),
                               "doi": doi, "openalex": w["id"], "work": w})
    candidates.sort(key=lambda c: (-c["score"], c["title"]))

    REPORT.write_text(json.dumps([{k: v for k, v in c.items() if k != "work"} for c in candidates],
                                 indent=1, ensure_ascii=False) + "\n")
    print(f"{len(works)} works found, {len(candidates)} new candidates -> {REPORT.relative_to(ROOT)}")
    for c in candidates[:25]:
        print(f"  {c['score']:3}  core={c['cites_core']:<2} {c['year']}  {c['title'][:90]}")

    if args.add:
        taken = {e.key.lower() for e in known}
        added = 0
        for c in candidates:
            if c["score"] < args.min_score:
                break
            entry = to_entry(c["work"])
            if normalize_title(entry.get("title")) in known_titles:
                continue
            known_titles.add(normalize_title(entry.get("title")))
            entry.key = make_key(entry, taken)
            entry.keywords = suggest_keywords((entry.get("title").lower(), ""))
            lists["unverified"].append(entry)
            added += 1
        write_bib(BIB_FILES["unverified"], lists["unverified"])
        print(f"added {added} entries with score >= {args.min_score} to {BIB_FILES['unverified'].name}")


KEY = api_key()

if __name__ == "__main__":
    try:
        main()
    except BudgetExhausted as err:
        sys.exit(f"OpenAlex refused the request: {err}\n"
                 + ("" if KEY else "No API key found; see the instructions at the top of this script."))
