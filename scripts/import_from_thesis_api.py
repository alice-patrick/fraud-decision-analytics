"""Import Main /simulation/sequential outputs into SQLite for analytics only.

No scoring or simulation logic is implemented here. All requested runs validate
before a staged database atomically replaces the previous database.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = ROOT / "data" / "processed" / "fraud_investigation.db"
ENDPOINT = "/simulation/sequential"
DEFAULT_LIMITS = [1000, 3000, 10000]
BASE_PARAMS = {
    "investigation_cost": 10.0, "static_threshold": 0.5,
    "ranking_policy": "risk_zone", "risk_zone_floor": 0.3,
    "budget_multiplier": 1.4, "alert_budget_per_step": 30,
    "suppression_window": 3, "monitoring_window_size": 1000,
}
SUMMARY_COLUMNS = [
    "total_transactions", "total_frauds", "policy_candidate_alerts", "selected_alerts",
    "suppressed_alerts", "capacity_rejected_alerts", "frauds_detected", "frauds_missed",
    "false_positives", "suppressed_frauds", "capacity_rejected_frauds", "precision", "recall",
    "suppression_rate", "alert_acceptance_rate", "investigation_cost_total",
    "missed_fraud_cost", "fraud_loss_prevented", "total_operational_cost",
]
DECISION_COLUMNS = [
    "transaction_id", "step", "type", "amount", "fraud_score", "rank_score",
    "policy_name", "policy_alert_candidate", "candidate_priority_rank", "accepted_priority_rank",
    "selected_alert", "suppression_applied", "capacity_rejected", "sequential_decision",
    "capacity_used_before_decision", "capacity_remaining_after_decision", "isFraud",
]
TYPE_COLUMNS = [
    "type", "transactions", "actual_frauds", "candidate_alerts", "investigated_alerts",
    "average_fraud_score", "actual_fraud_rate",
]
STEP_COLUMNS = [
    "step", "transactions_processed", "frauds_present", "frauds_detected", "candidate_alerts",
    "suppressed_alerts", "eligible_alerts", "investigated_alerts", "capacity_rejected_alerts",
    "analyst_capacity", "unused_capacity", "capacity_status",
]
MONITOR_COLUMNS = [
    "monitoring_window", "start_row", "end_row", "start_step", "end_step", *SUMMARY_COLUMNS,
]
TABLES = {
    "seq_runs": ["run_id", "limit", "imported_utc", "parameters_json", "source_endpoint"],
    "seq_policy_summary": ["run_id", "limit", "policy", *SUMMARY_COLUMNS],
    "seq_decisions": ["run_id", "limit", "policy", *DECISION_COLUMNS],
    "seq_transaction_types": ["run_id", "limit", "policy", *TYPE_COLUMNS],
    "seq_operational_steps": ["run_id", "limit", "policy", *STEP_COLUMNS],
    "seq_monitoring_windows": ["run_id", "limit", "policy", *MONITOR_COLUMNS],
}


def _frame(records: list[dict], required: list[str], context: str) -> pd.DataFrame:
    if not isinstance(records, list):
        raise ValueError(f"{context} must be a list of records.")
    if not records:
        return pd.DataFrame(columns=required)
    frame = pd.DataFrame(records)
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"{context} is missing fields: {sorted(missing)}")
    return frame


def validate_payload(payload: dict, requested_limit: int) -> None:
    """Reconcile original records; do not infer missing simulation results."""
    if not isinstance(payload, dict) or not isinstance(payload.get("parameters"), dict):
        raise ValueError("Expected a sequential response with API parameters.")
    parameters = payload["parameters"]
    if int(parameters.get("limit", -1)) != requested_limit:
        raise ValueError("API metadata does not match the requested transaction limit.")
    capacity = int(parameters["alert_budget_per_step"])
    if capacity < 1:
        raise ValueError("API analyst capacity must be positive.")
    fraud_totals = []
    for policy in ("static", "adaptive"):
        result = payload.get(f"{policy}_sequential")
        if not isinstance(result, dict) or not isinstance(result.get("summary"), dict):
            raise ValueError(f"Missing {policy} sequential result.")
        summary = result["summary"]
        missing = set(SUMMARY_COLUMNS) - set(summary)
        if missing:
            raise ValueError(f"{policy} summary is missing fields: {sorted(missing)}")
        if any(not pd.notna(summary[key]) or not float('-inf') < float(summary[key]) < float('inf')
               or float(summary[key]) < 0 for key in SUMMARY_COLUMNS):
            raise ValueError(f"{policy} summary contains invalid numeric values.")
        if any(float(summary[key]) != int(summary[key]) for key in SUMMARY_COLUMNS[:11]):
            raise ValueError(f"{policy} summary counts must be integers.")
        if int(summary["total_transactions"]) != requested_limit:
            raise ValueError(f"{policy}: API returned a truncated run.")
        if summary["total_frauds"] > requested_limit:
            raise ValueError(f"{policy}: fraud count exceeds evaluated transactions.")
        fraud_totals.append(int(summary["total_frauds"]))
        decisions = _frame(result.get("decision_rows"), DECISION_COLUMNS, f"{policy} decisions")
        if len(decisions) != int(summary["policy_candidate_alerts"]):
            raise ValueError(f"{policy}: incomplete candidate audit.")
        if decisions["transaction_id"].isna().any() or decisions["transaction_id"].duplicated().any():
            raise ValueError(f"{policy}: missing or duplicate candidate transaction IDs.")
        flags = ["selected_alert", "suppression_applied", "capacity_rejected"]
        for column in [*flags, "isFraud", "policy_alert_candidate"]:
            if not decisions[column].isin([0, 1, False, True]).all():
                raise ValueError(f"{policy}: invalid {column} flags.")
        if not decisions.empty:
            if not decisions["policy_alert_candidate"].eq(1).all():
                raise ValueError(f"{policy}: decision rows must be alert candidates.")
            if not decisions[flags].astype(int).sum(axis=1).eq(1).all():
                raise ValueError(f"{policy}: candidate outcomes overlap or are missing.")
            for flag, outcome in zip(flags, ["alert", "suppressed", "capacity_rejected"]):
                if not decisions[flag].eq(1).equals(decisions["sequential_decision"].eq(outcome)):
                    raise ValueError(f"{policy}: outcome labels disagree with audit flags.")
        selected = decisions["selected_alert"].eq(1)
        checks = {
            "selected_alerts": int(selected.sum()),
            "suppressed_alerts": int(decisions["suppression_applied"].eq(1).sum()),
            "capacity_rejected_alerts": int(decisions["capacity_rejected"].eq(1).sum()),
            "frauds_detected": int((selected & decisions["isFraud"].eq(1)).sum()),
            "false_positives": int((selected & decisions["isFraud"].eq(0)).sum()),
        }
        for key, value in checks.items():
            if value != int(summary[key]):
                raise ValueError(f"{policy}: {key} disagrees with the audit.")
        if int(summary["frauds_detected"]) + int(summary["frauds_missed"]) != fraud_totals[-1]:
            raise ValueError(f"{policy}: detected/missed frauds do not reconcile.")
        precision = checks["frauds_detected"] / checks["selected_alerts"] if checks["selected_alerts"] else 0.0
        recall = checks["frauds_detected"] / fraud_totals[-1] if fraud_totals[-1] else 0.0
        if abs(float(summary["precision"]) - precision) > 1e-6 or abs(float(summary["recall"]) - recall) > 1e-6:
            raise ValueError(f"{policy}: precision/recall disagree with the counts.")
        if abs(float(summary["total_operational_cost"]) - float(summary["investigation_cost_total"])
               - float(summary["missed_fraud_cost"])) > .02:
            raise ValueError(f"{policy}: cost components do not reconcile.")
        if abs(float(summary["investigation_cost_total"]) - checks["selected_alerts"]
               * float(parameters["investigation_cost"])) > .02:
            raise ValueError(f"{policy}: investigation cost disagrees with API assumptions.")
        types = _frame(result.get("transaction_type_summary"), TYPE_COLUMNS, f"{policy} types")
        steps = _frame(result.get("operational_steps"), STEP_COLUMNS, f"{policy} steps")
        monitoring = _frame(result.get("monitoring_windows"), MONITOR_COLUMNS, f"{policy} monitoring")
        if types["type"].duplicated().any() or steps["step"].duplicated().any():
            raise ValueError(f"{policy}: duplicate transaction types or operational steps.")
        if (steps["investigated_alerts"] > capacity).any():
            raise ValueError(f"{policy}: analyst capacity exceeded.")
        for frame, mappings in [
            (types, {"transactions": "total_transactions", "actual_frauds": "total_frauds",
                     "candidate_alerts": "policy_candidate_alerts", "investigated_alerts": "selected_alerts"}),
            (steps, {"transactions_processed": "total_transactions", "frauds_present": "total_frauds",
                     "frauds_detected": "frauds_detected", "candidate_alerts": "policy_candidate_alerts",
                     "investigated_alerts": "selected_alerts", "suppressed_alerts": "suppressed_alerts",
                     "capacity_rejected_alerts": "capacity_rejected_alerts"}),
            (monitoring, {key: key for key in ["total_transactions", "total_frauds", "selected_alerts",
                                             "frauds_detected", "policy_candidate_alerts"]}),
        ]:
            for column, key in mappings.items():
                if int(frame[column].sum()) != int(summary[key]):
                    raise ValueError(f"{policy}: {column} aggregates disagree with the summary.")
    if fraud_totals[0] != fraud_totals[1]:
        raise ValueError("Static and Adaptive ground-truth totals disagree.")


def payload_to_tables(payload: dict, requested_limit: int, source_url: str) -> dict[str, pd.DataFrame]:
    validate_payload(payload, requested_limit)
    run_id = uuid.uuid4().hex
    tables = {name: pd.DataFrame(columns=columns) for name, columns in TABLES.items()}
    tables["seq_runs"] = pd.DataFrame([{
        "run_id": run_id, "limit": requested_limit,
        "imported_utc": datetime.now(timezone.utc).isoformat(),
        "parameters_json": json.dumps(payload["parameters"], sort_keys=True),
        "source_endpoint": source_url.rstrip("/") + ENDPOINT,
    }])
    pieces = {name: [] for name in TABLES if name != "seq_runs"}
    for policy in ("static", "adaptive"):
        result = payload[f"{policy}_sequential"]
        records = {
            "seq_policy_summary": [result["summary"]],
            "seq_decisions": result["decision_rows"],
            "seq_transaction_types": result["transaction_type_summary"],
            "seq_operational_steps": result["operational_steps"],
            "seq_monitoring_windows": result["monitoring_windows"],
        }
        for name, rows in records.items():
            frame = pd.DataFrame(rows, columns=TABLES[name][3:])
            frame.insert(0, "policy", policy)
            frame.insert(0, "limit", requested_limit)
            frame.insert(0, "run_id", run_id)
            pieces[name].append(frame)
    for name, frames in pieces.items():
        tables[name] = pd.concat(frames, ignore_index=True)
    return tables


def save_to_sqlite(tables: dict[str, pd.DataFrame], database_path: Path = DATABASE_PATH) -> None:
    """Preserve unrelated tables and replace only after staging succeeds."""
    if set(tables) != set(TABLES):
        raise ValueError("All six sequential reporting tables are required.")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staged_name = tempfile.mkstemp(prefix="seq_import_", suffix=".db", dir=database_path.parent)
    os.close(descriptor)
    staged = Path(staged_name)
    try:
        with closing(sqlite3.connect(staged)) as target:
            if database_path.exists():
                with closing(sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                    source.backup(target)
            for name, frame in tables.items():
                frame.to_sql(name, target, if_exists="replace", index=False)
            target.execute("CREATE UNIQUE INDEX IF NOT EXISTS seq_run_identity ON seq_runs(run_id)")
            target.execute("CREATE UNIQUE INDEX IF NOT EXISTS seq_summary_identity ON seq_policy_summary(run_id, policy)")
            target.execute("CREATE UNIQUE INDEX IF NOT EXISTS seq_decision_identity ON seq_decisions(run_id, policy, transaction_id)")
            target.execute("CREATE INDEX IF NOT EXISTS seq_decisions_step ON seq_decisions(run_id, policy, step)")
            target.commit()
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity check failed.")
        os.replace(staged, database_path)
    finally:
        staged.unlink(missing_ok=True)


def get_json(api_url: str, params: dict) -> dict:
    url = api_url.rstrip("/") + ENDPOINT + "?" + urlencode(params)
    with urlopen(url, timeout=240) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("THESIS_API_BASE_URL", "http://127.0.0.1:8002"))
    parser.add_argument("--limits", nargs="+", type=int, default=DEFAULT_LIMITS)
    args = parser.parse_args()
    parsed = urlparse(args.api_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}
            or not parsed.port or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        parser.error("Use a local API address, such as http://127.0.0.1:8003")
    if any(limit < 1 or limit > 100000 for limit in args.limits):
        parser.error("Transaction limits must be between 1 and 100000.")
    collected = {name: [] for name in TABLES}
    for limit in sorted(set(args.limits)):
        print(f"Importing {limit:,} transactions from {ENDPOINT}…", flush=True)
        payload = get_json(args.api_url, {**BASE_PARAMS, "limit": limit})
        for name, frame in payload_to_tables(payload, limit, args.api_url).items():
            collected[name].append(frame)
    tables = {name: pd.concat(frames, ignore_index=True) for name, frames in collected.items()}
    save_to_sqlite(tables)
    print(f"Validated import complete: {DATABASE_PATH}")
    for name, frame in tables.items():
        print(f"  {name}: {len(frame):,} rows")


if __name__ == "__main__":
    main()
