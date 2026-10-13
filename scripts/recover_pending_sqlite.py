"""Recover an already completed sequential export after Windows WinError 32.

No Main API required; validates SQLite contents and then replaces the old database.
Run this script only with Streamlit / DB Browser / SQLite viewers closed.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "processed" / "fraud_investigation.db"
PENDING = DB.with_suffix(".pending.db")
REQUIRED = {
    "seq_runs", "seq_policy_summary", "seq_decisions",
    "seq_operational_steps", "seq_monitoring_windows", "seq_transaction_types",
}


def verify(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(
            f"Cannot find completed export: {path}\n"
            "If it does not exist, run the corrected importer instead."
        )
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as con:
        status = con.execute("PRAGMA quick_check").fetchone()[0]
        if status != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {status}")
        names = {
            row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = REQUIRED - names
        if missing:
            raise RuntimeError(f"Pending export is incomplete. Missing: {sorted(missing)}")
        expected = {
            "seq_runs": 3,
            "seq_policy_summary": 6,
        }
        for name in sorted(REQUIRED):
            total = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            print(f"{name}: {total:,} rows")
            if total == 0 or (name in expected and total != expected[name]):
                raise RuntimeError(f"Unexpected row count in {name}: {total}")
        results = con.execute("""
            SELECT s.run_id, s.policy, s.selected_alerts, s.frauds_detected,
              SUM(CASE WHEN d.selected_alert = 1 THEN 1 ELSE 0 END),
              SUM(CASE WHEN d.selected_alert = 1 AND d.isFraud = 1 THEN 1 ELSE 0 END)
            FROM seq_policy_summary s
            LEFT JOIN seq_decisions d
                ON d.run_id = s.run_id AND d.policy = s.policy
            GROUP BY s.run_id, s.policy
        """).fetchall()
        if len(results) != 6:
            raise RuntimeError("Expected six Static/Adaptive summary rows")
        for run_id, policy, selected, caught, calculated_selected, calculated_caught in results:
            if int(selected) != int(calculated_selected or 0) or int(caught) != int(calculated_caught or 0):
                raise RuntimeError(f"Audit totals differ for {run_id} / {policy}")
    print("Checks passed: all six tables and six policy totals are consistent.")


def main() -> None:
    verify(PENDING)
    if DB.exists():
        backup = DB.with_name(
            f"fraud_investigation.old_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        )
        try:
            shutil.copy2(DB, backup)
        except OSError as exc:
            raise RuntimeError(
                f"Could not back up old database. The pending export is unchanged: {exc}"
            ) from exc
        print(f"Old database backup: {backup}")
    try:
        PENDING.replace(DB)
    except PermissionError as exc:
        raise RuntimeError(
            "Windows still has the database open. Close all Streamlit CMDs "
            "(Ctrl+C), DB Browser, and any VS Code SQLite viewer; "
            "then run this recovery command again. The pending export is safe."
        ) from exc
    print(f"Recovery complete! Active SQLite database: {DB}")
    print("Now launch: python -m streamlit run dashboards/thesis_decision_dashboard.py")


if __name__ == "__main__":
    main()
