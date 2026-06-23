from pathlib import Path
import sqlite3

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]

API_BASE_URL = "http://127.0.0.1:8000"

DECISION_EXPORT_URL = f"{API_BASE_URL}/decision_export"
COMPARISON_URL = f"{API_BASE_URL}/comparison"
OPERATING_CURVE_URL = f"{API_BASE_URL}/operating_curve"

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

DECISION_EXPORT_CSV = PROCESSED_DIR / "thesis_decision_export.csv"
OPERATIONAL_SUMMARY_CSV = PROCESSED_DIR / "thesis_operational_summary.csv"
OPERATING_CURVE_CSV = PROCESSED_DIR / "thesis_operating_curve.csv"

DATABASE_PATH = PROCESSED_DIR / "fraud_investigation.db"


SIMULATION_LIMITS = [1000, 3000, 10000, 50000]

BASE_PARAMS = {
    "investigation_cost": 10,
    "ranking_policy": "risk_zone",
    "risk_zone_floor": 0.3,
    "budget_multiplier": 1.4,
}


def get_json(url: str, params: dict) -> dict | list:
    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()
    return response.json()


def fetch_thesis_decisions(params: dict) -> pd.DataFrame:
    data = get_json(DECISION_EXPORT_URL, params=params)
    df = pd.DataFrame(data)

    if df.empty:
        raise ValueError("No row-level decision data returned from Thesis API.")

    return df


def prepare_thesis_investigation_dataset(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["transaction_type"] = df["type"]
    df["alert_flag"] = df["adaptive_alert"]
    df["fraud_label"] = df["isFraud"]
    df["priority_score"] = df["rank_score"]
    df["alert_severity"] = df["severity"]
    df["alert_reason"] = df["reason"]

    df["expected_loss"] = df["expected_benefit"].clip(lower=0)

    df["investigation_status"] = "NOT_REVIEWED"

    df.loc[df["adaptive_alert"] == 1, "investigation_status"] = "ALERT_GENERATED"

    df.loc[
        df["selected_for_review"] == 1,
        "investigation_status",
    ] = "SELECTED_FOR_REVIEW"

    df.loc[
        (df["selected_for_review"] == 1) & (df["fraud_label"] == 1),
        "investigation_status",
    ] = "CONFIRMED_FRAUD"

    df.loc[
        df["budget_overflow"] == 1,
        "investigation_status",
    ] = "BUDGET_OVERFLOW"

    return df


def fetch_operational_summary(params: dict) -> pd.DataFrame:
    data = get_json(COMPARISON_URL, params=params)

    static_metrics = data["static"]
    decision_metrics = data["decision_system"]
    api_parameters = data["parameters"]
    business_kpis = data.get("business_kpis", {})

    static_row = {
        "system": "static_threshold",
        **api_parameters,
        **static_metrics,
        "cost_diff_vs_static": 0,
        "recall_diff_vs_static": 0,
        "precision_diff_vs_static": 0,
        "missed_fraud_cost_diff_vs_static": 0,
        "fraud_loss_prevented_diff_vs_static": 0,
    }

    adaptive_row = {
        "system": "adaptive_decision_system",
        **api_parameters,
        **decision_metrics,
        "cost_diff_vs_static": data["cost_diff"],
        "recall_diff_vs_static": data["recall_diff"],
        "precision_diff_vs_static": data["precision_diff"],
        "missed_fraud_cost_diff_vs_static": data["missed_fraud_cost_diff"],
        "fraud_loss_prevented_diff_vs_static": data["fraud_loss_prevented_diff"],
        **business_kpis,
    }

    return pd.DataFrame([static_row, adaptive_row])


def fetch_operating_curve(params: dict) -> pd.DataFrame:
    curve_params = params.copy()
    curve_params.pop("budget_multiplier", None)

    data = get_json(OPERATING_CURVE_URL, params=curve_params)
    curve_df = pd.DataFrame(data["operating_curve"])

    if curve_df.empty:
        raise ValueError("No operating curve data returned from Thesis API.")

    for key, value in data["parameters"].items():
        curve_df[key] = value

    return curve_df


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"CSV saved to: {path}")


def save_to_sqlite(tables: dict[str, pd.DataFrame]) -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)

    for table_name, df in tables.items():
        df.to_sql(
            table_name,
            connection,
            if_exists="replace",
            index=False,
        )
        print(f"SQLite table saved: {table_name} ({len(df):,} rows)")

    connection.close()
    print(f"Database: {DATABASE_PATH}")


def main() -> None:
    print("Importing multi-limit outputs from Thesis API...")

    all_decisions = []
    all_investigations = []
    all_summaries = []
    all_curves = []

    for limit in SIMULATION_LIMITS:
        print(f"\nImporting simulation limit: {limit:,}")

        params = BASE_PARAMS.copy()
        params["limit"] = limit

        decision_df = fetch_thesis_decisions(params)
        investigation_df = prepare_thesis_investigation_dataset(decision_df)
        summary_df = fetch_operational_summary(params)
        curve_df = fetch_operating_curve(params)

        decision_df["simulation_limit"] = limit
        investigation_df["simulation_limit"] = limit
        summary_df["simulation_limit"] = limit
        curve_df["simulation_limit"] = limit

        all_decisions.append(decision_df)
        all_investigations.append(investigation_df)
        all_summaries.append(summary_df)
        all_curves.append(curve_df)

        print(f"Rows imported: {len(decision_df):,}")
        print(f"Alerts: {int(decision_df['alert'].sum()):,}")
        print(f"Selected for review: {int(decision_df['selected_for_review'].sum()):,}")
        print(f"Confirmed frauds: {int(decision_df['isFraud'].sum()):,}")

    decision_all_df = pd.concat(all_decisions, ignore_index=True)
    investigation_all_df = pd.concat(all_investigations, ignore_index=True)
    summary_all_df = pd.concat(all_summaries, ignore_index=True)
    curve_all_df = pd.concat(all_curves, ignore_index=True)

    save_csv(decision_all_df, DECISION_EXPORT_CSV)
    save_csv(summary_all_df, OPERATIONAL_SUMMARY_CSV)
    save_csv(curve_all_df, OPERATING_CURVE_CSV)

    save_to_sqlite(
        {
            "thesis_decision_export": decision_all_df,
            "thesis_investigation_dataset": investigation_all_df,
            "thesis_operational_summary": summary_all_df,
            "thesis_operating_curve": curve_all_df,
        }
    )

    print("\nMulti-limit import completed successfully.")


if __name__ == "__main__":
    main()