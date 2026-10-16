"""Minimal BibTeX reading/writing shared by the bibliography scripts.

Only the standard library is used. Field values are kept as raw BibTeX
strings (without the outer braces), so entries round-trip unchanged.
"""
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The three bibliography files, in the order they appear on the site.
BIB_FILES = {
    "core": ROOT / "ScoreFollowing.bib",
    "related": ROOT / "ScoreFollowing-Related.bib",
    "unverified": ROOT / "ScoreFollowing-Unverified.bib",
}

# Fields are written in this order; any others follow alphabetically.
FIELD_ORDER = [
    "author", "editor", "title", "booktitle", "journal", "school", "institution",
    "publisher", "address", "series", "volume", "number", "pages", "type",
    "assignee", "nationality", "month", "year", "doi", "url", "note", "keywords",
]

HEADER = (
    "% Bibliography on Real-Time Score Following\n"
    "% Entries are sorted by citation key; run `python3 scripts/check_bibtex.py --fix` to sort.\n"
    "% Keywords must come from keywords.json.\n\n"
)


class Entry:
    def __init__(self, type_, key, fields):
        self.type = type_.lower()
        self.key = key
        self.fields = dict(fields)

    def get(self, name, default=""):
        return self.fields.get(name, default)

    @property
    def keywords(self):
        return [k.strip() for k in self.get("keywords").split(",") if k.strip()]

    @keywords.setter
    def keywords(self, values):
        values = sorted(set(values))
        if values:
            self.fields["keywords"] = ", ".join(values)
        else:
            self.fields.pop("keywords", None)

    def to_bibtex(self):
        names = [f for f in FIELD_ORDER if f in self.fields]
        names += sorted(f for f in self.fields if f not in FIELD_ORDER)
        body = ",\n".join(f"  {name} = {{{self.fields[name]}}}" for name in names)
        return f"@{self.type}{{{self.key},\n{body}\n}}\n"


def _read_braced(text, i):
    """Return (value, end) for a value starting at text[i] == '{' or '"'."""
    if text[i] == '"':
        end = i + 1
        while text[end] != '"' or text[end - 1] == "\\":
            end += 1
        return text[i + 1:end], end + 1
    depth, j = 0, i
    while True:
        c = text[j]
        if c == "{" and text[j - 1] != "\\":
            depth += 1
        elif c == "}" and text[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1


def parse_bib(text):
    entries = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        if m.group(1).lower() in ("comment", "string", "preamble"):
            continue
        i, fields = m.end(), {}
        while True:
            fm = re.compile(r"\s*(\w[\w-]*)\s*=\s*").match(text, i)
            if not fm:
                break
            name, i = fm.group(1).lower(), fm.end()
            if text[i] in '{"':
                value, i = _read_braced(text, i)
            else:  # bare number or macro such as a month abbreviation
                vm = re.compile(r"[\w.-]+").match(text, i)
                value, i = vm.group(0), vm.end()
            fields[name] = re.sub(r"\s+", " ", value).strip()
            i = re.compile(r"\s*,?").match(text, i).end()
        entries.append(Entry(m.group(1), m.group(2), fields))
    return entries


def read_bib(path):
    path = Path(path)
    return parse_bib(path.read_text(encoding="utf-8")) if path.exists() else []


def write_bib(path, entries):
    entries = sorted(entries, key=lambda e: e.key.lower())
    Path(path).write_text(HEADER + "\n".join(e.to_bibtex() for e in entries), encoding="utf-8")


# --- Plain-text helpers ----------------------------------------------------

_ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303",
            "c": "\u0327", "v": "\u030c", "=": "\u0304", ".": "\u0307", "u": "\u0306", "H": "\u030b"}
_MACROS = {r"\&": "&", r"\%": "%", r"\_": "_", r"\$": "$", r"\#": "#", "--": "\u2013",
           r"\textendash": "\u2013", r"\textemdash": "\u2014", r"\ss": "ß", r"\o": "ø",
           r"\O": "Ø", r"\aa": "å", r"\AA": "Å", r"\ae": "æ", r"\l": "ł", "~": "\u00a0"}


def latex_to_text(value):
    """Turn a BibTeX field value into readable Unicode text."""
    s = re.sub(r"\\([" + re.escape("'`^\"~=.") + r"]|[cvuH](?=[\s{]))\s*\{?\s*\\?(\w)\}?",
               lambda m: unicodedata.normalize("NFC", m.group(2) + _ACCENTS[m.group(1)]), value)
    for macro, rep in _MACROS.items():
        s = s.replace(macro, rep)
    s = re.sub(r"\\(emph|textit|textbf|mathrm|text)\s*", "", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def ascii_fold(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def normalize_title(title):
    """Lower-case alphanumeric form of a title, used to detect duplicates."""
    return re.sub(r"[^a-z0-9]", "", ascii_fold(latex_to_text(title)).lower())


def split_authors(value):
    return [a.strip() for a in re.split(r"\s+and\s+", value) if a.strip()]


def last_name(author):
    author = latex_to_text(author)
    return author.split(",")[0].strip() if "," in author else author.split()[-1]
