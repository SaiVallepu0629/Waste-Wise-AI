import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from Backend.database import engine, initialize_database
from Backend.models import User
from Backend.routes.auth import router as auth_router
from Backend.routes.inventory import router as inventory_router
from Backend.services.forecast_service import (
    ForecastServiceError,
    get_forecast_products,
    get_forecast_summary,
    get_product_forecast,
)
from Backend.services.inventory_service import risk_level_for
from Backend.security import get_current_user, validate_auth_configuration

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "ml" / "data"
ENVIRONMENT = os.environ.get("WASTEWISE_ENVIRONMENT", "development").strip().lower()
if ENVIRONMENT not in {"development", "production"}:
    raise RuntimeError("WASTEWISE_ENVIRONMENT must be development or production.")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_configuration()
    initialize_database()
    yield


is_production = ENVIRONMENT == "production"
app = FastAPI(
    title="WasteWise-AI API",
    version="1.0.0",
    lifespan=lifespan,
    debug=False,
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json",
)
app.include_router(auth_router)
app.include_router(inventory_router)

configured_cors_origins = os.environ.get("WASTEWISE_CORS_ORIGINS")
if is_production and not configured_cors_origins:
    raise RuntimeError(
        "Set WASTEWISE_CORS_ORIGINS to the exact HTTPS frontend origin(s) in production."
    )

cors_origins = [
    origin.strip()
    for origin in (
        configured_cors_origins
        or "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
if not cors_origins or "*" in cors_origins:
    raise RuntimeError("WASTEWISE_CORS_ORIGINS must be a non-empty explicit origin list.")
if is_production and any(
    urlsplit(origin).scheme != "https"
    or not urlsplit(origin).netloc
    or urlsplit(origin).path
    or urlsplit(origin).query
    or urlsplit(origin).fragment
    for origin in cors_origins
):
    raise RuntimeError(
        "Production CORS origins must be exact HTTPS origins without paths."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


def _read_csv(path: Path, required_columns: set[str]) -> pd.DataFrame:
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Required data file was not found: {path.name}",
        )

    try:
        dataframe = pd.read_csv(path)
    except (
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        OSError,
        UnicodeDecodeError,
    ) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read {path.name}; check that it is a valid CSV.",
        ) from exc

    if dataframe.empty:
        raise HTTPException(
            status_code=500,
            detail=f"{path.name} contains no data rows.",
        )

    missing_columns = required_columns - set(dataframe.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise HTTPException(
            status_code=500,
            detail=f"{path.name} is missing required columns: {missing}.",
        )

    return dataframe


def _require_valid_values(
    dataframe: pd.DataFrame,
    columns: set[str],
    file_name: str,
) -> None:
    invalid_columns = []
    for column in columns:
        values = dataframe[column]
        invalid = values.isna()
        if pd.api.types.is_numeric_dtype(values):
            invalid |= ~np.isfinite(values)
        else:
            invalid |= values.astype("string").str.strip().eq("").fillna(False)
        if invalid.any():
            invalid_columns.append(column)

    if invalid_columns:
        invalid = ", ".join(sorted(invalid_columns))
        raise HTTPException(
            status_code=500,
            detail=f"{file_name} contains missing values in required columns: {invalid}.",
        )


def _records(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    safe_dataframe = dataframe.astype(object).where(pd.notna(dataframe), None)
    return safe_dataframe.to_dict(orient="records")


def _snapshot_status(
    snapshot_date: pd.Series,
    latest_available_date: pd.Timestamp | None,
) -> pd.Series:
    today = pd.Timestamp(date.today())
    return pd.Series(
        [
            "future_snapshot"
            if snapshot > today
            else "latest_available_snapshot"
            if latest_available_date is not None and snapshot == latest_available_date
            else "historical_snapshot"
            for snapshot in snapshot_date
        ],
        index=snapshot_date.index,
        dtype="string",
    )


@app.get("/")
def home() -> dict[str, str]:
    return {"status": "ok", "message": "WasteWise-AI API is running"}


@app.get("/forecast/summary")
def forecast_summary(
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return get_forecast_summary()
    except ForecastServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/forecast/products")
def forecast_products(
    _user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    try:
        return get_forecast_products()
    except ForecastServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/forecast/product/{product_id}")
def forecast_product(
    product_id: int,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return get_product_forecast(product_id)
    except ForecastServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/discount-recommendations")
def get_discount_recommendations(
    _user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    path = DATA_DIR / "processed" / "discount_recommendations.csv"
    required = {
        "batch_id",
        "product_id",
        "recommended_discount_pct",
        "estimated_units_sold_simulated",
        "estimated_gross_margin_simulated",
        "estimated_unsold_units",
        "recommendation_type",
    }
    dataframe = _read_csv(path, required)
    numeric_columns = {
        "recommended_discount_pct",
        "estimated_units_sold_simulated",
        "estimated_gross_margin_simulated",
        "estimated_unsold_units",
    }
    for column in numeric_columns:
        dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")

    _require_valid_values(
        dataframe,
        numeric_columns | {"batch_id", "product_id", "recommendation_type"},
        path.name,
    )
    if dataframe["batch_id"].duplicated().any():
        raise HTTPException(
            status_code=500,
            detail=f"{path.name} contains more than one recommendation per batch.",
        )
    if not dataframe["recommendation_type"].eq("Simulation-based").all():
        raise HTTPException(
            status_code=500,
            detail="Recommendations must be identified as simulation-based.",
        )
    if (dataframe["estimated_unsold_units"] < 0).any():
        raise HTTPException(
            status_code=500,
            detail="Recommendations contain negative estimated unsold units.",
        )
    if (
        (dataframe["recommended_discount_pct"] < 0).any()
        or (dataframe["recommended_discount_pct"] > 100).any()
        or (dataframe["estimated_units_sold_simulated"] < 0).any()
    ):
        raise HTTPException(
            status_code=500,
            detail="Recommendations contain invalid discount or sales estimates.",
        )

    return _records(dataframe)


def _load_inventory() -> tuple[pd.DataFrame, pd.Timestamp]:
    batches_path = DATA_DIR / "raw" / "inventory_batches.csv"
    products_path = DATA_DIR / "raw" / "products.csv"
    batches = _read_csv(
        batches_path,
        {
            "batch_id",
            "product_id",
            "category",
            "snapshot_date",
            "expiry_date",
            "quantity_remaining",
            "expected_demand_before_expiry",
            "expiry_risk_label",
        },
    )
    products = _read_csv(
        products_path,
        {"product_id", "product_name"},
    )

    _require_valid_values(
        batches,
        {"batch_id", "product_id", "snapshot_date", "expiry_date"},
        batches_path.name,
    )
    _require_valid_values(products, {"product_id", "product_name"}, products_path.name)

    batches["snapshot_date"] = pd.to_datetime(
        batches["snapshot_date"], errors="coerce"
    )
    batches["expiry_date"] = pd.to_datetime(
        batches["expiry_date"], errors="coerce"
    )
    if batches[["snapshot_date", "expiry_date"]].isna().any().any():
        raise HTTPException(
            status_code=500,
            detail=f"{batches_path.name} contains invalid snapshot or expiry dates.",
        )
    for column in (
        "quantity_remaining",
        "expected_demand_before_expiry",
        "expiry_risk_label",
    ):
        batches[column] = pd.to_numeric(batches[column], errors="coerce")
    if batches[
        [
            "quantity_remaining",
            "expected_demand_before_expiry",
            "expiry_risk_label",
        ]
    ].isna().any().any():
        raise HTTPException(
            status_code=500,
            detail=f"{batches_path.name} contains invalid inventory or risk values.",
        )
    if not batches["expiry_risk_label"].isin([0, 1]).all():
        raise HTTPException(
            status_code=500,
            detail=f"{batches_path.name} has invalid expiry_risk_label values.",
        )
    if (
        (batches["quantity_remaining"] < 0).any()
        or (batches["expected_demand_before_expiry"] < 0).any()
    ):
        raise HTTPException(
            status_code=500,
            detail=f"{batches_path.name} contains negative inventory or demand values.",
        )
    if not batches["expiry_risk_label"].isin([0, 1]).all():
        raise HTTPException(
            status_code=500,
            detail=f"{batches_path.name} has invalid expiry_risk_label values.",
        )
    if products["product_id"].duplicated().any():
        raise HTTPException(
            status_code=500,
            detail=f"{products_path.name} contains duplicate product IDs.",
        )

    latest_snapshot = batches["snapshot_date"].max()
    observed_snapshots = batches.loc[
        batches["snapshot_date"] <= pd.Timestamp(date.today()), "snapshot_date"
    ]
    latest_available_snapshot = (
        observed_snapshots.max() if not observed_snapshots.empty else None
    )
    batches = batches.merge(
        products[["product_id", "product_name"]],
        on="product_id",
        how="left",
        validate="many_to_one",
    )
    if batches["product_name"].isna().any():
        raise HTTPException(
            status_code=500,
            detail="Some inventory batches do not match a product in products.csv.",
        )

    batches["days_to_expiry_at_snapshot"] = (
        batches["expiry_date"] - batches["snapshot_date"]
    ).dt.days
    quantity = batches["quantity_remaining"].to_numpy(dtype=float)
    demand_before_expiry = batches["expected_demand_before_expiry"].to_numpy(
        dtype=float
    )
    days_to_expiry = batches["days_to_expiry_at_snapshot"].to_numpy(dtype=int)
    projected_surplus = np.maximum(quantity - demand_before_expiry, 0)
    expired_at_snapshot = days_to_expiry < 0
    quantity_at_risk = np.where(expired_at_snapshot, quantity, projected_surplus)
    surplus_ratio = np.divide(
        quantity_at_risk,
        quantity,
        out=np.zeros_like(quantity_at_risk),
        where=quantity > 0,
    )
    urgency_score = np.maximum(0, np.rint((7 - days_to_expiry) / 7 * 35))
    risk_scores = np.minimum(100, np.rint(surplus_ratio * 65 + urgency_score))
    risk_scores = np.where(expired_at_snapshot & (quantity > 0), 100, risk_scores)
    risk_scores = np.where(quantity == 0, 0, risk_scores).astype(int)
    batches["quantity_at_risk_estimate"] = quantity_at_risk
    batches["likely_to_expire_unsold_estimate"] = quantity_at_risk > 0
    batches["rule_based_risk_score_at_snapshot"] = risk_scores
    batches["rule_based_risk_level_at_snapshot"] = [
        risk_level_for(int(score)) for score in risk_scores
    ]
    batches["estimate_basis"] = (
        "Rule-based estimate from quantity_remaining, expected_demand_before_expiry, "
        "and days to expiry at this snapshot; not a trained model prediction or "
        "observed waste."
    )
    batches["snapshot_status"] = _snapshot_status(
        batches["snapshot_date"], latest_available_snapshot
    )
    return batches, latest_snapshot


@app.get("/inventory")
def get_inventory(_user: User = Depends(get_current_user)) -> dict[str, Any]:
    batches, latest_snapshot = _load_inventory()
    latest_available = batches.loc[
        batches["snapshot_status"] == "latest_available_snapshot", "snapshot_date"
    ].max()
    batches = batches.sort_values(
        ["snapshot_date", "batch_id"], ascending=[False, True]
    ).copy()
    batches["snapshot_date"] = batches["snapshot_date"].dt.strftime("%Y-%m-%d")
    batches["expiry_date"] = batches["expiry_date"].dt.strftime("%Y-%m-%d")

    return {
        "source": "ml/data/raw/inventory_batches.csv",
        "latest_snapshot_date": latest_snapshot.strftime("%Y-%m-%d"),
        "latest_available_snapshot_date": (
            latest_available.strftime("%Y-%m-%d")
            if pd.notna(latest_available)
            else None
        ),
        "current_date": date.today().isoformat(),
        "note": (
            "These are dated dataset snapshots, not a live inventory feed. "
            "Rows are marked historical_snapshot, latest_available_snapshot, "
            "or future_snapshot; future-dated rows are not current inventory."
        ),
        "records": _records(batches),
    }


@app.get("/expiry-risk")
def get_expiry_risk(_user: User = Depends(get_current_user)) -> dict[str, Any]:
    batches, latest_snapshot = _load_inventory()
    latest_available = batches.loc[
        batches["snapshot_status"] == "latest_available_snapshot", "snapshot_date"
    ].max()
    batches["expiry_risk_label"] = batches["expiry_risk_label"].astype(int)
    batches["risk_status"] = batches["expiry_risk_label"].map(
        {1: "Flagged by source label", 0: "Not flagged by source label"}
    )
    batches = batches.sort_values(
        ["snapshot_date", "batch_id"], ascending=[False, True]
    ).copy()
    batches["snapshot_date"] = batches["snapshot_date"].dt.strftime("%Y-%m-%d")
    batches["expiry_date"] = batches["expiry_date"].dt.strftime("%Y-%m-%d")

    snapshot_counts = (
        batches.groupby("snapshot_status", observed=True)
        .size()
        .to_dict()
    )
    risk_counts = (
        batches.groupby("risk_status", observed=True)
        .size()
        .to_dict()
    )

    return {
        "source": "ml/data/raw/inventory_batches.csv",
        "risk_label_source": "expiry_risk_label",
        "latest_snapshot_date": latest_snapshot.strftime("%Y-%m-%d"),
        "latest_available_snapshot_date": (
            latest_available.strftime("%Y-%m-%d")
            if pd.notna(latest_available)
            else None
        ),
        "current_date": date.today().isoformat(),
        "note": (
            "Risk flags are the labels already present in the dataset, not new "
            "predictions. Additional risk levels and quantity-at-risk values are "
            "rule-based estimates using each row's snapshot data, not a trained "
            "model prediction or observed waste. Days to expiry are calculated "
            "from each row's snapshot_date and expiry_date. Snapshot status "
            "distinguishes historical, latest, and future-dated records."
        ),
        "summary": {
            "total_batches": len(batches),
            "risk_label_counts": risk_counts,
            "snapshot_status_counts": snapshot_counts,
        },
        "records": _records(batches),
    }
