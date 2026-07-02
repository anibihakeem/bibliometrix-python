"""
standardizer.py — Source-agnostic ETL transform layer for bibliometrix-python.

Maps heterogeneous bibliographic exports (Scopus, Dimensions, PubMed, OpenAlex)
onto the Web of Science (WoS) internal schema used by the analytical functions
in services/ and functions/. Replicates the conceptual role of convert2df() in
the R bibliometrix package.
"""

import pandas as pd
import numpy as np

# ----------------------------------------------------------------------
# TYPE CONTRACTS
# ----------------------------------------------------------------------
LIST_COLUMNS = ["AU", "AF", "C1", "CR", "DE", "ID"]
INT_COLUMNS = ["TC","PY"]

TARGET_SCHEMA = [
    "DB", "UT", "DI", "PMID", "TI", "SO", "JI", "PY", "DT", "LA", "TC",
    "AU", "AF", "C1", "RP", "CR", "DE", "ID", "AB", "VL", "IS", "BP", "EP", "SR",
]

# ----------------------------------------------------------------------
# MAPPING DICTIONARIES: {source_column_name: WoS_tag}
# ----------------------------------------------------------------------
SCOPUS_MAP = {
    "Authors":                       "AU",
    "Author full names":             "AF",
    "Title":                         "TI",
    "Year":                          "PY",
    "Source title":                  "SO",
    "Abbreviated Source Title":      "JI",
    "Volume":                        "VL",
    "Issue":                         "IS",
    "Page start":                    "BP",
    "Page end":                      "EP",
    "Cited by":                      "TC",
    "DOI":                           "DI",
    "Authors with affiliations":     "C1",
    "Correspondence Address":        "RP",
    "Abstract":                      "AB",
    "Author Keywords":               "DE",
    "Index Keywords":                "ID",
    "References":                    "CR",
    "PubMed ID":                     "PMID",
    "Language of Original Document": "LA",
    "Document Type":                 "DT",
    "EID":                           "UT",
}

DIMENSIONS_MAP = {
    "Publication ID":            "UT",    # e.g. "pub.1195337241"
    "DOI":                       "DI",
    "PMID":                      "PMID",
    "Title":                     "TI",
    "Abstract":                  "AB",
    "Source title":              "SO",
    "PubYear":                   "PY",    # already numeric
    "Volume":                    "VL",
    "Issue":                     "IS",
    "Publication Type":          "DT",    # "Chapter", "Article", ...
    "Authors":                   "AU",    # "Surname, First; Surname, First"
    "Authors (Raw Affiliation)": "C1",    # per-author "(affil)" -> keeps linkage
    "Corresponding Authors":     "RP",
    "Times cited":               "TC",
    "MeSH terms":                "ID",    # controlled keywords -> Index Keywords
    # No References column in Dimensions free export -> CR stays []
    # No author keywords column -> DE stays []
    # No ISO abbreviation -> JI stays "" (SR falls back to SO)
    # "Pagination" handled separately -> split into BP / EP
}
OPENALEX_MAP = {
    # filled in the Advanced API layer
}

# Dispatcher: source name -> (mapping dict, DB label, multi-value delimiter)
SOURCE_REGISTRY = {
    "scopus":     (SCOPUS_MAP,     "SCOPUS",     ";"),
    "dimensions": (DIMENSIONS_MAP, "DIMENSIONS", ";"),
    "openalex":   (OPENALEX_MAP,   "OPENALEX",   "|"),
}

# ----------------------------------------------------------------------
# Country-name normalization: source spelling -> countries.txt spelling.
# Applied to C1 affiliation strings so AU_CO country matching succeeds.
# ----------------------------------------------------------------------
COUNTRY_NORMALIZATION = {
    "Viet Nam": "Vietnam",
    "Russian Federation": "Russia",
    "Korea, Republic of": "South Korea",
    "Czech Republic": "Czech Republic",
}

def standardize(raw_df: pd.DataFrame, source: str) -> pd.DataFrame:
    """
    Transform a raw source DataFrame into the standardized WoS schema.

    Args:
        raw_df: The raw DataFrame as loaded from a source export or API.
        source: Source key, one of SOURCE_REGISTRY (e.g. "scopus").

    Returns:
        A DataFrame conforming to TARGET_SCHEMA with enforced type contracts.
    """
    if source not in SOURCE_REGISTRY:
        raise ValueError(f"Unknown source '{source}'. Known: {list(SOURCE_REGISTRY)}")

    mapping, db_label, delimiter = SOURCE_REGISTRY[source]

    df = _rename_columns(raw_df, mapping)

    # Source-specific structural transforms (things a rename can't express)
    if source == "dimensions" and "Pagination" in raw_df.columns:
        pages = raw_df["Pagination"].fillna("").astype(str).str.split("-", n=1, expand=True)
        df["BP"] = pages[0].fillna("")
        df["EP"] = pages[1].fillna("") if pages.shape[1] > 1 else ""

    df = _ensure_all_columns(df)
    df = _enforce_types(df, delimiter)
    df["DB"] = db_label
    # Keep ONLY the standardized WoS schema; drop unmapped source columns
    # (this is what removes the leftover NaN-bearing Scopus extras)
    df = df[TARGET_SCHEMA]
    return df
  
 



def _rename_columns(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Rename source columns to WoS tags using the mapping dictionary."""
    return df.rename(columns=mapping)


def _ensure_all_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add any missing target columns so the schema is always complete."""
    for col in TARGET_SCHEMA:
        if col not in df.columns:
            df[col] = np.nan
    return df
 

def _enforce_types(df: pd.DataFrame, delimiter: str) -> pd.DataFrame:
    """
    Apply type contracts:
      - list columns -> list[str], nulls -> []
      - int columns  -> int, nulls -> 0
      - scalar str   -> str, nulls -> ""
    """
    
    for col in LIST_COLUMNS:
        if col == "CR":
            df[col] = df[col].apply(_split_scopus_references)
        else:
            df[col] = df[col].apply(lambda v: _to_list(v, delimiter))
    # Normalize country spellings in affiliations (C1) for reliable AU_CO extraction
    if "C1" in df.columns:
        df["C1"] = df["C1"].apply(_normalize_countries)

    for col in INT_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    
    scalar_cols = [c for c in TARGET_SCHEMA if c not in LIST_COLUMNS + INT_COLUMNS]
    for col in scalar_cols:
        df[col] = df[col].fillna("").astype(str).replace("nan", "")

    return df

import re  # add at top of file if not already imported

def _split_scopus_references(value) -> list:
    """
    Split a Scopus 'References' field into individual references.

    Scopus separates references with '; ' but ALSO uses '; ' between co-authors
    within a single reference. Real references reliably end with '(YEAR)', so we
    split only on '; ' that follows a closing parenthesis.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    # Split on "; " only when preceded by ")"  -> reference boundary after (year)
    parts = re.split(r"(?<=\));\s+", text)
    return [p.strip() for p in parts if p.strip()]

def _to_list(value, delimiter: str) -> list:
    """Convert a delimited string / NaN / list into a clean list[str]."""
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [part.strip() for part in str(value).split(delimiter) if part.strip()]

def _normalize_countries(affiliations: list) -> list:
    """Canonicalize country-name spelling variants at the end of each affiliation string."""
    out = []
    for aff in affiliations:
        for variant, canonical in COUNTRY_NORMALIZATION.items():
            if aff.endswith(variant):
                aff = aff[: -len(variant)] + canonical
        out.append(aff)
    return out

def load_dimensions_xlsx(path: str) -> pd.DataFrame:
    """
    Load a Dimensions XLSX export.

    Dimensions places a disclaimer/notice row above the real header row,
    so the file must be read with skiprows=1 to get correct column names.
    """
    return pd.read_excel(path, skiprows=1)

def validate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validate that a standardized DataFrame conforms to the WoS schema contract.

    Checks:
      - every column in TARGET_SCHEMA is present
      - no NaN/None values remain
      - all LIST_COLUMNS contain Python lists
      - all INT_COLUMNS are integer-typed

    Raises:
        ValueError: if any contract is violated.

    Returns:
        The same DataFrame, unchanged, if all checks pass.
    """
    missing = [c for c in TARGET_SCHEMA if c not in df.columns]
    if missing:
        raise ValueError(f"Missing mandatory columns: {missing}")

    if df.isna().any().any():
        bad = df.columns[df.isna().any()].tolist()
        raise ValueError(f"NaN/None values remain in columns: {bad}")

    for col in LIST_COLUMNS:
        nonlist = df[col].apply(lambda v: not isinstance(v, list))
        if nonlist.any():
            raise ValueError(f"Column '{col}' contains non-list values.")

    for col in INT_COLUMNS:
        if not pd.api.types.is_integer_dtype(df[col]):
            raise ValueError(f"Column '{col}' is not integer-typed.")

    return df