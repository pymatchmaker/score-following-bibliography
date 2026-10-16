#!/usr/bin/env python3
"""Turn the Zotero snapshot into BibTeX entries and add new ones to the .bib files.

Items that already exist in any of the .bib files (same DOI or same
normalised title) are skipped, so the .bib files stay the source of truth and
manual edits there are never overwritten.

New items go to ScoreFollowing-Unverified.bib with automatically suggested
keywords, unless data/curation.json assigns them to a list ("core" or
"related") and/or adjusts their keywords and fields.

    python3 scripts/zotero_fetch.py      # refresh data/zotero_snapshot.json
    python3 scripts/zotero_import.py     # add new items to the .bib files
"""
import argparse
import json
import re
import sys

from bibtools import (BIB_FILES, ROOT, Entry, ascii_fold, last_name, latex_to_text,
                      normalize_title, parse_bib, read_bib, split_authors, write_bib)

SNAPSHOT = ROOT / "data" / "zotero_snapshot.json"
CURATION = ROOT / "data" / "curation.json"

# Zotero export fields that are not useful in a public bibliography.
DROP_FIELDS = {"abstract", "keywords", "language", "urldate", "copyright", "shorttitle",
               "issn", "isbn", "file", "collaborator"}

# Keywords whose rules may also match the abstract; all others only look at the
# title and the Zotero collection names, which gives far fewer false positives.
ABSTRACT_RULES = {"audio", "dtw", "hmm", "graphical-model", "particle-filter", "nmf",
                  "deep-learning", "reinforcement-learning"}

# Keyword suggestions: keyword -> regex.
RULES = {
    "audio": r"audio|acoustic|polyphonic music signals|spectr|chroma|listen|machine listening",
    "midi": r"\bmidi\b|symbolic music|symbolic (score|performance|alignment)|note alignment"
            r"|score[- ]performance matching|keyboard performance",
    "sheet-image": r"sheet[- ]music images?|score sheet images?|sheet images|real scores",
    "singing": r"lyric|singing|sung voice|vocal|karaoke",
    "multimodal": r"gaze|hand pose|audio-visual|multimodal_audiovisual|video",
    "dtw": r"time warping|\bdtw\b|oltw|dynamic programming|dp matching|string-matching",
    "hmm": r"hidden markov|\bhmms?\b|probabilistic_hmm|generalreferences_hmm",
    "graphical-model": r"bayesian|graphical model|conditional random|state[- ]space|semi-markov"
                       r"|\bhsmm\b|probabilistic_dbn|probabilistic_hsmm|stochastic",
    "particle-filter": r"particle filter|monte ?carlo|particlefiltering",
    "nmf": r"non-negative|\bnmf\b|spectral (factori[sz]ation|decomposition)",
    "deep-learning": r"neural|deep learning|convolutional|siamese|learned representation"
                     r"|autoencoder|learned_features",
    "reinforcement-learning": r"reinforcement learning|\brl\b",
    "fingerprinting": r"identification of piece|fingerprint",
    "tempo": r"\btempo\b",
    "structure": r"repeats|jumps|skips|structur|errors|mistakes|recitative",
    "features": r"features|distance functions|spectral template|observation model",
    "offline": r"off-?line|offline_method|offline_alignment",
    "accompaniment": r"accompan",
    "page-turning": r"page[- ]turn",
    "opera": r"opera\b|concertgebouw|concerts?\b|orchestral performance companion",
    "ensemble": r"ensemble|duet|quartet|robot|co-?player|big band|virtual orchestra",
    "education": r"practice|education|rehearsal",
    "survey": r"\bsurvey\b|state of the art|\breview\b|tutorial",
    "evaluation": r"\bevaluat|bottlenecks",
    "dataset": r"\bdataset\b",
    "software": r"python package|python library|open-source library|toolbox|tool chest"
                r"|file format|encoding music|implementations",
    "mirex": r"\bmirex\b",
}


def snapshot_entries():
    snapshot = json.loads(SNAPSHOT.read_text())
    collections = {c["key"]: c["name"] for c in snapshot["collections"]}
    for item in snapshot["items"]:
        data, bib = item["data"], parse_bib(item["bibtex"])
        if not bib:
            print(f"warning: no BibTeX for {data['key']} {data.get('title')!r}", file=sys.stderr)
            continue
        entry = bib[0]
        title = " ".join([data.get("title", "")]
                         + [collections[c] for c in data.get("collections", [])]).lower()
        yield data["key"], entry, (title, data.get("abstractNote", "").lower())


def clean(entry):
    for name in DROP_FIELDS:
        entry.fields.pop(name, None)
    entry.fields["title"] = re.sub(r"\.pdf$", "", entry.get("title"))
    if entry.get("doi") and entry.get("url", "").endswith(entry.get("doi")):
        entry.fields.pop("url")  # the DOI link is enough
    return entry


def make_key(entry, taken):
    authors = split_authors(entry.get("author") or entry.get("editor") or "Anonymous")
    name = re.sub(r"[^A-Za-z]", "", ascii_fold(last_name(authors[0]))) or "Anonymous"
    words = re.findall(r"[A-Za-z0-9]+", ascii_fold(latex_to_text(entry.get("title"))))
    stop = {"a", "an", "the", "on", "of", "for", "to", "and", "in", "using", "with", "towards"}
    word = next((w for w in words if w.lower() not in stop), "")
    base = f"{name}{entry.get('year', '')}{word[:1].upper()}{word[1:].lower()}"
    key, n = base, 0
    while key.lower() in taken:
        n += 1
        key = f"{base}{chr(ord('a') + n)}"
    taken.add(key.lower())
    return key


def suggest_keywords(context):
    title, abstract = context
    return [kw for kw, rx in RULES.items()
            if re.search(rx, title) or (kw in ABSTRACT_RULES and re.search(rx, abstract))]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="only report what would be added")
    args = parser.parse_args()

    curation = json.loads(CURATION.read_text()) if CURATION.exists() else {}
    lists = {name: read_bib(path) for name, path in BIB_FILES.items()}
    existing = [e for entries in lists.values() for e in entries]
    known_titles = {normalize_title(e.get("title")) for e in existing}
    known_dois = {e.get("doi").lower() for e in existing if e.get("doi")}
    taken = {e.key.lower() for e in existing}
    skip = set(curation.get("skip", []))

    added = {name: 0 for name in lists}
    for zkey, entry, context in snapshot_entries():
        if zkey in skip:
            continue
        clean(entry)
        for name, value in curation.get("fields", {}).get(zkey, {}).items():
            if value is None:
                entry.fields.pop(name, None)
            else:
                entry.fields[name] = value
        doi = entry.get("doi").lower()
        title = normalize_title(entry.get("title"))
        if title in known_titles or (doi and doi in known_dois):
            continue
        known_titles.add(title)
        if doi:
            known_dois.add(doi)

        keywords = set(suggest_keywords(context))
        for change in curation.get("keywords", {}).get(zkey, "").split():
            (keywords.add if change[0] == "+" else keywords.discard)(change[1:])
        target = curation.get("list", {}).get(zkey, "unverified")
        if target not in lists:
            sys.exit(f"unknown list {target!r} for {zkey}")
        entry.key = make_key(entry, taken)
        entry.keywords = keywords
        lists[target].append(entry)
        added[target] += 1
        print(f"+ {target:10} {entry.key:40} {latex_to_text(entry.get('title'))[:70]}")

    print("added:", ", ".join(f"{n} {name}" for name, n in added.items()))
    if not args.dry_run:
        for name, entries in lists.items():
            write_bib(BIB_FILES[name], entries)


if __name__ == "__main__":
    main()
