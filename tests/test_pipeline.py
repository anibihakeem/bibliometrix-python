"""Quick smoke tests for the ETL pipeline — run: python -m tests.test_pipeline"""
import pandas as pd
from shiny import reactive
from www.services.standardizer import standardize, validate
from www.services.metatagextraction import metaTagExtraction

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
    for i in range(min(5, len(r))):
        print("C1 first:", r["C1"].iloc[i][:1])
        print("AU_CO   :", r["AU_CO"].iloc[i])
        print("---")

if __name__ == "__main__":
    main()