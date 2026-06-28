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
INT_COLUMNS = ["TC"]

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
    "Affiliations":                  "C1",
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
    # filled later from a real Dimensions XLSX export
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
        df[col] = df[col].apply(lambda v: _to_list(v, delimiter))

    for col in INT_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    scalar_cols = [c for c in TARGET_SCHEMA if c not in LIST_COLUMNS + INT_COLUMNS]
    for col in scalar_cols:
        df[col] = df[col].fillna("").astype(str).replace("nan", "")

    return df


def _to_list(value, delimiter: str) -> list:
    """Convert a delimited string / NaN / list into a clean list[str]."""
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [part.strip() for part in str(value).split(delimiter) if part.strip()]