#!/usr/bin/env python3
"""Sanity checks for the bibliography files.

Checks, across all .bib files: duplicate citation keys, duplicate titles and
DOIs, missing required fields, keywords not listed in keywords.json, and that
each file is sorted by key. With --fix, the files are rewritten sorted and in
canonical formatting. Exits with status 1 if a problem is left.
"""
import argparse
import json
import sys
from collections import defaultdict

from bibtools import BIB_FILES, ROOT, normalize_title, read_bib, write_bib

REQUIRED = {"author", "title", "year"}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fix", action="store_true", help="sort and reformat the .bib files")
    args = parser.parse_args()

    vocabulary = {k for group in json.loads((ROOT / "keywords.json").read_text()).values() for k in group}
    problems = []
    seen = defaultdict(lambda: defaultdict(list))  # kind -> value -> [where]

    for name, path in BIB_FILES.items():
        entries = read_bib(path)
        keys = [e.key for e in entries]
        if keys != sorted(keys, key=str.lower):
            if args.fix:
                print(f"sorted {path.name}")
            else:
                problems.append(f"{path.name}: entries are not sorted by key (run with --fix)")
        if args.fix:
            write_bib(path, entries)
        for e in entries:
            where = f"{path.name}:{e.key}"
            seen["key"][e.key.lower()].append(where)
            seen["title"][normalize_title(e.get("title"))].append(where)
            if e.get("doi"):
                seen["DOI"][e.get("doi").lower()].append(where)
            missing = REQUIRED - {f for f in e.fields if e.fields[f]}
            if missing:
                problems.append(f"{where}: missing {', '.join(sorted(missing))}")
            unknown = set(e.keywords) - vocabulary
            if unknown:
                problems.append(f"{where}: unknown keywords {', '.join(sorted(unknown))}")

    for kind, values in seen.items():
        for value, places in values.items():
            if len(places) > 1:
                problems.append(f"duplicate {kind}: {', '.join(places)}")

    for p in problems:
        print(p)
    total = sum(len(v) for v in seen["key"].values())
    print(f"{total} entries checked, {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
