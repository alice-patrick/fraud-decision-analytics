"""Reporting regression checks using frozen outputs from the Main sequential API."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dashboards/thesis_decision_dashboard.py"
spec = importlib.util.spec_from_file_location("analytics_importer", ROOT / "scripts/import_from_thesis_api.py")
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


def payload(name="sequential_payload"):
    return json.loads((ROOT / f"tests/fixtures/{name}.json").read_text(encoding="utf-8"))


def reporting_functions():
    # Load the actual SQL and pure validation helpers without launching Streamlit.
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    names = {"run_validation", "amount", "count", "pct", "formatted_results"}
    nodes = [node for node in tree.body if
             (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name)
              and t.id.startswith("SQL_") for t in node.targets)) or
             (isinstance(node, ast.FunctionDef) and node.name in names)]
    namespace = {"pd": pd}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP), "exec"), namespace)
    return namespace


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / "report.db"
        self.tables = importer.payload_to_tables(payload(), 8, "http://127.0.0.1:8003")
        importer.save_to_sqlite(self.tables, self.database)
        self.run_id = self.tables["seq_runs"].iloc[0]["run_id"]
        self.reporting = reporting_functions()

    def query(self, name, policy=None, run_id=None):
        with sqlite3.connect(self.database) as con:
            return pd.read_sql_query(self.reporting[name], con,
                params={"run_id": self.run_id if run_id is None else run_id, "policy": policy})

    def test_api_summaries_reconcile_with_sql_audit(self):
        summary = self.query("SQL_OVERVIEW")
        steps = pd.concat([self.query("SQL_STEP_WORKLOAD", p) for p in ["static", "adaptive"]])
        self.assertEqual(self.reporting["run_validation"](summary, steps, 2), [])
        self.assertEqual(summary.set_index("policy")["selected_alerts"].to_dict(), {"static": 3, "adaptive": 4})

    def test_policy_queries_return_different_actual_accepted_rows(self):
        static = self.query("SQL_AUDIT", "static")
        adaptive = self.query("SQL_AUDIT", "adaptive")
        self.assertEqual(static.loc[static.selected_alert.eq(1), "transaction_id"].tolist(), [1, 2, 5])
        self.assertEqual(adaptive.loc[adaptive.selected_alert.eq(1), "transaction_id"].tolist(), [1, 2, 5, 6])

    def test_zero_candidate_steps_remain_in_monitoring(self):
        steps = self.query("SQL_STEP_WORKLOAD", "static")
        self.assertEqual(steps.step.tolist(), [1, 2, 3])
        self.assertEqual(steps.candidates.tolist(), [3, 2, 0])
        self.assertEqual(steps.cumulative_investigations.tolist(), [2, 3, 3])

    def test_non_alert_transaction_types_are_included(self):
        types = self.query("SQL_TYPE_ANALYSIS", "adaptive").set_index("type")
        self.assertEqual(types.loc["PAYMENT", "transactions"], 2)
        self.assertEqual(types.loc["PAYMENT", "candidate_alerts"], 0)

    def test_score_rank_matches_main_tie_breaking(self):
        rows = self.query("SQL_AUDIT", "adaptive")
        self.assertEqual(rows.candidate_priority_rank.tolist(), rows.score_rank_in_step.tolist())

    def test_filters_are_bound_parameters(self):
        for name in ["SQL_OVERVIEW", "SQL_AUDIT", "SQL_TYPE_ANALYSIS", "SQL_STEP_WORKLOAD", "SQL_MONITORING"]:
            self.assertTrue(self.query(name, "adaptive", "' OR 1=1 --").empty)

    def test_no_candidates_are_valid_and_keep_the_schema(self):
        tables = importer.payload_to_tables(payload("zero_candidate_payload"), 8, "http://localhost:8003")
        importer.save_to_sqlite(tables, self.database)
        self.run_id = tables["seq_runs"].iloc[0]["run_id"]
        overview = self.query("SQL_OVERVIEW")
        steps = pd.concat([self.query("SQL_STEP_WORKLOAD", p) for p in ["static", "adaptive"]])
        self.assertTrue(self.query("SQL_AUDIT", "adaptive").empty)
        self.assertEqual(overview.selected_alerts.tolist(), [0, 0])
        self.assertEqual(self.reporting["run_validation"](overview, steps, 2), [])

    def test_incomplete_audit_is_rejected(self):
        wrong = payload()
        wrong["adaptive_sequential"]["decision_rows"].pop()
        with self.assertRaisesRegex(ValueError, "incomplete candidate"):
            importer.validate_payload(wrong, 8)

    def test_overlapping_outcomes_are_rejected(self):
        wrong = payload()
        wrong["adaptive_sequential"]["decision_rows"][0]["capacity_rejected"] = True
        with self.assertRaisesRegex(ValueError, "overlap"):
            importer.validate_payload(wrong, 8)

    def test_cost_and_truncation_errors_are_rejected(self):
        for field, value in [("total_operational_cost", 0), ("total_transactions", 7)]:
            wrong = payload()
            wrong["static_sequential"]["summary"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                importer.validate_payload(wrong, 8)

    def test_dashboard_hides_inconsistent_summary(self):
        overview = self.query("SQL_OVERVIEW")
        overview.loc[overview.policy.eq("adaptive"), "frauds_detected"] += 1
        steps = pd.concat([self.query("SQL_STEP_WORKLOAD", p) for p in ["static", "adaptive"]])
        self.assertTrue(self.reporting["run_validation"](overview, steps, 2))

    def test_failed_staging_preserves_original_database(self):
        digest = hashlib.sha256(self.database.read_bytes()).hexdigest()
        wrong = copy.deepcopy(self.tables)
        wrong["seq_policy_summary"] = pd.concat([wrong["seq_policy_summary"]]*2)
        with self.assertRaises(sqlite3.IntegrityError):
            importer.save_to_sqlite(wrong, self.database)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), digest)

    def test_unrelated_legacy_tables_are_preserved(self):
        with sqlite3.connect(self.database) as con:
            con.execute("CREATE TABLE legacy_report (value INTEGER)")
            con.execute("INSERT INTO legacy_report VALUES (42)")
        importer.save_to_sqlite(self.tables, self.database)
        with sqlite3.connect(self.database) as con:
            self.assertEqual(con.execute("SELECT value FROM legacy_report").fetchone()[0], 42)


HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


@unittest.skipUnless(HAS_STREAMLIT, "Install requirements.txt to run Streamlit AppTest checks")
class DashboardTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.AppTest = AppTest
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / "report.db"
        tables = importer.payload_to_tables(payload(), 8, "http://127.0.0.1:8003")
        importer.save_to_sqlite(tables, self.database)
        env = patch.dict(os.environ, {"ANALYTICS_DB_PATH": str(self.database)})
        env.start()
        self.addCleanup(env.stop)

    def test_sidebar_policy_controls_all_reports_and_keeps_comparison(self):
        app = self.AppTest.from_file(str(APP), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.sidebar.selectbox(key="decision_policy").value, "Adaptive")
        self.assertEqual(len(app.radio), 0)
        self.assertEqual(app.tabs[0].metric[2].value, "4")
        self.assertEqual(len(app.tabs[2].dataframe[0].value), 4)
        self.assertEqual(app.tabs[3].metric[0].value, "6")
        comparison = app.tabs[1].dataframe[0].value.copy()
        app.sidebar.selectbox(key="decision_policy").set_value("Static").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.tabs[0].metric[2].label, "Static investigated")
        self.assertEqual(app.tabs[0].metric[2].value, "3")
        self.assertEqual(len(app.tabs[2].dataframe[0].value), 3)
        self.assertEqual(app.tabs[3].metric[0].value, "5")
        self.assertIn("Static", app.tabs[4].subheader[0].value)
        pd.testing.assert_frame_equal(app.tabs[1].dataframe[0].value, comparison)
        app.sidebar.selectbox(key="decision_policy").set_value("Adaptive").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.tabs[0].metric[2].value, "4")

    def test_empty_policy_renders_without_errors(self):
        tables = importer.payload_to_tables(payload("zero_candidate_payload"), 8, "http://localhost:8003")
        importer.save_to_sqlite(tables, self.database)
        app = self.AppTest.from_file(str(APP), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.tabs[0].metric[2].value, "0")
        self.assertTrue(app.tabs[2].dataframe[0].value.empty)

    def test_missing_database_shows_import_without_creating_database(self):
        missing = self.database.parent / "not_imported.db"
        with patch.dict(os.environ, {"ANALYTICS_DB_PATH": str(missing)}):
            app = self.AppTest.from_file(str(APP)).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.warning)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
