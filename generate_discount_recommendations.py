
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
INPUT_FILE = (
    PROJECT_DIR
    / "ml"
    / "data"
    / "raw"
    / "discount_scenarios_simulated.csv"
)
OUTPUT_DIR = PROJECT_DIR / "ml" / "data" / "processed"
OUTPUT_FILE = OUTPUT_DIR / "discount_recommendations.csv"

REQUIRED_COLUMNS = {
    "batch_id",
    "product_id",
    "days_to_expiry",
    "quantity_remaining",
    "discount_pct",
    "estimated_units_sold_simulated",
    "estimated_revenue_simulated",
    "estimated_gross_margin_simulated",
}
NUMERIC_COLUMNS = REQUIRED_COLUMNS - {"batch_id", "product_id"}


def main() -> None:
    if not INPUT_FILE.is_file():
        raise FileNotFoundError(f"Input dataset not found: {INPUT_FILE}")

    df = pd.read_csv(INPUT_FILE)
    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Input dataset is missing required columns: {missing}")

    scenario_count = len(df)
    df["batch_id"] = df["batch_id"].astype("string").str.strip()
    df["product_id"] = df["product_id"].astype("string").str.strip()
    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    valid_rows = (
        df["batch_id"].notna()
        & df["batch_id"].ne("")
        & df["product_id"].notna()
        & df["product_id"].ne("")
        & df[list(NUMERIC_COLUMNS)].notna().all(axis=1)
    )
    skipped_scenarios = int((~valid_rows).sum())
    df = df.loc[valid_rows].copy()
    if df.empty:
        raise ValueError("Input dataset contains no valid discount scenarios.")

    df["estimated_unsold_units"] = (
        df["quantity_remaining"] - df["estimated_units_sold_simulated"]
    ).clip(lower=0)

    # Keep the existing objective: minimize unsold units, then maximize margin,
    # then prefer a smaller discount when the preceding values are tied.
    df = df.sort_values(
        by=[
            "batch_id",
            "estimated_unsold_units",
            "estimated_gross_margin_simulated",
            "discount_pct",
        ],
        ascending=[True, True, False, True],
    )

    recommendations = df.drop_duplicates(subset=["batch_id"]).copy()
    recommendations = recommendations.rename(
        columns={"discount_pct": "recommended_discount_pct"}
    )
    recommendations["recommendation_type"] = "Simulation-based"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    recommendations.to_csv(OUTPUT_FILE, index=False)

    source_batches = df["batch_id"].nunique()
    print("Simulation-based discount recommendations generated.")
    print(f"Input scenarios: {scenario_count}")
    print(f"Invalid scenarios skipped: {skipped_scenarios}")
    print(f"Recommendations generated: {len(recommendations)}")
    print(f"Valid batches with recommendations: {source_batches}")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
