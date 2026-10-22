#!/usr/bin/env python3
"""Build the static website from the .bib files into site/.

    python3 generate_site.py            # writes site/index.html, related.html, unverified.html
    python3 generate_site.py --check    # only parse and validate, write nothing

The layout follows the OMR Research bibliography. The pages need no external
scripts (only the Open Sans web font) and list all entries without JavaScript;
JavaScript adds search, filters, sorting and the expandable BibTeX panels.
"""
import argparse
import html
import json
import re
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from bibtools import (BIB_FILES, ROOT, ascii_fold, last_name, latex_to_text, read_bib,  # noqa: E402
                      split_authors)

OUT = ROOT / "site"
TITLE = "Bibliography on Real-Time Score Following"
REPO_URL = "https://github.com/pymatchmaker/score-following-bibliography"

PAGES = {
    "core": ("index.html", "Score Following",
             "Research on real-time score following, music tracking and the systems built on it, "
             "such as automatic accompaniment and page turning."),
    "related": ("related.html", "Related Research",
                "Work that is not primarily about real-time following but is closely related: offline "
                "audio-to-score and note alignment, features, datasets, tools and general references."),
    "unverified": ("unverified.html", "Unverified",
                   "Candidate entries that were found automatically or submitted but have not yet been "
                   "checked by a maintainer. Metadata may be incomplete or wrong."),
}

MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}

THESIS_TYPES = {"phdthesis": "PhD thesis", "mastersthesis": "Master's thesis"}


def esc(text):
    return html.escape(text, quote=True)


def format_name(name):
    name = latex_to_text(name)
    if "," in name:
        last, first = [p.strip() for p in name.split(",", 1)]
        return f"{first} {last}".strip()
    return name


def format_authors(entry):
    names = [format_name(a) for a in split_authors(entry.get("author") or entry.get("editor"))]
    if len(names) <= 2:
        text = " and ".join(names)
    else:
        text = ", ".join(names[:-1]) + ", and " + names[-1]
    return text + (" (Ed.)" if not entry.get("author") and entry.get("editor") else "")


def format_venue(e):
    """Plain-text venue line, parts joined with ' · ' as on the OMR page."""
    t = lambda f: latex_to_text(e.get(f))  # noqa: E731
    if e.type == "article":
        parts = [t("journal"), t("volume") + (f"({t('number')})" if e.get("number") else "")]
    elif e.type in ("inproceedings", "incollection"):
        parts = [t("booktitle"), t("publisher")]
    elif e.type in THESIS_TYPES:
        parts = [THESIS_TYPES[e.type], t("school")]
    elif e.type == "techreport":
        parts = [t("type") or "Technical report", t("institution"), t("number")]
    elif e.type == "patent":
        parts = [" ".join(filter(None, ["Patent", t("number")])), t("assignee")]
    elif e.type == "book":
        parts = [t("publisher")]
    else:
        parts = [t("howpublished") or t("publisher") or t("note")]
    if e.get("pages"):
        parts.append("pp. " + t("pages"))
    return " · ".join(p for p in parts if p)


def entry_links(e):
    """(label, url, css class) badges, as on the OMR Research page."""
    links = []
    doi, url = e.get("doi"), e.get("url")
    if doi:
        arxiv = doi.lower().startswith("10.48550/arxiv.")
        links.append(("arXiv" if arxiv else "DOI", "https://doi.org/" + doi, "badge-arxiv" if arxiv else "badge-doi"))
    if url:
        arxiv = "arxiv.org" in url
        links.append(("arXiv" if arxiv else "URL", url, "badge-arxiv" if arxiv else "badge-url"))
    return links


def year_month(e):
    year = int(re.sub(r"\D", "", e.get("year"))[:4] or 0)
    return year * 100 + MONTHS.get(e.get("month", "").lower()[:3], 0)


def sort_key(e):
    return (-year_month(e), e.key.lower())


def first_author_key(e):
    authors = split_authors(e.get("author") or e.get("editor"))
    return re.sub(r"[^a-z]", "", ascii_fold(last_name(authors[0])).lower()) if authors else ""


def render_entry(e, labels):
    title = latex_to_text(e.get("title"))
    links = entry_links(e)
    title_html = f'<a href="{esc(links[0][1])}">{esc(title)}</a>' if links else esc(title)
    badges = "".join(f'<a class="badge {cls}" href="{esc(href)}">{label}</a>' for label, href, cls in links)
    tags = "".join(f'<button class="kw" type="button" data-tag="{esc(k)}" title="Show all entries with this keyword">'
                   f'{esc(labels.get(k, k))}</button>' for k in e.keywords)
    venue = format_venue(e)
    authors = format_authors(e)
    search = " ".join([e.key, e.get("year"), authors, title, venue, e.type,
                       " ".join(labels.get(k, k) for k in e.keywords)]).lower()
    return f"""<article class="entry-card" id="{esc(e.key)}" data-year="{esc(latex_to_text(e.get('year')))}"
 data-type="{esc(e.type)}" data-tags="{esc(' '.join(e.keywords))}" data-ym="{year_month(e)}"
 data-author="{esc(first_author_key(e))}" data-key="{esc(e.key.lower())}" data-search="{esc(search)}">
<div class="entry-header">
<div class="entry-chips"><span class="entry-year">{esc(latex_to_text(e.get('year')))}</span><span class="entry-type">{esc(e.type)}</span>{badges}</div>
<div class="entry-authors">{esc(authors)}</div>
<div class="entry-title">{title_html}</div>
{f'<div class="entry-venue">{esc(venue)}</div>' if venue else ''}
{f'<div class="entry-kws">{tags}</div>' if tags else ''}
</div>
<div class="entry-panel">
<div class="entry-bibtex-wrap"><button class="copy-btn" type="button">Copy BibTeX</button><pre class="entry-bibtex">{esc(e.to_bibtex().strip())}</pre></div>
</div>
</article>"""


def render_options(values, counts=None):
    return "".join(f'<option value="{esc(v)}">{esc(label)}{f" ({counts[v]})" if counts else ""}</option>'
                   for v, label in values)


def render_keyword_options(vocabulary, counts):
    groups = []
    for group, tags in vocabulary.items():
        opts = render_options([(k, label) for k, label in tags.items() if counts[k]], counts)
        if opts:
            groups.append(f'<optgroup label="{esc(group)}">{opts}</optgroup>')
    return "".join(groups)


def render_page(name, entries, vocabulary, totals):
    filename, heading, intro = PAGES[name]
    labels = {k: v for tags in vocabulary.values() for k, v in tags.items()}
    entries = sorted(entries, key=sort_key)
    years = sorted({latex_to_text(e.get("year")) for e in entries if e.get("year")}, reverse=True)
    types = Counter(e.type for e in entries)
    nav = "".join(
        f'<a href="{PAGES[n][0]}" class="btn-nav{" btn-nav-active" if n == name else ""}">'
        f'{esc(PAGES[n][1])} <span class="n">{totals[n]}</span></a>' for n in PAGES)
    return TEMPLATE.format(
        title=esc(TITLE), heading=esc(heading), intro=esc(intro), nav=nav, repo=esc(REPO_URL),
        updated=date.today().strftime("%d.%m.%Y"), bibfile=esc(BIB_FILES[name].name),
        years=render_options([(y, y) for y in years]),
        types=render_options([(t, t) for t in sorted(types)], types),
        keywords=render_keyword_options(vocabulary, Counter(k for e in entries for k in e.keywords)),
        entries="\n".join(render_entry(e, labels) for e in entries), count=len(entries),
        empty="" if entries else '<p class="no-results">No entries yet.</p>',
        script=SCRIPT, style=STYLE)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="validate only, write nothing")
    args = parser.parse_args()

    vocabulary = json.loads((ROOT / "keywords.json").read_text())
    lists = {name: read_bib(path) for name, path in BIB_FILES.items()}
    totals = {name: len(entries) for name, entries in lists.items()}
    pages = {PAGES[name][0]: render_page(name, entries, vocabulary, totals) for name, entries in lists.items()}
    if args.check:
        print("OK:", ", ".join(f"{n} {name}" for name, n in totals.items()))
        return
    OUT.mkdir(exist_ok=True)
    for filename, content in pages.items():
        (OUT / filename).write_text(content, encoding="utf-8")
    for path in BIB_FILES.values():
        shutil.copy(path, OUT / path.name)
    print(f"Wrote {len(pages)} pages to {OUT.relative_to(ROOT)}/ ("
          + ", ".join(f"{n} {name}" for name, n in totals.items()) + ")")


# Layout and colours follow the OMR Research bibliography (https://omr-research.github.io/).
STYLE = """
*,*::before,*::after{box-sizing:border-box}
body{margin:0;font-family:"Open Sans",Arial,sans-serif;font-size:1rem;background:#f8f9fa;color:#212529}
a{color:#155799;text-decoration:none}
a:hover{text-decoration:underline}

/* Header */
.page-header{padding:40px 20px 24px;color:#fff;text-align:center;background:linear-gradient(120deg,#155799,#159957)}
.page-header h1{margin:0 0 6px;font-size:42px;font-weight:700;line-height:1.2}
.page-header p{margin:0 0 14px;opacity:.85}
.btn-github,.btn-nav{display:inline-block;padding:.75rem 1rem;margin:0 3px 1rem;border-radius:.3rem;
  color:rgba(255,255,255,.7);transition:color .2s,background-color .2s,border-color .2s}
.btn-github{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.2)}
.btn-github:hover{background:rgba(255,255,255,.2);color:#fff;text-decoration:none}
.page-nav{display:flex;flex-wrap:wrap;justify-content:center}
.btn-nav:hover{background:rgba(255,255,255,.15);color:#fff;text-decoration:none}
.btn-nav-active{background:rgba(255,255,255,.2);color:#fff;font-weight:600}
.btn-nav .n{font-size:.8em;opacity:.8;font-weight:400}

/* Controls */
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:10px 20px;background:#fff;
  border-bottom:1px solid #dee2e6;position:sticky;top:0;z-index:100;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.controls input[type=search],.controls select,.controls .btn{font-family:inherit;font-size:inherit;padding:5px 10px;
  border:1px solid #ced4da;border-radius:4px;background:#fff;color:#212529;outline:none}
.controls input[type=search]{flex:1 1 200px;min-width:160px}
.controls input[type=search]:focus,.controls select:focus{border-color:#159957;box-shadow:0 0 0 2px rgba(21,153,87,.15)}
.controls select,.controls .btn{cursor:pointer;max-width:100%}
.controls .btn:hover{border-color:#159957;color:#159957;text-decoration:none}
.controls label{color:#555;white-space:nowrap}
.stat-label{color:#666;white-space:nowrap}

/* Entries */
.entry-list{padding:12px 20px;max-width:1100px;margin:0 auto}
.page-intro{color:#666;margin:4px 0 14px;font-size:.95rem}
.entry-card{background:#fff;border:1px solid #e1e4e8;border-radius:6px;margin-bottom:10px;overflow:hidden;
  cursor:pointer;transition:box-shadow .15s}
.entry-card:hover{box-shadow:0 2px 8px rgba(0,0,0,.1)}
.entry-card:target{border-color:#159957;box-shadow:0 0 0 2px rgba(21,153,87,.25)}
.entry-header{padding:12px 14px 10px}
.entry-chips{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin-bottom:4px}
.entry-year{font-size:.75rem;font-weight:700;color:#fff;background:#159957;padding:2px 7px;border-radius:3px}
.entry-type{font-size:.75rem;color:#666;background:#f0f0f0;padding:2px 7px;border-radius:3px;text-transform:lowercase}
.entry-authors{color:#555;margin-bottom:3px}
.entry-title{font-weight:600;color:#155799;margin-bottom:4px;line-height:1.4}
.entry-title a{color:#155799}
.entry-title a:hover{color:#159957}
.entry-venue{color:#666;font-style:italic}
.entry-kws{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.kw{font-family:inherit;font-size:.72rem;color:#155799;background:#eef4fb;border:1px solid #d6e4f3;
  padding:1px 7px;border-radius:10px;cursor:pointer}
.kw:hover{background:#155799;color:#fff;border-color:#155799}
.badge{display:inline-block;font-size:.75rem;font-weight:700;padding:2px 7px;border-radius:3px;transition:opacity .15s}
.badge:hover{opacity:.8;text-decoration:none}
.badge-doi{background:#dbeafe;color:#1e40af}
.badge-arxiv{background:#fef3c7;color:#92400e}
.badge-url{background:#d1fae5;color:#065f46}

/* Expandable BibTeX panel */
.entry-panel{display:none;border-top:1px solid #e9ecef;background:#f8f9fa;cursor:auto}
.entry-card.open .entry-panel{display:block}
.entry-bibtex-wrap{position:relative;padding:10px 14px}
.entry-bibtex{font-family:"Courier New",monospace;font-size:.8rem;white-space:pre-wrap;word-break:break-all;color:#333;margin:0;padding-right:110px}
.copy-btn{position:absolute;top:10px;right:14px;font-family:inherit;font-size:.75rem;cursor:pointer;padding:3px 10px;
  border-radius:4px;border:1px solid #ced4da;background:#fff;color:#555;transition:background .15s,color .15s}
.copy-btn:hover,.copy-btn.copied{background:#159957;color:#fff;border-color:#159957}

.no-results{text-align:center;color:#888;padding:40px}
.page-footer{text-align:center;color:#888;font-size:.85rem;padding:20px 20px 40px;max-width:1100px;margin:0 auto}

@media (max-width:600px){
  .page-header{padding:28px 16px 16px}
  .page-header h1{font-size:28px}
  .controls{padding:10px 16px;position:static}
  .entry-list{padding:12px 16px}
  .entry-bibtex{padding-right:0;padding-top:28px}
}
"""

SCRIPT = """
(function(){
  const $ = id => document.getElementById(id);
  const list = $('entryList'), cards = [...list.querySelectorAll('.entry-card')];
  const controls = ['q', 'fYear', 'fType', 'fKeyword', 'fSort'];
  const byYearDesc = (a, b) => b.dataset.ym - a.dataset.ym || a.dataset.key.localeCompare(b.dataset.key);
  const sorters = {
    year_desc: byYearDesc,
    year_asc: (a, b) => a.dataset.ym - b.dataset.ym || a.dataset.key.localeCompare(b.dataset.key),
    author: (a, b) => a.dataset.author.localeCompare(b.dataset.author) || byYearDesc(a, b),
    key: (a, b) => a.dataset.key.localeCompare(b.dataset.key),
  };

  function applyFilters(){
    const terms = $('q').value.toLowerCase().split(/\\s+/).filter(Boolean);
    const yr = $('fYear').value, tp = $('fType').value, kw = $('fKeyword').value;
    let shown = 0;
    for (const c of cards){
      const ok = terms.every(t => c.dataset.search.includes(t))
        && (!yr || c.dataset.year === yr) && (!tp || c.dataset.type === tp)
        && (!kw || c.dataset.tags.split(' ').includes(kw));
      c.hidden = !ok; if (ok) shown++;
    }
    [...cards].sort(sorters[$('fSort').value] || byYearDesc).forEach(c => list.appendChild(c));
    $('noResults').hidden = shown > 0 || !cards.length;
    $('statLabel').textContent = shown === cards.length ? cards.length + ' entries' : shown + ' of ' + cards.length + ' entries';
    const params = new URLSearchParams();
    for (const id of controls){ const v = $(id).value; if (v && !(id === 'fSort' && v === 'year_desc')) params.set(id, v); }
    history.replaceState(null, '', (params.toString() ? '?' + params : location.pathname) + location.hash);
  }

  list.addEventListener('click', e => {
    const card = e.target.closest('.entry-card');
    if (!card) return;
    const kw = e.target.closest('.kw');
    if (kw){ $('fKeyword').value = kw.dataset.tag; applyFilters(); window.scrollTo({top: $('controls').offsetTop}); return; }
    const copy = e.target.closest('.copy-btn');
    if (copy){
      navigator.clipboard.writeText(card.querySelector('.entry-bibtex').textContent).then(() => {
        copy.textContent = 'Copied!'; copy.classList.add('copied');
        setTimeout(() => { copy.textContent = 'Copy BibTeX'; copy.classList.remove('copied'); }, 1800);
      }, () => {});
      return;
    }
    // Links and selecting text inside the BibTeX panel should not toggle the card.
    if (e.target.closest('a, .entry-panel') || String(window.getSelection())) return;
    card.classList.toggle('open');
  });
  for (const id of controls) $(id).addEventListener(id === 'q' ? 'input' : 'change', applyFilters);

  const params = new URLSearchParams(location.search);
  for (const id of controls) if (params.get(id)) $(id).value = params.get(id);
  if (location.hash && document.getElementById(location.hash.slice(1)))
    document.getElementById(location.hash.slice(1)).classList.add('open');
  applyFilters();
})();
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{heading} – {title}</title>
<meta name="description" content="{intro}">
<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Open+Sans:400,600,700&display=swap">
<style>{style}</style>
</head>
<body>
<section class="page-header">
<h1>{title}</h1>
<p>Last updated: {updated}</p>
<a href="{repo}" class="btn-github">View on GitHub</a>
<nav class="page-nav">{nav}</nav>
</section>

<div class="controls" id="controls">
<input type="search" id="q" placeholder="Search title, author, venue, keyword, key…" aria-label="Search">
<select id="fYear" aria-label="Year"><option value="">All years</option>{years}</select>
<select id="fType" aria-label="Entry type"><option value="">All types</option>{types}</select>
<select id="fKeyword" aria-label="Keyword"><option value="">All keywords</option>{keywords}</select>
<label>Sort:
<select id="fSort">
<option value="year_desc">Year ↓</option>
<option value="year_asc">Year ↑</option>
<option value="author">Author A–Z</option>
<option value="key">Key A–Z</option>
</select>
</label>
<a class="btn" href="{bibfile}" download>Download .bib</a>
<span class="stat-label" id="statLabel">{count} entries</span>
</div>

<main class="entry-list" id="entryList">
<p class="page-intro">{intro} Click an entry to show its BibTeX.</p>
{empty}
<p class="no-results" id="noResults" hidden>No entries match the current filters.</p>
{entries}
</main>

<footer class="page-footer">
<p>Maintained alongside <a href="https://github.com/pymatchmaker/matchmaker">Matchmaker</a>. Missing a paper or found an error?
Open an issue or a pull request on <a href="{repo}">GitHub</a>.
Modelled on the <a href="https://omr-research.github.io/">Bibliography on Optical Music Recognition</a>.</p>
</footer>
<script>{script}</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
