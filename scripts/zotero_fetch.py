#!/usr/bin/env python3
"""Download all top-level items and collections of the Zotero group library.

Writes a raw snapshot to data/zotero_snapshot.json, which build_bib.py turns
into the BibTeX files. Credentials are read from ~/.config/zotero/credentials
(ZOTERO_API_KEY=..., ZOTERO_GROUP_ID=...) or from environment variables of the
same name. Only the standard library is used.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

API = "https://api.zotero.org"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "zotero_snapshot.json"


def load_credentials():
    cred = {}
    path = Path.home() / ".config" / "zotero" / "credentials"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                cred[key.strip()] = value.strip()
    for key in ("ZOTERO_API_KEY", "ZOTERO_GROUP_ID"):
        if os.environ.get(key):
            cred[key] = os.environ[key]
    if not cred.get("ZOTERO_GROUP_ID"):
        sys.exit("ZOTERO_GROUP_ID is not set")
    return cred.get("ZOTERO_API_KEY"), cred["ZOTERO_GROUP_ID"]


def fetch_all(path, api_key):
    """Follow the API's pagination and return all results of a listing."""
    results, start = [], 0
    while True:
        sep = "&" if "?" in path else "?"
        url = f"{API}{path}{sep}limit=100&start={start}"
        headers = {"Zotero-API-Version": "3"}
        if api_key:
            headers["Zotero-API-Key"] = api_key
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
            page = json.load(r)
            total = int(r.headers.get("Total-Results", len(page)))
        results.extend(page)
        start += len(page)
        if not page or start >= total:
            return results


def main():
    api_key, group = load_credentials()
    base = f"/groups/{group}"
    collections = fetch_all(f"{base}/collections", api_key)
    items = fetch_all(f"{base}/items/top?include=data,bibtex&sort=date", api_key)
    snapshot = {
        "group": group,
        "collections": [c["data"] for c in collections],
        "items": [{"data": i["data"], "bibtex": i.get("bibtex", "")} for i in items],
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n")
    print(f"Fetched {len(items)} items and {len(collections)} collections -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
