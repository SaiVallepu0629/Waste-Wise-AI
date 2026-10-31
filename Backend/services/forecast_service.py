from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

PROJECT_DIR = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_DIR / "ml" / "artifacts" / "demand_forecast_model.pkl"
SALES_PATH = PROJECT_DIR / "ml" / "data" / "raw" / "perishable_inventory.csv"
PRODUCTS_PATH = PROJECT_DIR / "ml" / "data" / "raw" / "products.csv"

FEATURES = [
    "day_of_week",
    "month",
    "day_of_month",
    "sales_lag_1",
    "sales_lag_7",
    "rolling_mean_7",
]
REQUIRED_SALES_COLUMNS = {"date", "product_id", "units_sold"}
REQUIRED_PRODUCT_COLUMNS = {"product_id", "product_name"}
MIN_HISTORY_DAYS = 8


class ForecastServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


def _read_csv(path: Path, required_columns: set[str]) -> pd.DataFrame:
    if not path.is_file():
        raise ForecastServiceError(f"Required file was not found: {path.name}", 404)

    try:
        dataframe = pd.read_csv(path)
    except (
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        OSError,
        UnicodeDecodeError,
    ) as exc:
        raise ForecastServiceError(
            f"Could not read {path.name}; check that it is a valid CSV."
        ) from exc

    if dataframe.empty:
        raise ForecastServiceError(f"{path.name} contains no data rows.")

    missing_columns = required_columns - set(dataframe.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ForecastServiceError(
            f"{path.name} is missing required columns: {missing}."
        )
    return dataframe


@lru_cache(maxsize=4)
def _load_model_bundle(path_string: str) -> tuple[Any, tuple[str, ...]]:
    path = Path(path_string)
    if not path.is_file():
        raise ForecastServiceError(
            f"Demand forecast model was not found: {path.name}", 503
        )

    try:
        bundle = joblib.load(path)
    except (
        OSError,
        EOFError,
        ImportError,
        AttributeError,
        ValueError,
        ModuleNotFoundError,
    ) as exc:
        raise ForecastServiceError(
            "The saved demand forecast model could not be loaded. "
            "Check its file integrity and Scikit-learn compatibility.",
            503,
        ) from exc

    if not isinstance(bundle, dict) or "model" not in bundle or "features" not in bundle:
        raise ForecastServiceError(
            "The saved model must contain both 'model' and 'features'.", 503
        )

    model = bundle["model"]
    features = tuple(bundle["features"])
    if not callable(getattr(model, "predict", None)):
        raise ForecastServiceError(
            "The saved model does not provide a prediction method.", 503
        )
    if features != tuple(FEATURES):
        raise ForecastServiceError(
            "The saved model feature list does not match the notebook feature pipeline.",
            503,
        )

    model_feature_names = getattr(model, "feature_names_in_", None)
    if model_feature_names is not None and tuple(model_feature_names) != features:
        raise ForecastServiceError(
            "The saved model's fitted feature names do not match its feature metadata.",
            503,
        )
    model_feature_count = getattr(model, "n_features_in_", len(features))
    if model_feature_count != len(features):
        raise ForecastServiceError(
            "The saved model's fitted feature count does not match its metadata.", 503
        )
    return model, features


def _normalize_product_ids(values: pd.Series, file_name: str) -> pd.Series:
    numeric_ids = pd.to_numeric(values, errors="coerce")
    invalid = (
        numeric_ids.isna()
        | ~np.isfinite(numeric_ids)
        | (numeric_ids % 1 != 0)
    )
    if invalid.any():
        raise ForecastServiceError(
            f"{file_name} contains missing or invalid product IDs."
        )
    return numeric_ids.astype("int64").astype("string")


def _load_sales_data() -> tuple[pd.DataFrame, int]:
    raw = _read_csv(SALES_PATH, REQUIRED_SALES_COLUMNS)
    sales = raw[["date", "product_id", "units_sold"]].copy()
    sales["date"] = pd.to_datetime(sales["date"], errors="coerce")
    sales["product_id"] = pd.to_numeric(sales["product_id"], errors="coerce")
    sales["units_sold"] = pd.to_numeric(sales["units_sold"], errors="coerce")

    valid_rows = (
        sales["date"].notna()
        & sales["product_id"].notna()
        & np.isfinite(sales["product_id"])
        & (sales["product_id"] % 1 == 0)
        & sales["units_sold"].notna()
        & np.isfinite(sales["units_sold"])
        & (sales["units_sold"] >= 0)
    )
    dropped_rows = int((~valid_rows).sum())
    sales = sales.loc[valid_rows].copy()
    if sales.empty:
        raise ForecastServiceError(
            f"{SALES_PATH.name} contains no valid sales observations."
        )

    sales["product_id"] = sales["product_id"].astype("int64").astype("string")
    sales = (
        sales.groupby(["product_id", "date"], as_index=False)["units_sold"]
        .sum()
        .sort_values(["product_id", "date"])
        .reset_index(drop=True)
    )
    return sales, dropped_rows


def _load_products() -> pd.DataFrame:
    products = _read_csv(PRODUCTS_PATH, REQUIRED_PRODUCT_COLUMNS)
    products = products.copy()
    products["product_id"] = _normalize_product_ids(
        products["product_id"], PRODUCTS_PATH.name
    )
    products["product_name"] = products["product_name"].astype("string").str.strip()
    if products["product_name"].isna().any() or products["product_name"].eq("").any():
        raise ForecastServiceError(
            f"{PRODUCTS_PATH.name} contains missing product names."
        )
    if products["product_id"].duplicated().any():
        raise ForecastServiceError(
            f"{PRODUCTS_PATH.name} contains duplicate product IDs."
        )
    return products


def _prepare_model_data(sales: pd.DataFrame) -> pd.DataFrame:
    engineered = sales.copy()
    engineered["day_of_week"] = engineered["date"].dt.day_of_week
    engineered["month"] = engineered["date"].dt.month
    engineered["day_of_month"] = engineered["date"].dt.day

    grouped_sales = engineered.groupby("product_id", sort=False)["units_sold"]
    engineered["sales_lag_1"] = grouped_sales.shift(1)
    engineered["sales_lag_7"] = grouped_sales.shift(7)
    engineered["rolling_mean_7"] = engineered.groupby(
        "product_id", sort=False
    )["units_sold"].transform(
        lambda values: values.shift(1).rolling(7).mean()
    )

    model_data = engineered.dropna(subset=FEATURES).copy()
    if model_data.empty:
        raise ForecastServiceError(
            "Not enough consecutive sales history to calculate the model features."
        )
    model_data["product_id"] = model_data["product_id"].astype("string")
    return model_data.sort_values(["date", "product_id"]).reset_index(drop=True)


def _split_by_date(model_data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    unique_dates = sorted(model_data["date"].unique())
    if len(unique_dates) < 5:
        raise ForecastServiceError(
            "At least five distinct feature dates are required for chronological evaluation."
        )
    split_index = int(len(unique_dates) * 0.8)
    if split_index >= len(unique_dates):
        raise ForecastServiceError("The chronological evaluation split is invalid.")

    cutoff_date = pd.Timestamp(unique_dates[split_index])
    train = model_data.loc[model_data["date"] < cutoff_date].copy()
    test = model_data.loc[model_data["date"] >= cutoff_date].copy()
    if train.empty or test.empty:
        raise ForecastServiceError(
            "The chronological evaluation split produced an empty partition."
        )
    return train, test, cutoff_date


def _metrics(actual: pd.Series, predicted: np.ndarray) -> dict[str, float | None]:
    r_squared = (
        float(r2_score(actual, predicted))
        if len(actual) >= 2 and actual.nunique() > 1
        else None
    )
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "r2": r_squared,
    }


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value.item() if isinstance(value, np.generic) else value


@lru_cache(maxsize=1)
def _load_evaluation() -> dict[str, Any]:
    model, features = _load_model_bundle(str(MODEL_PATH))
    sales, dropped_rows = _load_sales_data()
    model_data = _prepare_model_data(sales)
    _, test, cutoff_date = _split_by_date(model_data)
    test_features = test.loc[:, list(features)]
    if not np.isfinite(test_features.to_numpy(dtype=float)).all():
        raise ForecastServiceError(
            "Evaluation features contain missing or non-finite values."
        )

    try:
        predictions = np.asarray(model.predict(test_features), dtype=float)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ForecastServiceError(
            "The saved model could not predict from the notebook-compatible "
            "feature matrix. Check the installed Scikit-learn version.",
            503,
        ) from exc
    if predictions.ndim != 1 or len(predictions) != len(test):
        raise ForecastServiceError(
            "The saved model returned predictions with an unexpected shape.", 503
        )
    if not np.isfinite(predictions).all():
        raise ForecastServiceError(
            "The saved model returned non-finite predictions.", 503
        )

    test = test.copy()
    test["predicted_units"] = np.maximum(predictions, 0)
    products = _load_products()
    product_ids = set(products["product_id"])
    unknown_products = set(sales["product_id"]) - product_ids
    if unknown_products:
        unknown = ", ".join(sorted(unknown_products))
        raise ForecastServiceError(
            f"{SALES_PATH.name} contains product IDs missing from "
            f"{PRODUCTS_PATH.name}: {unknown}."
        )

    latest_observation_date = sales["date"].max()
    current_date = pd.Timestamp(date.today())
    future_forecast_supported = latest_observation_date >= current_date
    if future_forecast_supported:
        future_forecast_reason = (
            "The available sales history reaches today, but the model has only "
            "been verified for rolling one-day-ahead predictions; multi-day "
            "future forecasts have not been validated."
        )
        future_forecast_supported = False
    else:
        gap_days = (current_date - latest_observation_date).days
        future_forecast_reason = (
            f"Sales data ends on {latest_observation_date.date()}, "
            f"{gap_days} days before today. Forecasts after the data cutoff "
            "would not represent current demand. The model was also evaluated "
            "only in rolling one-day-ahead mode, not for recursive multi-day forecasts."
        )

    return {
        "model": model,
        "features": features,
        "sales": sales,
        "model_data": model_data,
        "test": test,
        "products": products,
        "cutoff_date": cutoff_date,
        "dropped_rows": dropped_rows,
        "latest_observation_date": latest_observation_date,
        "metrics": _metrics(test["units_sold"], test["predicted_units"].to_numpy()),
        "future_forecast_supported": future_forecast_supported,
        "future_forecast_reason": future_forecast_reason,
    }


def _prediction_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    ordered = frame.sort_values("date")
    return [
        {
            "date": row.date.strftime("%Y-%m-%d"),
            "actual_units": float(row.units_sold),
            "predicted_units": float(row.predicted_units),
        }
        for row in ordered.itertuples(index=False)
    ]


def get_forecast_summary() -> dict[str, Any]:
    evaluation = _load_evaluation()
    sales = evaluation["sales"]
    model = evaluation["model"]
    return {
        "model": {
            "name": type(model).__name__,
            "artifact": "ml/artifacts/demand_forecast_model.pkl",
            "features": list(evaluation["features"]),
            "scikit_learn_version": sklearn.__version__,
        },
        "evaluation": {
            "method": "Chronological 80/20 split by distinct feature dates",
            "prediction_mode": (
                "Rolling one-day-ahead: each held-out day uses observed sales "
                "from earlier days, including earlier days in the test window."
            ),
            "cutoff_date": evaluation["cutoff_date"].strftime("%Y-%m-%d"),
            "test_start_date": evaluation["test"]["date"].min().strftime("%Y-%m-%d"),
            "test_end_date": evaluation["test"]["date"].max().strftime("%Y-%m-%d"),
            "test_rows": len(evaluation["test"]),
            "metrics": evaluation["metrics"],
        },
        "data": {
            "source": "ml/data/raw/perishable_inventory.csv",
            "first_observation_date": sales["date"].min().strftime("%Y-%m-%d"),
            "last_observation_date": evaluation[
                "latest_observation_date"
            ].strftime("%Y-%m-%d"),
            "product_count": int(sales["product_id"].nunique()),
            "valid_sales_rows": len(sales),
            "invalid_rows_dropped": evaluation["dropped_rows"],
        },
        "future_forecast": {
            "supported": evaluation["future_forecast_supported"],
            "reason": evaluation["future_forecast_reason"],
        },
    }


def get_forecast_products() -> list[dict[str, Any]]:
    evaluation = _load_evaluation()
    sales = evaluation["sales"]
    test = evaluation["test"]
    products = evaluation["products"]
    product_rows = []
    for product in products.itertuples(index=False):
        product_sales = sales.loc[sales["product_id"] == product.product_id]
        product_test = test.loc[test["product_id"] == product.product_id]
        record: dict[str, Any] = {
            "product_id": int(product.product_id),
            "product_name": str(product.product_name),
            "history_rows": len(product_sales),
            "first_observation_date": (
                product_sales["date"].min().strftime("%Y-%m-%d")
                if not product_sales.empty
                else None
            ),
            "last_observation_date": (
                product_sales["date"].max().strftime("%Y-%m-%d")
                if not product_sales.empty
                else None
            ),
            "held_out_prediction_rows": len(product_test),
            "forecast_available": not product_test.empty,
        }
        for field in ("category", "shelf_life_days", "selling_price", "unit_cost"):
            if field in products.columns:
                value = getattr(product, field)
                record[field] = _json_value(value)
        product_rows.append(record)
    return product_rows


def get_product_forecast(product_id: int) -> dict[str, Any]:
    evaluation = _load_evaluation()
    product_key = str(product_id)
    products = evaluation["products"]
    product = products.loc[products["product_id"] == product_key]
    if product.empty:
        raise ForecastServiceError(
            f"Product {product_id} is not present in the product catalog.", 404
        )

    history = evaluation["sales"]
    history = history.loc[history["product_id"] == product_key].sort_values("date")
    if len(history) < MIN_HISTORY_DAYS:
        raise ForecastServiceError(
            f"Product {product_id} has fewer than {MIN_HISTORY_DAYS} valid "
            "sales days; the model cannot calculate its lag features.",
            422,
        )

    predictions = evaluation["test"]
    predictions = predictions.loc[predictions["product_id"] == product_key]
    if predictions.empty:
        raise ForecastServiceError(
            f"Product {product_id} has no held-out predictions in the "
            "chronological evaluation window.",
            422,
        )

    product_test_metrics = _metrics(
        predictions["units_sold"],
        predictions["predicted_units"].to_numpy(),
    )
    row = product.iloc[0]
    product_info: dict[str, Any] = {
        "product_id": int(row["product_id"]),
        "product_name": str(row["product_name"]),
    }
    for field in ("category", "shelf_life_days", "selling_price", "unit_cost"):
        if field in products.columns:
            product_info[field] = _json_value(row[field])

    return {
        "product": product_info,
        "model_features": list(evaluation["features"]),
        "historical_sales": [
            {
                "date": observation.date.strftime("%Y-%m-%d"),
                "actual_units": float(observation.units_sold),
            }
            for observation in history.itertuples(index=False)
        ],
        "held_out_predictions": _prediction_rows(predictions),
        "evaluation": {
            "prediction_mode": "Rolling one-day-ahead",
            "cutoff_date": evaluation["cutoff_date"].strftime("%Y-%m-%d"),
            "test_rows": len(predictions),
            "metrics": product_test_metrics,
        },
        "future_forecast": {
            "supported": evaluation["future_forecast_supported"],
            "reason": evaluation["future_forecast_reason"],
            "records": [],
        },
    }
