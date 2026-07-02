"""
api_retriever.py — Advanced-level Extract layer: live API retrieval.

Fetches works from the OpenAlex REST API given a textual query, handling
authentication, pagination, rate limits, and retries. Flattens the nested
JSON into a raw DataFrame whose columns match OPENALEX_MAP in standardizer.py,
so the identical transformation pipeline is reused with no duplicated logic.

The API key is read from the OPENALEX_API_KEY environment variable and is
never stored in code or in the repository.
"""

import os
import time

import pandas as pd
import requests

OPENALEX_BASE = "https://api.openalex.org/works"
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2


def fetch_openalex(query: str, max_records: int = 200, api_key: str | None = None) -> pd.DataFrame:
    """
    Retrieve works matching `query` from OpenAlex and return a flat raw DataFrame.

    Args:
        query: Free-text search string (e.g. "machine learning").
        max_records: Maximum number of works to retrieve.
        api_key: OpenAlex API key. Falls back to the OPENALEX_API_KEY env var.

    Returns:
        A DataFrame with one row per work, columns matching OPENALEX_MAP.

    Raises:
        RuntimeError: if no API key is available or retries are exhausted.
    """
    key = api_key or os.environ.get("OPENALEX_API_KEY")
    if not key:
        raise RuntimeError(
            "No OpenAlex API key. Set the OPENALEX_API_KEY environment variable "
            "or pass api_key=. Free keys: https://openalex.org/settings/api"
        )

    records, cursor = [], "*"
    per_page = min(100, max_records)  # 100 = max page size, most credit-efficient

    while len(records) < max_records:
        params = {
            "search": query,
            "per-page": per_page,
            "cursor": cursor,
            "api_key": key,
        }
        data = _request_with_retries(OPENALEX_BASE, params)

        results = data.get("results", [])
        if not results:
            break
        records.extend(_flatten_work(w) for w in results)

        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break

    return pd.DataFrame(records[:max_records])


def _request_with_retries(url: str, params: dict) -> dict:
    """GET with exponential backoff on rate-limit (429) and server (5xx) errors."""
    for attempt in range(MAX_RETRIES):
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503):
            wait = BACKOFF_BASE_SECONDS * (2 ** attempt)
            print(f"Rate-limited/unavailable (HTTP {resp.status_code}); retrying in {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"OpenAlex request failed after {MAX_RETRIES} retries.")


def _flatten_work(w: dict) -> dict:
    """Flatten one nested OpenAlex work object into a flat record."""
    authorships = w.get("authorships") or []
    biblio = w.get("biblio") or {}
    source = ((w.get("primary_location") or {}).get("source") or {})

    affiliations = []
    for a in authorships:
        name = (a.get("author") or {}).get("display_name") or ""
        for aff in a.get("raw_affiliation_strings") or []:
            affiliations.append(f"{name}, {aff}" if name else aff)

    return {
        "id": w.get("id") or "",
        "doi": w.get("doi") or "",
        "title": w.get("title") or "",
        "publication_year": w.get("publication_year"),
        "source_name": source.get("display_name") or "",
        "type": w.get("type") or "",
        "language": w.get("language") or "",
        "cited_by_count": w.get("cited_by_count", 0),
        "authors": "; ".join(
            (a.get("author") or {}).get("display_name") or "" for a in authorships
        ),
        "affiliations": "; ".join(affiliations),
        "volume": biblio.get("volume") or "",
        "issue": biblio.get("issue") or "",
        "first_page": biblio.get("first_page") or "",
        "last_page": biblio.get("last_page") or "",
        "keywords": "; ".join(
            k.get("display_name") or "" for k in (w.get("keywords") or [])
        ),
        "abstract": _rebuild_abstract(w.get("abstract_inverted_index")),
        "references": "; ".join(w.get("referenced_works") or []),
    }


def _rebuild_abstract(inverted: dict | None) -> str:
    """Reconstruct abstract text from OpenAlex's inverted index format."""
    if not inverted:
        return ""
    positions = {}
    for word, idxs in inverted.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))