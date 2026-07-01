"""Quick smoke tests for the ETL pipeline — run: python -m tests.test_pipeline"""
import pandas as pd
from shiny import reactive
from www.services.standardizer import standardize, validate
from www.services.metatagextraction import metaTagExtraction
from www.services.biblionetwork import biblionetwork

SAMPLE = "sources/samples/scopus_sample.csv"


def main():
    raw = pd.read_csv(SAMPLE)
    out = standardize(raw, "scopus")

    print("=== 1. Standardize + validate ===")
    validate(out)
    print("columns:", list(out.columns))
    print("shape:", out.shape, "| any NaN:", out.isna().any().any())

    print("\n=== 2. SR generation ===")
    w = reactive.Value(out.copy())
    with reactive.isolate():
        metaTagExtraction(w, "SR")
        r = w.get()
    print(r[["AU", "PY", "JI", "SR"]].head(3).to_string())

    print("\n=== 3. AU_CO country extraction ===")
    w = reactive.Value(out.copy())
    with reactive.isolate():
        metaTagExtraction(w, "AU_CO")
        r = w.get()
    for i in range(min(3, len(r))):
        print("C1 first:", r["C1"].iloc[i][:1])
        print("AU_CO   :", r["AU_CO"].iloc[i])
        print("---")

    print("\n=== 4. Keyword co-occurrence (ID) ===")
    w = reactive.Value(out.copy())
    with reactive.isolate():
        net = biblionetwork(w, analysis="co-occurrences", network="keywords", n=20, sep=";")
    print("keyword co-occ matrix:", type(net).__name__, getattr(net, "shape", "n/a"))

    print("\n=== 5. References (CR) ===")
    print("CR count row 0:", len(out["CR"].iloc[0]))
    print("first ref:", repr(out["CR"].iloc[0][0])[:200] if out["CR"].iloc[0] else "EMPTY")
    w = reactive.Value(out.copy())
    with reactive.isolate():
        metaTagExtraction(w, "CR_AU")
        metaTagExtraction(w, "CR_SO")
        r = w.get()
    print("CR_AU row0:", repr(r["CR_AU"].iloc[0])[:150])
    print("CR_SO row0:", repr(r["CR_SO"].iloc[0])[:150])


if __name__ == "__main__":
    main()