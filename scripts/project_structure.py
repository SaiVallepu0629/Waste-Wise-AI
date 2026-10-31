
from pathlib import Path
import argparse

PROJECT_STRUCTURE = {
    "frontend": {
        "public": {},
        "src": {
            "assets": {},
            "components": {
                "common": {},
                "charts": {},
                "tables": {},
                "forms": {},
            },
            "layouts": {
                "MainLayout.tsx": None,
                "AuthLayout.tsx": None,
            },
            "pages": {
                "Login.tsx": None,
                "Dashboard.tsx": None,
                "Products.tsx": None,
                "Inventory.tsx": None,
                "SalesHistory.tsx": None,
                "DemandForecast.tsx": None,
                "ExpiryRisk.tsx": None,
                "Recommendations.tsx": None,
                "WasteReports.tsx": None,
                "ModelMetrics.tsx": None,
            },
            "services": {
                "api.ts": None,
                "products.ts": None,
                "inventory.ts": None,
                "predictions.ts": None,
            },
            "hooks": {},
            "types": {},
            "utils": {},
            "App.tsx": None,
            "main.tsx": None,
        },
        "package.json": None,
        "vite.config.ts": None,
    },
    "backend": {
        "app": {
            "api": {
                "v1": {
                    "auth.py": None,
                    "dashboard.py": None,
                    "products.py": None,
                    "batches.py": None,
                    "sales.py": None,
                    "forecasts.py": None,
                    "risk.py": None,
                    "recommendations.py": None,
                    "waste.py": None,
                }
            },
            "core": {
                "config.py": None,
                "security.py": None,
            },
            "db": {
                "session.py": None,
                "base.py": None,
            },
            "models": {
                "user.py": None,
                "product.py": None,
                "inventory.py": None,
                "sales.py": None,
                "prediction.py": None,
            },
            "schemas": {},
            "services": {
                "inventory_service.py": None,
                "forecast_service.py": None,
                "recommendation_service.py": None,
            },
            "repositories": {},
            "main.py": None,
            "dependencies.py": None,
        },
        "tests": {},
        "requirements.txt": None,
        ".env.example": None,
    },
    "ml": {
        "data": {
            "raw": {},
            "interim": {},
            "processed": {},
        },
        "notebooks": {
            "01_data_understanding.ipynb": None,
            "02_eda.ipynb": None,
            "03_feature_engineering.ipynb": None,
            "04_demand_forecasting.ipynb": None,
            "05_expiry_risk_model.ipynb": None,
            "06_model_evaluation.ipynb": None,
        },
        "src": {
            "data_validation.py": None,
            "preprocessing.py": None,
            "feature_engineering.py": None,
            "train_forecast.py": None,
            "train_expiry_risk.py": None,
            "evaluate.py": None,
            "predict.py": None,
        },
        "artifacts": {},
        "tests": {},
        "requirements.txt": None,
    },
    "database": {
        "schema.sql": None,
        "seed_data.sql": None,
        "migrations": {},
    },
    "scripts": {
        "import_dataset.py": None,
        "generate_demo_data.py": None,
        "validate_data.py": None,
    },
    "docs": {
        "project_report.md": None,
        "api_documentation.md": None,
        "database_design.md": None,
        "model_card.md": None,
    },
    "docker-compose.yml": None,
    ".gitignore": None,
    "README.md": None,
}


def create_structure(base_path: Path, structure: dict) -> None:
    """Create folders and empty files recursively."""

    for name, content in structure.items():
        path = base_path / name

        if isinstance(content, dict):
            path.mkdir(parents=True, exist_ok=True)
            create_structure(path, content)

        elif content is None:
            path.parent.mkdir(parents=True, exist_ok=True)

            if not path.exists():
                path.touch()
                print(f"[FILE] {path}")
            else:
                print(f"[SKIP] {path} already exists")


def main():
    parser = argparse.ArgumentParser(
        description="Create the WasteWise-AI project structure."
    )
    parser.add_argument(
        "--path",
        default=None,
        help="Project directory to initialize (default: this script's project)",
    )
    args = parser.parse_args()

    project_root = (
        Path(args.path).expanduser().resolve()
        if args.path
        else Path(__file__).resolve().parents[1]
    )

    project_root.mkdir(parents=True, exist_ok=True)
    create_structure(project_root, PROJECT_STRUCTURE)

    print("\n" + "=" * 55)
    print("WasteWise-AI project structure created successfully!")
    print(f"Project location: {project_root}")
    print("=" * 55)


if __name__ == "__main__":
    main()
