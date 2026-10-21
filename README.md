# Bibliography on Real-Time Score Following

A curated bibliography of research on real-time score following (also called
real-time music alignment or music tracking), maintained alongside
[Matchmaker](https://github.com/pymatchmaker/matchmaker). It is modelled on the
[OMR Research bibliography](https://omr-research.github.io/).

The site will be published at <https://pymatchmaker.github.io/score-following-bibliography/>.

## Files

| File | Contents |
| --- | --- |
| `ScoreFollowing.bib` | Verified work on real-time score following and the systems built on it (accompaniment, page turning, …) |
| `ScoreFollowing-Related.bib` | Verified related work: offline alignment, features, datasets, tools, general references |
| `ScoreFollowing-Unverified.bib` | Candidates found automatically or submitted, not yet checked |
| `keywords.json` | The allowed values of the `keywords` field, grouped for the site's filters |
| `generate_site.py` | Builds the static site into `site/` (standard library only) |
| `scripts/check_bibtex.py` | Checks for duplicate keys/titles/DOIs, missing fields, unknown keywords and sort order |
| `scripts/zotero_fetch.py`, `scripts/zotero_import.py` | Import new items from the Zotero group library |
| `scripts/discover.py` | Finds new candidate papers through OpenAlex citations |
| `data/curation.json` | Per-item list/keyword decisions for the Zotero import |
| `data/openalex_ids.json` | Cache of OpenAlex ids for the bibliography entries |

The `.bib` files are the source of truth. Edit them directly; the import
scripts only ever add entries and never change existing ones.

## Building the site

```sh
python3 generate_site.py          # writes site/index.html, related.html, unverified.html
python3 -m http.server -d site    # then open http://localhost:8000
```

## Entry conventions

- Citation keys are `LastnameYearTitleword`, e.g. `Dixon2005Line`; a second
  entry with the same key gets a letter suffix (`Arzt2014Tempob`).
- Every entry needs `author`, `title` and `year`, and should have a `doi`, or a
  `url` if there is no DOI.
- `keywords` lists tags from `keywords.json`, separated by commas: the input type
  (`audio`, `midi`, `sheet-image`, …), the method (`dtw`, `hmm`, `deep-learning`, …),
  the problem addressed, the application and the kind of work.
- Run `python3 scripts/check_bibtex.py --fix` before committing; it sorts the
  files. `git config core.hooksPath hooks` runs it automatically on every commit.

## Adding papers

**From Zotero.** Add papers to the `realtimemusicalignment` group library, then:

```sh
python3 scripts/zotero_fetch.py           # download a snapshot of the group library
python3 scripts/zotero_import.py --dry-run
python3 scripts/zotero_import.py          # new items go to ScoreFollowing-Unverified.bib
```

Credentials are read from `~/.config/zotero/credentials`
(`ZOTERO_API_KEY=…`, `ZOTERO_GROUP_ID=…`). To put an item straight into the core or
related list, or to adjust its suggested keywords, add it to `data/curation.json`
before importing.

**Automatic discovery.** `scripts/discover.py` looks up every entry in
[OpenAlex](https://openalex.org), collects recent papers that cite entries of the
core list or whose titles match score-following phrases, and scores them (+2 per
cited core entry, +1 per cited related entry, +5 for a title phrase such as
"score following", +2 for a looser one such as "accompaniment"):

```sh
python3 scripts/discover.py --since 2025-01-01          # report to data/candidates.json
python3 scripts/discover.py --since 2025-01-01 --add    # add candidates with score >= 5 to Unverified
```

OpenAlex requires a free API key for this amount of traffic: create one at
<https://help.openalex.org/api/authentication/> and store it as `OPENALEX_API_KEY=…` in
`~/.config/openalex/credentials`.

**Verifying.** For each entry in `ScoreFollowing-Unverified.bib`, check the
metadata against the publisher, the venue's proceedings or DBLP, add a DOI or URL,
fix the keywords, and move the entry to `ScoreFollowing.bib` or
`ScoreFollowing-Related.bib`, or delete it if it is out of scope.

**Contributions** are welcome as issues or pull requests that edit the `.bib` files.
