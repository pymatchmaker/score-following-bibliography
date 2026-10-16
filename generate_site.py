#!/usr/bin/env python3
"""Build the static website from the .bib files into site/.

    python3 generate_site.py            # writes site/index.html, related.html, unverified.html
    python3 generate_site.py --check    # only parse and validate, write nothing

The pages are self-contained (no external scripts or styles) and work
without JavaScript; JavaScript adds search, keyword filters and BibTeX copy.
"""
import argparse
import html
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from bibtools import BIB_FILES, ROOT, latex_to_text, read_bib, split_authors  # noqa: E402

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
    t = lambda f: latex_to_text(e.get(f))  # noqa: E731
    parts = []
    if e.type == "article":
        journal = t("journal")
        vol = t("volume") + (f"({t('number')})" if e.get("number") else "")
        parts = [f"<em>{esc(journal)}</em>" if journal else "", esc(vol)]
    elif e.type in ("inproceedings", "incollection"):
        parts = [f"<em>{esc(t('booktitle'))}</em>" if e.get("booktitle") else "", esc(t("publisher"))]
    elif e.type in THESIS_TYPES:
        kind = THESIS_TYPES[e.type]
        parts = [esc(kind), esc(t("school"))]
    elif e.type == "techreport":
        parts = [esc(t("type") or "Technical report"), esc(t("institution")), esc(t("number"))]
    elif e.type == "patent":
        parts = [esc(" ".join(filter(None, ["Patent", t("number")]))), esc(t("assignee"))]
    elif e.type == "book":
        parts = [esc(t("publisher"))]
    else:
        parts = [esc(t("howpublished") or t("publisher") or t("note"))]
    if e.get("pages"):
        parts.append("pp. " + esc(t("pages")))
    return ", ".join(p for p in parts if p)


def entry_link(e):
    if e.get("doi"):
        return "https://doi.org/" + e.get("doi")
    return e.get("url")


def sort_key(e):
    month = e.get("month", "").lower()[:3]
    return (-int(re.sub(r"\D", "", e.get("year")) or 0), -MONTHS.get(month, 0), e.key.lower())


def render_entry(e, labels):
    title = latex_to_text(e.get("title"))
    link = entry_link(e)
    title_html = f'<a href="{esc(link)}">{esc(title)}</a>' if link else esc(title)
    links = []
    if e.get("doi"):
        links.append(f'<a class="act" href="https://doi.org/{esc(e.get("doi"))}">DOI</a>')
    if e.get("url"):
        links.append(f'<a class="act" href="{esc(e.get("url"))}">URL</a>')
    links.append(f'<button class="act" type="button" data-bib="{esc(e.key)}">BibTeX</button>')
    tags = "".join(f'<button class="tag" type="button" data-tag="{esc(k)}">{esc(labels.get(k, k))}</button>'
                   for k in e.keywords)
    search = " ".join([title, format_authors(e), latex_to_text(e.get("booktitle") or e.get("journal")),
                       e.get("year"), e.key, " ".join(e.keywords)]).lower()
    return f"""<li class="entry" id="{esc(e.key)}" data-tags="{esc(' '.join(e.keywords))}" data-search="{esc(search)}">
<div class="title">{title_html}</div>
<div class="authors">{esc(format_authors(e))}</div>
<div class="venue">{format_venue(e)}{', ' if format_venue(e) else ''}{esc(e.get('year'))}</div>
<div class="meta">{''.join(links)}<span class="tags">{tags}</span></div>
<pre class="bibtex" hidden>{esc(e.to_bibtex())}</pre>
</li>"""


def render_filters(vocabulary, counts):
    groups = []
    for group, tags in vocabulary.items():
        chips = "".join(
            f'<button class="tag" type="button" data-tag="{esc(k)}" aria-pressed="false">'
            f'{esc(label)}<span class="n">{counts[k]}</span></button>'
            for k, label in tags.items() if counts[k])
        if chips:
            groups.append(f'<div class="fgroup"><span class="flabel">{esc(group)}</span>{chips}</div>')
    return "\n".join(groups)


def render_page(name, entries, vocabulary, totals):
    filename, heading, intro = PAGES[name]
    labels = {k: v for tags in vocabulary.values() for k, v in tags.items()}
    counts = Counter(k for e in entries for k in e.keywords)
    by_year = defaultdict(list)
    for e in sorted(entries, key=sort_key):
        by_year[latex_to_text(e.get("year")) or "Undated"].append(e)
    sections = "\n".join(
        f'<section class="year" data-year="{esc(y)}"><h2>{esc(y)}<span class="n">{len(es)}</span></h2>\n'
        f'<ol>{"".join(render_entry(e, labels) for e in es)}</ol></section>'
        for y, es in by_year.items())
    nav = "".join(
        f'<a href="{PAGES[n][0]}"{" aria-current=page" if n == name else ""}>{esc(PAGES[n][1])}'
        f'<span class="n">{totals[n]}</span></a>' for n in PAGES)
    bibfile = BIB_FILES[name].name
    empty = '' if entries else '<p class="empty-list">No entries yet.</p>'
    return TEMPLATE.format(
        title=esc(TITLE), heading=esc(heading), intro=esc(intro), nav=nav,
        filters=render_filters(vocabulary, counts), sections=sections, count=len(entries),
        bibfile=esc(bibfile), repo=esc(REPO_URL), today=date.today().isoformat(),
        empty=empty, script=SCRIPT, style=STYLE)


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


STYLE = """
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#5f6368;--line:#e4e1da;--card:#fff;--accent:#2f5d8a;
--chip:#eef1f5;--chip-on:#2f5d8a;--chip-on-fg:#fff;--mark:#fff3b0}
@media (prefers-color-scheme:dark){:root{--bg:#16171a;--fg:#e8e6e3;--muted:#9aa0a6;--line:#2c2e33;
--card:#1d1f23;--accent:#8ab4e8;--chip:#272a30;--chip-on:#8ab4e8;--chip-on-fg:#111;--mark:#5a4a00}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent)}
.wrap{max-width:960px;margin:0 auto;padding:0 16px}
header{border-bottom:1px solid var(--line);padding:32px 0 0}
header h1{font-size:1.7rem;line-height:1.2;margin:0 0 6px}
header p{color:var(--muted);margin:0 0 16px;max-width:70ch}
nav{display:flex;gap:4px;flex-wrap:wrap}
nav a{padding:8px 14px;border-radius:8px 8px 0 0;text-decoration:none;color:var(--muted);border:1px solid transparent;border-bottom:none}
nav a[aria-current]{color:var(--fg);background:var(--bg);border-color:var(--line);margin-bottom:-1px;font-weight:600}
.n{font-size:.75em;color:var(--muted);margin-left:6px;font-weight:400}
.controls{position:sticky;top:0;z-index:2;background:var(--bg);padding:14px 0 10px;border-bottom:1px solid var(--line)}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
input[type=search]{flex:1;min-width:200px;padding:9px 12px;font:inherit;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
.btn{padding:9px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);font:inherit;font-size:.9rem;cursor:pointer;text-decoration:none;white-space:nowrap}
details.filters{margin-top:10px}
details.filters summary{cursor:pointer;color:var(--muted);font-size:.9rem}
.fgroup{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:8px}
.flabel{font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);width:90px}
.tag{border:0;background:var(--chip);color:var(--fg);border-radius:999px;padding:2px 10px;font:inherit;font-size:.78rem;cursor:pointer}
.tag[aria-pressed=true]{background:var(--chip-on);color:var(--chip-on-fg)}
.tag[aria-pressed=true] .n{color:inherit}
.status{font-size:.85rem;color:var(--muted);margin-top:8px}
.intro{color:var(--muted);margin:18px 0 0}
section.year h2{font-size:1.1rem;margin:28px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--line)}
ol{list-style:none;margin:0;padding:0}
.entry{padding:10px 0 12px;border-bottom:1px solid var(--line)}
.entry:last-child{border-bottom:0}
.entry:target{background:var(--mark);margin:0 -8px;padding:10px 8px 12px;border-radius:6px}
.title{font-weight:600}
.title a{color:inherit;text-decoration:none}
.title a:hover{color:var(--accent);text-decoration:underline}
.authors{font-size:.93rem}
.venue{font-size:.9rem;color:var(--muted)}
.meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:6px}
.act{font:inherit;font-size:.78rem;border:1px solid var(--line);background:var(--card);color:var(--accent);border-radius:6px;padding:1px 8px;cursor:pointer;text-decoration:none}
.tags{display:contents}
pre.bibtex{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:.8rem;overflow-x:auto;margin:8px 0 0;white-space:pre}
.empty-list,.none{color:var(--muted);padding:24px 0}
footer{color:var(--muted);font-size:.85rem;border-top:1px solid var(--line);margin-top:40px;padding:20px 0 40px}
@media (max-width:600px){.flabel{width:100%}header h1{font-size:1.35rem}}
"""

SCRIPT = """
(function(){
  const q = document.getElementById('q'), status = document.getElementById('status');
  const entries = [...document.querySelectorAll('.entry')];
  const active = new Set();
  function apply(){
    const terms = q.value.toLowerCase().split(/\\s+/).filter(Boolean);
    let shown = 0;
    for (const li of entries){
      const tags = li.dataset.tags.split(' ');
      const ok = terms.every(t => li.dataset.search.includes(t)) && [...active].every(t => tags.includes(t));
      li.hidden = !ok; if (ok) shown++;
    }
    for (const s of document.querySelectorAll('section.year'))
      s.hidden = ![...s.querySelectorAll('.entry')].some(li => !li.hidden);
    for (const b of document.querySelectorAll('.controls .tag'))
      b.setAttribute('aria-pressed', active.has(b.dataset.tag));
    document.getElementById('none').hidden = shown > 0 || !entries.length;
    status.textContent = (terms.length || active.size) ? shown + ' of ' + entries.length + ' entries' : entries.length + ' entries';
    const params = new URLSearchParams();
    if (q.value) params.set('q', q.value);
    if (active.size) params.set('tags', [...active].join(','));
    history.replaceState(null, '', (params.toString() ? '?' + params : location.pathname) + location.hash);
  }
  function toggle(tag){ active.has(tag) ? active.delete(tag) : active.add(tag); apply(); }
  document.addEventListener('click', e => {
    const tag = e.target.closest('.tag');
    if (tag){ toggle(tag.dataset.tag); if (!tag.closest('.controls')) document.querySelector('.controls').scrollIntoView(); return; }
    const bib = e.target.closest('[data-bib]');
    if (bib){
      const pre = bib.closest('.entry').querySelector('pre.bibtex');
      pre.hidden = !pre.hidden;
      if (!pre.hidden && navigator.clipboard) navigator.clipboard.writeText(pre.textContent).then(() => {
        bib.textContent = 'Copied'; setTimeout(() => bib.textContent = 'BibTeX', 1500); }, () => {});
    }
  });
  q.addEventListener('input', apply);
  document.getElementById('clear').addEventListener('click', () => { q.value = ''; active.clear(); apply(); });
  const params = new URLSearchParams(location.search);
  q.value = params.get('q') || '';
  (params.get('tags') || '').split(',').filter(Boolean).forEach(t => active.add(t));
  apply();
})();
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{heading} – {title}</title>
<meta name="description" content="{intro}">
<style>{style}</style>
</head>
<body>
<header><div class="wrap">
<h1>{title}</h1>
<p>A curated, open bibliography of research on real-time score following, also known as real-time music alignment or music tracking. Contributions are welcome.</p>
<nav>{nav}</nav>
</div></header>
<main class="wrap">
<p class="intro">{intro}</p>
<div class="controls">
<div class="row">
<input id="q" type="search" placeholder="Search titles, authors, venues, years…" aria-label="Search">
<button class="btn" id="clear" type="button">Clear</button>
<a class="btn" href="{bibfile}" download>Download .bib</a>
</div>
<details class="filters" open><summary>Filter by keyword</summary>
{filters}
</details>
<div class="status" id="status">{count} entries</div>
</div>
{empty}
<p class="none" id="none" hidden>No entries match the current search and filters.</p>
{sections}
</main>
<footer><div class="wrap">
<p>Maintained alongside the <a href="https://github.com/pymatchmaker/matchmaker">Matchmaker</a> project. Missing a paper or found an error?
Open an issue or a pull request at <a href="{repo}">{repo}</a>.</p>
<p>Generated on {today} from <a href="{bibfile}">{bibfile}</a>. Inspired by the <a href="https://omr-research.github.io/">OMR Research bibliography</a>.</p>
</div></footer>
<script>{script}</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
