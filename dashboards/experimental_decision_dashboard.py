"""SQL reporting over imported Main Framework /simulation/sequential results.

Run: python -m streamlit run dashboards/thesis_decision_dashboard.py
The sidebar policy controls every single-policy report; comparison always shows both.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from html import escape
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("ANALYTICS_DB_PATH", str(ROOT / "data" / "processed" / "fraud_investigation.db")))
IMPORTER = ROOT / "scripts" / "import_from_thesis_api.py"
REQUIRED_TABLES = {
    "seq_runs", "seq_policy_summary", "seq_decisions",
    "seq_transaction_types", "seq_operational_steps", "seq_monitoring_windows",
}

SQL_OVERVIEW = """
WITH audit AS (
    SELECT run_id, policy, COUNT(*) AS candidate_alerts_audit,
        SUM(CASE WHEN selected_alert = 1 THEN 1 ELSE 0 END) AS investigated_audit,
        SUM(CASE WHEN selected_alert = 1 AND isFraud = 1 THEN 1 ELSE 0 END)
            AS frauds_detected_audit,
        SUM(CASE WHEN suppression_applied = 1 THEN 1 ELSE 0 END) AS suppressed,
        SUM(CASE WHEN capacity_rejected = 1 THEN 1 ELSE 0 END) AS capacity_rejected,
        SUM(CASE WHEN selected_alert + suppression_applied + capacity_rejected != 1
                 THEN 1 ELSE 0 END) AS invalid_outcomes
    FROM seq_decisions
    WHERE run_id = :run_id
    GROUP BY run_id, policy
)
SELECT s.*, r."limit" AS run_limit, r.parameters_json, r.imported_utc,
    COALESCE(a.candidate_alerts_audit, 0) AS candidate_alerts_audit,
    COALESCE(a.investigated_audit, 0) AS investigated_audit,
    COALESCE(a.frauds_detected_audit, 0) AS frauds_detected_audit,
    COALESCE(a.suppressed, 0) AS suppressed,
    COALESCE(a.capacity_rejected, 0) AS capacity_rejected,
    COALESCE(a.invalid_outcomes, 0) AS invalid_outcomes
FROM seq_policy_summary AS s
JOIN seq_runs AS r ON r.run_id = s.run_id
LEFT JOIN audit AS a ON a.run_id = s.run_id AND a.policy = s.policy
WHERE s.run_id = :run_id
ORDER BY CASE s.policy WHEN 'static' THEN 0 ELSE 1 END
"""

SQL_TYPE_ANALYSIS = """
WITH audit_by_type AS (
    SELECT run_id, policy, type,
        SUM(CASE WHEN selected_alert = 1 AND isFraud = 1 THEN 1 ELSE 0 END)
            AS detected_frauds,
        SUM(CASE WHEN suppression_applied = 1 THEN 1 ELSE 0 END) AS suppressed,
        SUM(CASE WHEN capacity_rejected = 1 THEN 1 ELSE 0 END) AS capacity_rejected
    FROM seq_decisions
    WHERE run_id = :run_id
    GROUP BY run_id, policy, type
)
SELECT t.policy, t.type, t.transactions, t.actual_frauds,
    t.candidate_alerts, t.investigated_alerts,
    t.average_fraud_score, t.actual_fraud_rate,
    COALESCE(a.detected_frauds, 0) AS detected_frauds,
    COALESCE(a.suppressed, 0) AS suppressed,
    COALESCE(a.capacity_rejected, 0) AS capacity_rejected
FROM seq_transaction_types AS t
LEFT JOIN audit_by_type AS a
    ON a.run_id = t.run_id AND a.policy = t.policy AND a.type = t.type
WHERE t.run_id = :run_id AND t.policy = :policy
ORDER BY t.transactions DESC, t.type
"""

SQL_STEP_WORKLOAD = """
WITH step_totals AS (
    SELECT run_id, policy, step, COUNT(*) AS candidates,
        SUM(CASE WHEN selected_alert = 1 THEN 1 ELSE 0 END) AS investigated,
        SUM(CASE WHEN suppression_applied = 1 THEN 1 ELSE 0 END) AS suppressed,
        SUM(CASE WHEN capacity_rejected = 1 THEN 1 ELSE 0 END) AS capacity_rejected
    FROM seq_decisions
    WHERE run_id = :run_id AND policy = :policy
    GROUP BY run_id, policy, step
), all_steps AS (
    SELECT o.policy, o.step, o.transactions_processed, o.analyst_capacity,
        o.eligible_alerts, o.unused_capacity, o.frauds_present, o.frauds_detected,
        COALESCE(a.candidates, 0) AS candidates,
        COALESCE(a.investigated, 0) AS investigated,
        COALESCE(a.suppressed, 0) AS suppressed,
        COALESCE(a.capacity_rejected, 0) AS capacity_rejected
    FROM seq_operational_steps AS o
    LEFT JOIN step_totals AS a
        ON a.run_id = o.run_id AND a.policy = o.policy AND a.step = o.step
    WHERE o.run_id = :run_id AND o.policy = :policy
)
SELECT *, ROW_NUMBER() OVER (ORDER BY investigated DESC, step ASC) AS workload_rank,
    SUM(investigated) OVER (
        ORDER BY step ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_investigations
FROM all_steps
ORDER BY step
"""

SQL_AUDIT = """
WITH ranked_candidates AS (
    SELECT transaction_id, step, type, amount, fraud_score, rank_score,
        selected_alert, suppression_applied, capacity_rejected,
        sequential_decision, isFraud, candidate_priority_rank, accepted_priority_rank,
        capacity_used_before_decision, capacity_remaining_after_decision,
        ROW_NUMBER() OVER (
            PARTITION BY step
            ORDER BY rank_score DESC, fraud_score DESC, transaction_id ASC
        ) AS score_rank_in_step
    FROM seq_decisions
    WHERE run_id = :run_id AND policy = :policy
)
SELECT * FROM ranked_candidates
ORDER BY step, score_rank_in_step
"""

SQL_MONITORING = """
SELECT * FROM seq_monitoring_windows
WHERE run_id = :run_id AND policy = :policy
ORDER BY monitoring_window
"""

st.set_page_config(
    page_title="Fraud Decision Analytics | SQL", page_icon="📊",
    layout="wide", initial_sidebar_state="expanded",
)
UI_CSS = '.block-container{max-width:1480px;padding-top:1.4rem;padding-bottom:2.5rem}\n#MainMenu{visibility:hidden}\n.dashboard-header{padding:1.35rem 1.5rem;border:1px solid #29394d;border-left:4px solid #fb7185;border-radius:17px;background:linear-gradient(120deg,#192337,#111822 70%);margin-bottom:1rem}\n.dashboard-header h1{font-size:1.85rem;letter-spacing:-.055rem;color:#f1f5fb;margin:0;font-weight:740}\n.dashboard-header p{margin:.5rem 0 0;color:#a4b5cc;font-size:.9rem}\n.eyebrow{font-size:.67rem;letter-spacing:.14rem;color:#fb8da0;font-weight:750;text-transform:uppercase;margin-bottom:.4rem}\n.analytics-grid{display:grid;grid-template-columns:repeat(var(--card-count,4),minmax(0,1fr));gap:13px;margin:.6rem 0 1.3rem}\n.analytics-kpi{padding:17px 17px 14px;background:linear-gradient(135deg,#182231,#121a25);border:1px solid #2a3b50;border-radius:14px;min-height:124px;border-top:3px solid #7aafff;box-shadow:0 7px 20px #00000014}\n.analytics-kpi.green{border-top-color:#39cba3}.analytics-kpi.rose{border-top-color:#fb7185}.analytics-kpi.amber{border-top-color:#f3ba62}.analytics-kpi.violet{border-top-color:#b39aff}\n.kpi-label{font-size:.78rem;color:#b2c1d6;line-height:1.4;font-weight:650}\n.kpi-value{font-size:1.9rem;line-height:1.2;font-weight:750;letter-spacing:-.055rem;color:#f5f8ff;margin:.42rem 0;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}\n.analytics-grid[style*="--card-count:5"] .kpi-value{font-size:1.25rem;letter-spacing:-.02rem}\n.kpi-note{font-size:.72rem;color:#879db9;line-height:1.45;margin-top:.4rem}\n.kpi-delta{display:inline-block;font-size:.71rem;padding:3px 7px;border-radius:6px;background:#233147;color:#bbcadf;margin-top:.25rem}\n.kpi-delta.positive{background:#12382e;color:#76e1be}.kpi-delta.negative{background:#412633;color:#ffafbc}\n.comparison-panel{border:1px solid #2a3b50;background:#131c28;border-radius:14px;overflow:hidden;margin-top:.8rem}\n.comparison-table{width:100%;border-collapse:collapse;font-size:.84rem}\n.comparison-table th{text-align:right;padding:17px 13px;background:#192638;color:#b9cbe3;font-size:.76rem;border-bottom:1px solid #2c3e55;white-space:nowrap}\n.comparison-table th:first-child{text-align:left}.comparison-table td{padding:17px 13px;border-bottom:1px solid #253347;text-align:right;font-variant-numeric:tabular-nums}\n.comparison-table td:first-child{text-align:left;color:#d9e4f3;font-weight:650}\n.static-number{color:#95bdff;font-weight:750}.adaptive-number{color:#67dfbc;font-weight:750}.change-number{color:#b3bfd1}\n.selected-chip{display:block;font-size:.58rem;color:#a8b8ce;font-weight:400;margin-top:3px}\n.panel-footnote{font-size:.7rem;color:#8ca2bf;padding:13px 15px;line-height:1.5}\n.insight-panel,.explain-panel,.decision-panel{background:linear-gradient(120deg,#172a34,#141c29);border:1px solid #2e4a59;border-left:3px solid #39cba3;border-radius:13px;padding:17px 20px;margin:.7rem 0 1rem;color:#c8d8e9;line-height:1.65;font-size:.85rem}\n.explain-panel{border-left-color:#7aafff;background:linear-gradient(120deg,#19283e,#131c2a)}\n.decision-panel{border-left-color:#b39aff;background:linear-gradient(120deg,#251e37,#181c2a)}\n.insight-panel strong,.explain-panel strong,.decision-panel strong{display:block;color:#f3f7ff;margin-bottom:5px;font-size:.89rem}\n.policy-key{display:flex;gap:18px;align-items:center;color:#b6c7dc;font-size:.73rem;margin:.8rem 0 .3rem}\n.policy-key span:before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;background:#7aafff}.policy-key span:last-child:before{background:#39cba3}\n[data-testid="stMetric"]{border:1px solid #2a3b50;border-top:2px solid #7aafff;background:#141c28;border-radius:12px;padding:13px 15px;min-height:100px}\n[data-testid="stMetricValue"]{font-size:1.55rem}\n[data-testid="stDataFrame"]{border:1px solid #2a3b50;border-radius:12px}\nsection[data-testid="stSidebar"]{border-right:1px solid #29394d}\nbutton[data-baseweb="tab"]{font-weight:650;padding:.75rem .5rem;font-size:.86rem}\nbutton[data-baseweb="tab"][aria-selected="true"]{color:#fb7185!important}\n[data-testid="stTabs"] [data-baseweb="tab-highlight"]{background-color:#fb7185}\n[data-testid="stAlert"]{border-radius:12px}\n@media(max-width:1100px){.analytics-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.kpi-value{font-size:1.6rem}.comparison-table th,.comparison-table td{padding:14px 9px;font-size:.76rem}}\n@media(max-width:650px){.analytics-grid{grid-template-columns:1fr}.dashboard-header h1{font-size:1.35rem}.comparison-table th,.comparison-table td{padding:12px 6px;font-size:.68rem}}\n'
st.markdown("<style>"+UI_CSS+"</style>", unsafe_allow_html=True)


def amount(value: object) -> str:
    return f"€{float(value):,.2f}"


def count(value: object) -> str:
    return f"{int(value):,}"


def pct(value: object) -> str:
    return f"{float(value):.1%}"


def read_sql(query: str, run_id: str, policy: str | None = None) -> pd.DataFrame:
    parameters = {"run_id": run_id, "policy": policy}
    with closing(sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        return pd.read_sql_query(query, con, params=parameters)


@st.cache_data(show_spinner=False)
def query_cached(query: str, run_id: str, policy: str | None, db_version: int):
    # Include the file version so reruns refresh data after import.
    return read_sql(query, run_id, policy)


@st.cache_data(show_spinner=False)
def describe_database(db_version: int):
    with closing(sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        names = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        missing = REQUIRED_TABLES - names
        if missing:
            return missing, pd.DataFrame()
        runs = pd.read_sql_query(
            'SELECT run_id, "limit", imported_utc, parameters_json '
            'FROM seq_runs ORDER BY "limit", imported_utc', con,
        )
    return set(), runs


def launch_import():
    st.info("Keep the Main Framework API running in a separate terminal, then import its "
            "sequential results here.")
    api_url = st.text_input("Main API address", value=os.getenv(
        "THESIS_API_BASE_URL", "http://127.0.0.1:8002"),
        placeholder="http://127.0.0.1:8003")
    if not st.button("Import sequential results", type="primary"):
        return
    try:
        parsed = urlparse(api_url.strip())
        valid_url = (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
                     and parsed.port and not parsed.username and not parsed.password
                     and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)
    except ValueError:
        valid_url = False
    if not valid_url:
        st.error("Enter a local API address such as http://127.0.0.1:8003")
        return
    if not IMPORTER.exists() or "/simulation/sequential" not in IMPORTER.read_text(encoding="utf-8-sig"):
        st.error("Install the matching scripts/import_from_thesis_api.py sequential importer.")
        return
    environment = dict(os.environ)
    environment["THESIS_API_BASE_URL"] = api_url.strip().rstrip("/")
    environment["PYTHONIOENCODING"] = "utf-8"
    with st.spinner("Importing and validating sequential results (1k / 3k / 10k)…"):
        try:
            result = subprocess.run(
                [sys.executable, str(IMPORTER)], cwd=str(ROOT), env=environment,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=1200, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            st.error(f"Import failed to start or timed out: {exc}")
            return
    if result.returncode:
        st.error("Import failed. The previous database is preserved until a complete import succeeds.")
        st.code((result.stdout + "\n" + result.stderr)[-8000:], language="text")
        return
    st.success("Import completed.")
    st.cache_data.clear()
    st.rerun()


def run_validation(summary: pd.DataFrame, steps: pd.DataFrame, capacity: int) -> list[str]:
    """Reconcile SQL reports against the original sequential API summaries."""
    issues: list[str] = []
    if len(summary) != 2 or set(summary["policy"]) != {"static", "adaptive"}:
        return ["Exactly one Static and one Adaptive Sequential summary are required."]
    if capacity < 1:
        issues.append("The imported analyst capacity must be positive.")
    for row in summary.itertuples(index=False):
        for source, audit, name in [
            (row.selected_alerts, row.investigated_audit, "investigated count"),
            (row.frauds_detected, row.frauds_detected_audit, "detected fraud count"),
            (row.policy_candidate_alerts, row.candidate_alerts_audit, "candidate count"),
            (row.suppressed_alerts, row.suppressed, "suppressed count"),
            (row.capacity_rejected_alerts, row.capacity_rejected, "capacity-rejected count"),
        ]:
            if int(source) != int(audit):
                issues.append(f"{row.policy}: {name} disagrees with the audit.")
        if int(row.total_transactions) != int(row.run_limit):
            issues.append(f"{row.policy}: total transactions do not match the imported run size.")
        if int(row.frauds_detected) + int(row.frauds_missed) != int(row.total_frauds):
            issues.append(f"{row.policy}: detected and missed frauds do not reconcile.")
        if int(row.frauds_detected) + int(row.false_positives) != int(row.selected_alerts):
            issues.append(f"{row.policy}: investigated outcome counts do not reconcile.")
        if int(row.invalid_outcomes):
            issues.append(f"{row.policy}: candidates must have exactly one decision outcome.")
        precision = float(row.frauds_detected) / float(row.selected_alerts) if row.selected_alerts else 0.0
        recall = float(row.frauds_detected) / float(row.total_frauds) if row.total_frauds else 0.0
        if abs(float(row.precision) - precision) > 1e-6 or abs(float(row.recall) - recall) > 1e-6:
            issues.append(f"{row.policy}: precision or recall disagrees with the underlying counts.")
        if abs(float(row.total_operational_cost) - float(row.investigation_cost_total)
               - float(row.missed_fraud_cost)) > .02:
            issues.append(f"{row.policy}: the operational cost components do not reconcile.")
        policy_steps = steps.loc[steps["policy"].eq(row.policy)]
        if int(policy_steps["investigated"].sum()) != int(row.selected_alerts):
            issues.append(f"{row.policy}: operational steps disagree with investigated totals.")
        if int(policy_steps["candidates"].sum()) != int(row.policy_candidate_alerts):
            issues.append(f"{row.policy}: operational steps disagree with candidate totals.")
        if int(policy_steps["transactions_processed"].sum()) != int(row.total_transactions):
            issues.append(f"{row.policy}: operational steps do not cover all transactions.")
    if summary["total_frauds"].nunique() != 1:
        issues.append("Static and Adaptive have different underlying fraud totals.")
    if not steps.empty and (steps["investigated"] > capacity).any():
        issues.append("At least one step exceeds the declared analyst capacity.")
    return issues


def styled_plot(fig, height: int = 330):
    fig.update_layout(
        template="plotly_dark", height=height, margin=dict(l=10, r=10, t=46, b=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#dae4ee"), title_font=dict(size=17), legend_title_text="",
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="rgba(130,150,180,.13)", zeroline=False)
    st.plotly_chart(fig, width="stretch")


def metric_row(items: list[tuple[str, str]]):
    for column, (label, value) in zip(st.columns(len(items)), items):
        column.metric(label, value)


def pp_difference(value: float) -> str:
    if value == 0:
        return "0.0 pp"
    if abs(value) < .01:
        return ("+" if value > 0 else "−") + "<0.01 pp"
    return f"{value:+.2f} pp" if abs(value) < .1 else f"{value:+.1f} pp"


def overview_kpis(current: pd.Series, other: pd.Series, other_label: str) -> list[dict]:
    """Selected-policy ratios and signed differences; undefined ratios stay blank."""
    def rate_item(label, field, denominator, help_text, color="normal"):
        defined = float(current[denominator]) > 0
        comparable = defined and float(other[denominator]) > 0
        value = float(current[field]) if defined else None
        return {
            "label": label, "value": pct(value) if defined else "—",
            "delta": (f"{pp_difference((value-float(other[field]))*100)} vs {other_label}"
                      if comparable else None),
            "delta_color": color, "help": help_text,
        }

    items = [
        rate_item("Fraud coverage", "recall", "total_frauds",
                  "Detected frauds / all actual frauds (recall). Undefined when no actual frauds exist."),
        rate_item("Alert yield", "precision", "selected_alerts",
                  "Detected frauds / investigations (precision). Undefined when no alerts are investigated."),
    ]
    current_rate = float(current.selected_alerts) / float(current.total_transactions) if current.total_transactions else 0.0
    other_rate = float(other.selected_alerts) / float(other.total_transactions) if other.total_transactions else 0.0
    items.append({
        "label": "Investigation rate", "value": pct(current_rate),
        "delta": f"{pp_difference((current_rate-other_rate)*100)} vs {other_label}",
        "delta_color": "off", "help": "Investigations / evaluated transactions. Read workload together with fraud coverage.",
    })
    cost_change = float(current.total_operational_cost) - float(other.total_operational_cost)
    sign = "+" if cost_change >= 0 else "-"
    items.append({
        "label": "Estimated operational cost", "value": amount(current.total_operational_cost),
        "delta": f"{sign}{amount(abs(cost_change))} vs {other_label}",
        "delta_color": "inverse", "help": "Investigation cost + modeled missed-fraud loss. Lower cost is favorable under this run's assumptions.",
    })
    return items


def comparison_counts(summary: pd.DataFrame) -> pd.DataFrame:
    """One compact count comparison, consistently ordered Static then Adaptive."""
    policies = summary.set_index("policy")
    records = []
    for label, field in [
        ("Investigations", "selected_alerts"),
        ("Frauds detected", "frauds_detected"),
        ("Frauds missed", "frauds_missed"),
        ("Non-fraud reviews", "false_positives"),
    ]:
        static_value, adaptive_value = (int(policies.loc[p, field]) for p in ["static", "adaptive"])
        records.append({"Metric": label, "Static": static_value, "Adaptive": adaptive_value,
                        "Adaptive − Static": adaptive_value - static_value})
    return pd.DataFrame(records)


def cost_breakdown(summary: pd.DataFrame) -> pd.DataFrame:
    """Original cost components, rather than another copy of total-cost KPIs."""
    policies = summary.set_index("policy")
    return pd.DataFrame([
        {"Strategy": policy.capitalize(), "Component": label, "Cost": float(policies.loc[policy, field])}
        for policy in ["static", "adaptive"]
        for label, field in [("Investigations", "investigation_cost_total"),
                             ("Missed-fraud loss", "missed_fraud_cost")]
    ])


def comparison_reading(static: pd.Series, adaptive: pd.Series) -> str:
    """Describe observed coverage/cost trade-offs without assuming Adaptive wins."""
    fraud_change = int(adaptive.frauds_detected) - int(static.frauds_detected)
    review_change = int(adaptive.selected_alerts) - int(static.selected_alerts)
    cost_change = float(adaptive.total_operational_cost) - float(static.total_operational_cost)
    equal_cost = abs(cost_change) <= .01
    if fraud_change > 0:
        if cost_change < -.01:
            reading = "Adaptive increases fraud coverage and lowers modeled total cost in this run."
        elif equal_cost:
            reading = "Adaptive increases fraud coverage at effectively the same modeled total cost."
        else:
            reading = "Adaptive increases fraud coverage with a higher modeled total cost."
    elif fraud_change < 0:
        if cost_change > .01:
            reading = "Static increases fraud coverage and lowers modeled total cost in this run."
        elif equal_cost:
            reading = "Static increases fraud coverage at effectively the same modeled total cost."
        else:
            reading = "Static has higher fraud coverage; Adaptive has lower modeled total cost. This is a trade-off."
    elif equal_cost:
        reading = "Neither policy improves fraud coverage or modeled total cost in this run."
    else:
        cheaper = "Adaptive" if cost_change < 0 else "Static"
        reading = (f"Fraud coverage is equal. {cheaper} has lower modeled total cost; "
                   "review workload and the amounts of the specific frauds detected explain the difference.")

    # Marginal effort is informative only when extra coverage also requires extra reviews.
    if fraud_change and fraud_change * review_change > 0:
        higher_coverage = "Adaptive" if fraud_change > 0 else "Static"
        effort = abs(review_change / fraud_change)
        reading += (f" {higher_coverage} needs {effort:,.1f} additional reviews per additional fraud "
                    "detected, relative to the other policy.")
    if fraud_change and not equal_cost and fraud_change * cost_change > 0:
        higher_coverage = "Adaptive" if fraud_change > 0 else "Static"
        reading += (f" The incremental modeled cost for {higher_coverage} is "
                    f"{amount(abs(cost_change / fraud_change))} per additional fraud detected.")
    return reading


OUTCOME_LABELS = {"alert": "Investigate", "capacity_rejected": "Capacity reached", "suppressed": "Suppressed"}
OUTCOME_COLORS = {"Investigate": "#39cba3", "Capacity reached": "#fb7185", "Suppressed": "#f3ba62"}
POLICY_COLORS = {"Static": "#7aafff", "Adaptive": "#39cba3"}
MONITOR_METRICS = {
    "selected_alerts": ("Investigations", "count", "Number of alerts accepted for investigation within this transaction group."),
    "policy_candidate_alerts": ("Candidate alerts", "count", "Transactions that the selected policy flagged before suppression and capacity were applied."),
    "capacity_rejected_alerts": ("Capacity reached", "count", "Candidates not investigated because the operational-step investigation limit had already been used."),
    "suppressed_alerts": ("Suppressed alerts", "count", "Repeat-entity candidates removed by the Main suppression rule."),
    "frauds_detected": ("Frauds detected", "count", "Actual frauds among investigated transactions, known retrospectively from PaySim labels."),
    "frauds_missed": ("Frauds missed", "count", "Actual frauds not investigated, including frauds that never became candidates."),
    "recall": ("Fraud coverage (recall)", "percent", "Detected frauds divided by all actual frauds in this window. A window with no actual frauds has no defined recall."),
    "precision": ("Alert yield (precision)", "percent", "Detected frauds divided by investigations in this window. A window with no investigations has no defined precision."),
    "total_operational_cost": ("Estimated operational cost", "money", "Investigation spend plus modeled missed-fraud loss for the transactions in this window."),
}


def cards_html(items: list[dict]) -> str:
    """Escape data before putting it into the dashboard's compact card layout."""
    cards = []
    for item in items:
        tone = item.get("tone", "blue")
        if tone not in {"blue", "green", "rose", "amber", "violet"}:
            tone = "blue"
        delta = item.get("delta")
        delta_html = ""
        if delta:
            negative = str(delta).startswith(("-", "−"))
            inverse = item.get("delta_color") == "inverse"
            status = "neutral" if item.get("delta_color") == "off" else (
                "positive" if negative == inverse else "negative")
            if str(delta).startswith(("+0.0 pp", "-0.0 pp", "+€0.00", "-€0.00")):
                status = "neutral"
            delta_html = f'<span class="kpi-delta {status}">{escape(str(delta))}</span>'
        note = item.get("note", "")
        cards.append(
            f'<div class="analytics-kpi {tone}" title="{escape(str(item.get("help", "")), quote=True)}">'
            f'<div class="kpi-label">{escape(str(item["label"]))}</div>'
            f'<div class="kpi-value">{escape(str(item["value"]))}</div>{delta_html}'
            f'<div class="kpi-note">{escape(str(note))}</div></div>'
        )
    return f'<div class="analytics-grid" style="--card-count:{len(items)}">'+"".join(cards)+"</div>"


def comparison_html(summary: pd.DataFrame, selected_policy: str) -> str:
    rows = []
    for row in comparison_counts(summary).itertuples(index=False, name=None):
        label, static_value, adaptive_value, change = row
        rows.append(f'<tr><td>{escape(label)}</td><td class="static-number">{count(static_value)}</td>'
                    f'<td class="adaptive-number">{count(adaptive_value)}</td>'
                    f'<td class="change-number">{change:+,}</td></tr>')
    selected = '<span class="selected-chip">selected</span>'
    static_chip = selected if selected_policy == "static" else ""
    adaptive_chip = selected if selected_policy == "adaptive" else ""
    return ('<div class="comparison-panel"><table class="comparison-table"><thead><tr>'
            '<th>Outcome</th><th>Static '+static_chip+'</th><th>Adaptive '+adaptive_chip+'</th>'
            '<th>Change</th></tr></thead><tbody>'+"".join(rows)+'</tbody></table>'
            '<div class="panel-footnote">Change = Adaptive − Static. Non-fraud reviews use investigation capacity.</div></div>')


def cost_components_figure(summary: pd.DataFrame):
    policies = summary.set_index("policy")
    fig = make_subplots(rows=2, cols=1, vertical_spacing=.30,
                        subplot_titles=("Investigation spend", "Missed-fraud exposure"))
    for position, field in enumerate(["investigation_cost_total", "missed_fraud_cost"], start=1):
        values = [float(policies.loc[p, field]) for p in ["static", "adaptive"]]
        fig.add_trace(go.Bar(
            y=["Static", "Adaptive"], x=values, orientation="h",
            marker_color=[POLICY_COLORS["Static"], POLICY_COLORS["Adaptive"]],
            text=[amount(value) for value in values], textposition="outside", cliponaxis=False,
            hovertemplate="%{y}: €%{x:,.2f}<extra></extra>", showlegend=False,
        ), row=position, col=1)
        fig.update_xaxes(range=[0, max(max(values)*1.42, 1)], tickprefix="€", tickformat=".2s", row=position, col=1)
        fig.update_yaxes(autorange="reversed", row=position, col=1)
    fig.update_layout(bargap=.42)
    return fig


def filter_candidates(frame: pd.DataFrame, types=None, outcomes=None, step=None,
                      label="All labels", risk_range=(0.0, 1.0)) -> pd.DataFrame:
    chosen = frame.copy()
    if types is not None:
        chosen = chosen.loc[chosen["type"].astype(str).isin(types)]
    if outcomes is not None:
        chosen = chosen.loc[chosen["sequential_decision"].map(OUTCOME_LABELS).isin(outcomes)]
    if step is not None:
        chosen = chosen.loc[chosen["step"].eq(step)]
    if label != "All labels":
        chosen = chosen.loc[chosen["isFraud"].eq(int(label == "Fraud"))]
    chosen = chosen.loc[pd.to_numeric(chosen["fraud_score"], errors="coerce").between(*risk_range)]
    return chosen.sort_values(["step", "candidate_priority_rank"], kind="stable")


def decision_reason(row: pd.Series, capacity: int, suppression_window: int) -> str:
    """Describe the Main's recorded decision, without using the evaluation label."""
    rank, step = int(row.candidate_priority_rank), int(row.step)
    used = int(row.capacity_used_before_decision)
    remaining = int(row.capacity_remaining_after_decision)
    outcome = str(row.sequential_decision)
    if outcome == "alert":
        return (f"Priority #{rank} in step {step}. The candidate passed suppression and had an "
                f"investigation slot available: {used} of {capacity} slots were already used. "
                f"This investigation left {remaining} slots in the step.")
    if outcome == "capacity_rejected":
        return (f"Priority #{rank} in step {step}. The candidate was eligible after suppression, "
                f"but earlier accepted candidates had already used {used} of {capacity} slots. "
                f"The recorded remaining capacity was {remaining}, so it was not investigated.")
    if outcome == "suppressed":
        return (f"The Main marked this as a repeat-entity candidate within the {suppression_window}-step "
                f"suppression window. It did not use an investigation slot. "
                f"The recorded remaining capacity in step {step} was {remaining}.")
    return "The Main did not export a recognized sequential outcome for this candidate."


def priority_view(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Priority in step": frame["candidate_priority_rank"],
        "Transaction": frame["transaction_id"].map(lambda value: f"TX-{value}"),
        "Step": frame["step"], "Type": frame["type"],
        "Fraud risk (%)": pd.to_numeric(frame["fraud_score"])*100,
        "Priority score": frame["rank_score"],
        "Decision": frame["sequential_decision"].map(OUTCOME_LABELS),
    })


def capacity_statistics(steps: pd.DataFrame) -> dict:
    slots = int(steps["analyst_capacity"].sum())
    used = int(steps["investigated"].sum())
    return {"slots": slots, "used": used, "utilisation": used/slots if slots else 0.0,
            "unused": slots-used, "full_steps": int(steps["investigated"].ge(steps["analyst_capacity"]).sum()),
            "step_count": len(steps), "rejected": int(steps["capacity_rejected"].sum())}


def capacity_figure(steps: pd.DataFrame):
    fig = go.Figure()
    for field, label, color in [("investigated", "Investigated", "#39cba3"),
                                ("suppressed", "Suppressed", "#f3ba62"),
                                ("capacity_rejected", "Capacity reached", "#fb7185")]:
        fig.add_trace(go.Bar(
            x=steps["step"], y=steps[field], name=label, marker_color=color,
            customdata=steps[["candidates", "eligible_alerts", "analyst_capacity", "unused_capacity"]],
            hovertemplate=("Step %{x}<br>"+label+": %{y}<br>Candidates: %{customdata[0]}"
                           "<br>Eligible after suppression: %{customdata[1]}<br>Investigation slots: %{customdata[2]}"
                           "<br>Unused slots: %{customdata[3]}<extra></extra>"),
        ))
    fig.add_trace(go.Scatter(x=steps["step"], y=steps["analyst_capacity"], mode="lines",
                            name="Investigation capacity", line=dict(color="#c6d1e3", dash="dash"),
                            hovertemplate="Step %{x}<br>Investigation capacity: %{y}<extra></extra>"))
    fig.update_layout(barmode="stack", legend=dict(orientation="h", y=1.08, x=0),
                      xaxis_title="Operational step", yaxis_title="Candidate alerts")
    fig.update_xaxes(dtick=1)
    return fig


def transaction_flow_spec(types: pd.DataFrame, candidates_only: bool = False) -> dict:
    """Conserved full-population flow; no invented records or fractional dummy links."""
    frame = types.copy()
    if candidates_only:
        # Validate original totals before narrowing the reporting population.
        transaction_flow_spec(types)
        frame = frame.loc[frame.candidate_alerts.gt(0)].copy()
        frame["transactions"] = frame["candidate_alerts"]
    total = int(frame["transactions"].sum())
    labels = [f"{'Candidate alerts' if candidates_only else 'All transactions'} · {total:,}"]
    colors = ["#7aafff"]
    positions = [.01]
    node_details = [f"{'Candidate population' if candidates_only else 'Full evaluated population'}: {total:,} transactions"]
    source, target, values, details, link_colors = [], [], [], [], []
    palette = ["#7aafff", "#8b93ff", "#6ed5d7", "#c39cff", "#93bfdd"]
    for index, row in enumerate(frame.itertuples(index=False), start=1):
        labels.append(f"{row.type} · {int(row.transactions):,}")
        colors.append(palette[(index-1)%len(palette)])
        positions.append(.28)
        node_details.append(
            f"{escape(str(row.type))}<br>Transactions: {int(row.transactions):,}"
            f"<br>Candidates: {int(row.candidate_alerts):,}<br>Investigated: {int(row.investigated_alerts):,}"
            f"<br>Frauds found: {int(row.detected_frauds):,}<br>Suppressed: {int(row.suppressed):,}"
            f"<br>Capacity reached: {int(row.capacity_rejected):,}"
            f"<br>Actual frauds in all transactions: {int(row.actual_frauds):,}"
            f"<br>Average model risk: {float(row.average_fraud_score):.1%}"
        )
        source.append(0); target.append(index); values.append(int(row.transactions))
        details.append(node_details[-1]); link_colors.append("rgba(122,175,255,.19)")
    outcome_start = len(labels)
    outcome_labels = ["No candidate", "Investigated", "Suppressed", "Capacity reached"]
    outcome_totals = [int((frame.transactions-frame.candidate_alerts).sum()),
                      int(frame.investigated_alerts.sum()), int(frame.suppressed.sum()),
                      int(frame.capacity_rejected.sum())]
    for label, value, color in zip(outcome_labels, outcome_totals, ["#54667f", "#39cba3", "#f3ba62", "#fb7185"]):
        labels.append(f"{label} · {value:,}"); colors.append(color); positions.append(.64)
        node_details.append(f"{label}: {value:,} transactions")
    detected = int(frame.detected_frauds.sum())
    final_start = len(labels)
    for label, value, color in [("Frauds found", detected, "#39cba3"),
                                ("Non-fraud reviews", outcome_totals[1]-detected, "#7aafff")]:
        labels.append(f"{label} · {value:,}"); colors.append(color); positions.append(.97)
        node_details.append(f"{label}: {value:,}; retrospective evaluation labels")
    outcome_link_colors = ["rgba(84,102,127,.24)", "rgba(57,203,163,.44)",
                           "rgba(243,186,98,.40)", "rgba(251,113,133,.40)"]
    for index, row in enumerate(frame.itertuples(index=False), start=1):
        n, candidate, investigated = int(row.transactions), int(row.candidate_alerts), int(row.investigated_alerts)
        counts = [n-candidate, investigated, int(row.suppressed), int(row.capacity_rejected)]
        if min(counts) < 0 or sum(counts) != n or not 0 <= int(row.detected_frauds) <= investigated:
            raise ValueError(f"Transaction-type outcomes do not reconcile for {row.type}.")
        for offset, value in enumerate(counts):
            if value:
                source.append(index); target.append(outcome_start+offset); values.append(value)
                details.append(node_details[index]); link_colors.append(outcome_link_colors[offset])
    for offset, value in enumerate([detected, outcome_totals[1]-detected]):
        if value:
            source.append(outcome_start+1); target.append(final_start+offset); values.append(value)
            details.append("Investigated alerts split by retrospective fraud labels")
            link_colors.append(["rgba(57,203,163,.44)", "rgba(122,175,255,.36)"][offset])
    return {"total": total, "labels": labels, "colors": colors, "x": positions,
            "node_details": node_details, "source": source, "target": target,
            "values": values, "details": details, "link_colors": link_colors}


def transaction_flow_figure(spec: dict):
    fig = go.Figure(go.Sankey(
        arrangement="snap", valueformat=",.0f", valuesuffix=" transactions",
        node=dict(label=spec["labels"], color=spec["colors"], x=spec["x"], pad=25, thickness=15,
                  line=dict(color="#28384b", width=.5), customdata=spec["node_details"],
                  hovertemplate="%{customdata}<extra></extra>"),
        link=dict(source=spec["source"], target=spec["target"], value=spec["values"],
                  color=spec["link_colors"], customdata=spec["details"],
                  hovertemplate="%{source.label} → %{target.label}<br>%{value:,} transactions<br>%{customdata}<extra></extra>"),
    ))
    return fig


def monitoring_definition(frame: pd.DataFrame, window_size: int) -> str:
    first = frame.sort_values("monitoring_window").iloc[0]
    first_row, last_row = int(first.start_row)+1, int(first.end_row)+1
    return (f"{len(frame):,} consecutive reporting groups, normally {window_size:,} transactions each. "
            f"For example, window {int(first.monitoring_window)} contains replay positions "
            f"{first_row:,}–{last_row:,}, across steps {int(first.start_step)}–{int(first.end_step)}. "
            "Windows group ordered transactions, not fixed periods of time. Capacity resets per operational step, "
            "not per window; a step can span several windows. The last window may be smaller.")


def monitoring_insight(data: pd.DataFrame, column: str) -> str:
    valid = data.loc[data.Value.notna()]
    label, unit, _ = MONITOR_METRICS[column]
    if valid.empty:
        return "No defined values are available for this metric."
    focus = valid.loc[valid.Value.idxmin() if column in {"recall", "precision"} else valid.Value.idxmax()]
    value = f"{focus.Value:.1f}%" if unit == "percent" else amount(focus.Value) if unit == "money" else count(focus.Value)
    text = f"Window {int(focus.Window)} has the {'lowest' if column in {'recall', 'precision'} else 'highest'} {label.lower()}: {value}. "
    if column in {"recall", "precision"}:
        denominator = int(focus.total_frauds if column == "recall" else focus.selected_alerts)
        text += f"This rate is based on {int(focus.frauds_detected):,} detected frauds out of {denominator:,} {'actual frauds' if column == 'recall' else 'investigations'}. Small denominators can produce volatile rates. "
    elif column == "total_operational_cost":
        text += f"Missed-fraud exposure contributes {amount(focus.missed_fraud_cost)}; investigation spend contributes {amount(focus.investigation_cost_total)}. "
    else:
        text += f"That group contains {int(focus.total_transactions):,} transactions, {int(focus.selected_alerts):,} investigations and {int(focus.frauds_missed):,} missed frauds. "
    return text + "Inspect the window's step span in Analyst Capacity before attributing the change to capacity or prioritisation."



def monitoring_series(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    label, unit, _ = MONITOR_METRICS[column]
    data = frame.sort_values("monitoring_window").copy()
    values = pd.to_numeric(data[column], errors="coerce")
    if unit == "percent":
        denominator = "total_frauds" if column == "recall" else "selected_alerts"
        values = values.where(data[denominator].gt(0))*100
    data["Value"] = values
    data["Window"] = data["monitoring_window"].astype(int)
    data["Transactions"] = data["total_transactions"].astype(int)
    data["First replay position"] = data["start_row"].astype(int)+1
    data["Last replay position"] = data["end_row"].astype(int)+1
    data["Step span"] = data["start_step"].astype(str)+"–"+data["end_step"].astype(str)
    return data


st.markdown(
    '<div class="dashboard-header"><div class="eyebrow">SQL / Operations Reporting</div>'
    '<h1>Fraud Decision Analytics</h1>'
    '<p>Policy KPIs · Analyst Capacity · Decision Audit · Monitoring</p></div>',
    unsafe_allow_html=True,
)
st.caption("Companion to the Main Decision-Centric Fraud Framework · PaySim synthetic data · offline sequential replay")

if not DB_PATH.exists():
    st.warning("The sequential SQLite dataset has not been imported yet.")
    launch_import()
    st.stop()

try:
    db_version = DB_PATH.stat().st_mtime_ns
    missing, runs = describe_database(db_version)
except (sqlite3.DatabaseError, pd.errors.DatabaseError, OSError) as exc:
    st.error(f"Cannot read the SQLite database: {exc}")
    launch_import()
    st.stop()

if missing or runs.empty:
    detail = ", ".join(sorted(missing)) if missing else "No runs found"
    st.warning(f"The database does not contain the required sequential tables: {detail}")
    launch_import()
    st.stop()

run_options = (runs.assign(limit=pd.to_numeric(runs["limit"], errors="coerce"))
    .dropna(subset=["limit"]).sort_values(["limit", "imported_utc"])
    .drop_duplicates(subset=["limit"], keep="last"))
if run_options.empty:
    st.error("No usable sequential runs were found.")
    st.stop()

with st.sidebar:
    st.header("Simulation Settings")
    choices = sorted(run_options["limit"].astype(int).tolist())
    size = st.selectbox("Transactions evaluated", choices, index=len(choices)-1,
                        format_func=lambda x: f"{x:,}")
    # One policy selection shared by all Analytics reports.
    policy_label = st.selectbox("Decision policy", ["Static", "Adaptive"],
                                index=0, key="decision_policy")
    policy = policy_label.lower()
    st.caption("Selected-policy KPIs and detail reports follow this setting. "
               "Overview compares both policies, with Static first.")
    selected_run = run_options.loc[run_options["limit"].eq(size)].iloc[0]
    run_id = str(selected_run["run_id"])
    try:
        settings = json.loads(selected_run["parameters_json"])
        capacity = int(settings["alert_budget_per_step"])
    except (ValueError, TypeError, KeyError):
        st.error("The imported run does not include valid simulation settings.")
        st.stop()
    st.divider()
    st.markdown("**Main simulation assumptions**")
    st.write(f"Analyst capacity / step: **{capacity}**")
    st.write(f"Repeat-alert suppression: **{settings.get('suppression_window', '—')} steps**")
    with st.expander("Additional settings"):
        st.write(f"Static threshold: **{settings.get('static_threshold', '—')}**")
        st.write(f"Adaptive risk floor: **{settings.get('risk_zone_floor', '—')}**")
        st.write(f"Budget multiplier: **{settings.get('budget_multiplier', '—')}**")
        st.write(f"Investigation cost: **{settings.get('investigation_cost', '—')}**")
    st.caption("Selecting a policy changes reporting only. Main simulation assumptions are read-only.")
    st.divider()
    st.caption("Data source: local SQLite · /simulation/sequential")

try:
    overview = query_cached(SQL_OVERVIEW, run_id, None, db_version)
    static_steps = query_cached(SQL_STEP_WORKLOAD, run_id, "static", db_version)
    adaptive_steps = query_cached(SQL_STEP_WORKLOAD, run_id, "adaptive", db_version)
    issues = run_validation(overview, pd.concat([static_steps, adaptive_steps], ignore_index=True), capacity)
except (sqlite3.Error, pd.errors.DatabaseError, KeyError, ValueError, TypeError, AttributeError) as exc:
    st.error(f"Could not reconcile the sequential reporting tables: {exc}")
    launch_import()
    st.stop()

if issues:
    st.error("Main-vs-SQL checks did not reconcile. Results have been hidden.")
    for issue in issues:
        st.write(f"• {issue}")
    st.stop()

static = overview.set_index("policy").loc["static"]
adaptive = overview.set_index("policy").loc["adaptive"]
current = overview.set_index("policy").loc[policy]
try:
    audit = query_cached(SQL_AUDIT, run_id, policy, db_version)
    bytype = query_cached(SQL_TYPE_ANALYSIS, run_id, policy, db_version)
    monitoring = query_cached(SQL_MONITORING, run_id, policy, db_version)
except (sqlite3.Error, pd.errors.DatabaseError, KeyError) as exc:
    st.error(f"Could not load the selected policy reports: {exc}")
    st.stop()
steps = adaptive_steps if policy == "adaptive" else static_steps
other_label = "Adaptive" if policy == "static" else "Static"
other = adaptive if policy == "static" else static

st.caption(f"{count(size)} transactions · {count(static.total_frauds)} actual frauds · "
           f"imported {str(selected_run['imported_utc'])[:16]} UTC")
tab_overview, tab_capacity, tab_audit, tab_monitor = st.tabs([
    "Overview", "Analyst Capacity", "Audit Trail", "Monitoring",
])

with tab_overview:
    st.subheader(f"Executive Overview · {policy_label}")
    items = overview_kpis(current, other, other_label)
    for item, tone, note in zip(items, ["blue", "green", "violet", "amber"],
                                ["Detected / actual frauds", "Frauds per investigated alert",
                                 "Share of transactions reviewed", "Reviews + missed-fraud exposure"]):
        item.update(tone=tone, note=note)
    st.markdown(cards_html(items), unsafe_allow_html=True)
    comparison_column, cost_column = st.columns([1.15, 1])
    with comparison_column:
        st.markdown("**Outcomes & workload**")
        st.markdown(comparison_html(overview, policy), unsafe_allow_html=True)
    with cost_column:
        st.markdown("**Where the cost comes from**")
        st.markdown('<div class="policy-key"><span>Static</span><span>Adaptive</span></div>', unsafe_allow_html=True)
        styled_plot(cost_components_figure(overview), height=315)
        st.caption("Separate scales make review spend and missed-fraud exposure readable.")
    st.markdown('<div class="insight-panel"><strong>Business interpretation</strong>'
                +escape(comparison_reading(static, adaptive))+"</div>", unsafe_allow_html=True)
    with st.expander("Metric definitions and reporting scope"):
        st.markdown(
            "**Fraud coverage:** detected / actual frauds. **Alert yield:** detected / investigations. "
            "**Investigation rate:** investigations / evaluated transactions. "
            "Rate differences are percentage points (pp); cost differences compare the selected policy with the other policy. "
            "A dash means the denominator is zero. Both policies share the same sequential run. "
            "Fraud labels are retrospective; monetary costs are hypothetical simulation estimates."
        )

    with st.expander(f"Explore Transaction Flow · {policy_label}", expanded=False):
        st.caption(
            "Follow the selected policy's transaction types through alert screening, "
            "investigation, suppression and capacity outcomes. Use the sidebar to "
            "switch between Static and Adaptive."
        )
        flow_options = sorted(bytype["type"].dropna().astype(str).unique().tolist())
        selected_flow_types = st.multiselect(
            "Transaction types", options=flow_options, default=flow_options,
            key=f"overview_flow_types_{policy}",
        )
        type_context = bytype.loc[
            bytype["type"].astype(str).isin(selected_flow_types)
        ].copy()
        if type_context.empty:
            st.info("Select at least one transaction type to display its flow.")
        else:
            flow_scope = st.radio(
                "Flow population", ["All transactions", "Candidate alerts only"],
                horizontal=True, key=f"overview_flow_population_{policy}",
            )
            try:
                flow = transaction_flow_spec(
                    type_context, candidates_only=flow_scope == "Candidate alerts only"
                )
                if flow["total"]:
                    styled_plot(transaction_flow_figure(flow), height=540)
                else:
                    st.info("No candidate alerts exist for the selected transaction types.")
            except ValueError as exc:
                st.error(f"Transaction-type counts do not reconcile: {exc}")
            st.caption(
                "Frauds found and non-fraud reviews use retrospective PaySim labels. "
                "All transactions includes the No candidate branch; Candidate alerts only "
                "focuses on the recorded candidate outcomes."
            )

with tab_capacity:
    st.subheader(f"Analyst Capacity · {policy_label}")
    stats = capacity_statistics(steps)
    st.markdown(cards_html([
        {"label": "Investigation capacity used", "value": pct(stats["utilisation"]), "tone": "green",
         "note": f'{count(stats["used"])} of {count(stats["slots"])} slots across the replay'},
        {"label": "Steps at capacity", "value": f'{stats["full_steps"]} / {stats["step_count"]}', "tone": "rose",
         "note": "Operational cycles with all investigation slots used"},
        {"label": "Unused investigation slots", "value": count(stats["unused"]), "tone": "blue",
         "note": "Unused slots are not carried into the next step"},
        {"label": "Capacity-rejected candidates", "value": count(stats["rejected"]), "tone": "amber",
         "note": "Eligible candidates left without an investigation slot"},
    ]), unsafe_allow_html=True)
    st.markdown("**Capacity pressure by operational step**")
    styled_plot(capacity_figure(steps), height=325)
    st.caption("The dashed line is the investigation limit. Only the green Investigated segment consumes slots; "
               "suppressed and capacity-rejected candidates remain uninvestigated.")
    st.markdown("### Prioritised Investigation Queue")
    st.caption("Candidates retain the priority assigned by the Main within each operational step. "
               "Filter the queue, then inspect an individual decision below.")
    if audit.empty:
        st.info("No candidate alerts were exported for this policy.")
    else:
        q1, q2, q3, q4 = st.columns([.85, 1.05, 1.45, 1.1])
        step_options = [None]+sorted(audit["step"].dropna().unique().tolist())
        type_options = sorted(audit["type"].dropna().astype(str).unique().tolist())
        with q1:
            queue_step = st.selectbox("Operational step", step_options,
                format_func=lambda value: "All steps" if value is None else f"Step {int(value)}",
                key=f"capacity_step_{policy}")
        with q2:
            queue_types = st.multiselect("Transaction type", type_options, default=type_options,
                                         key=f"capacity_types_{policy}")
        with q3:
            queue_outcomes = st.multiselect("Queue outcome", list(OUTCOME_COLORS), default=list(OUTCOME_COLORS),
                                            key=f"capacity_outcomes_{policy}")
        with q4:
            queue_risk = st.slider("Fraud risk range", min_value=0.0, max_value=1.0, value=(0.0, 1.0),
                                   step=.05, format="%.2f", key=f"capacity_risk_{policy}")
        queue = filter_candidates(audit, types=queue_types, outcomes=queue_outcomes,
                                  step=queue_step, risk_range=queue_risk)
        accepted_in_view = int(queue["selected_alert"].eq(1).sum())
        st.caption(f"{len(queue):,} candidates in view · {accepted_in_view:,} investigated · "
                   f"{len(queue)-accepted_in_view:,} not investigated. The complete filtered queue is shown.")
        view = priority_view(queue)
        st.dataframe(view, hide_index=True, width="stretch", height=370,
            column_config={
                "Fraud risk (%)": st.column_config.NumberColumn(format="%.1f%%", help="Model-estimated fraud probability."),
                "Priority score": st.column_config.NumberColumn(format="%.3f", help="Main's ranking value; not a probability."),
                "Priority in step": st.column_config.NumberColumn(format="%d", help="Recorded candidate order within this step."),
            })
        st.download_button("Download prioritised queue (CSV)", view.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"prioritised_queue_{size}_{policy}.csv", mime="text/csv")
        st.markdown("### Alert Decision Explanation")
        if queue.empty:
            st.info("No candidates match these filters. Broaden the filters to inspect a decision.")
        else:
            options = queue["transaction_id"].tolist()
            selection_key = f"capacity_transaction_{policy}"
            if selection_key in st.session_state and st.session_state[selection_key] not in options:
                st.session_state[selection_key] = options[0]
            selected_transaction = st.selectbox("Select a transaction to explain", options,
                format_func=lambda value: f"TX-{value}", key=selection_key)
            chosen = queue.loc[queue["transaction_id"].eq(selected_transaction)].iloc[0]
            outcome = OUTCOME_LABELS.get(str(chosen.sequential_decision), "Unknown")
            decision_tone = {"Investigate": "green", "Suppressed": "amber", "Capacity reached": "rose"}.get(outcome, "blue")
            st.markdown(cards_html([
                {"label": "Transaction type", "value": chosen.type, "note": "Synthetic PaySim category"},
                {"label": "Fraud risk", "value": pct(chosen.fraud_score), "note": "Model-estimated probability"},
                {"label": "Priority score", "value": f"{float(chosen.rank_score):,.3f}", "note": "Operational ranking value"},
                {"label": "Priority in step", "value": f"#{int(chosen.candidate_priority_rank)} · step {int(chosen.step)}",
                 "note": "Recorded order before the capacity decision"},
                {"label": "Final decision", "value": outcome, "tone": decision_tone, "note": "Outcome exported by the Main"},
            ]), unsafe_allow_html=True)
            reason = decision_reason(chosen, capacity, int(settings.get("suppression_window", 0)))
            st.markdown('<div class="decision-panel"><strong>Why this decision?</strong>'
                        +escape(reason)+"</div>", unsafe_allow_html=True)
            with st.expander("Fraud risk, priority and recorded decision details"):
                st.markdown(
                    "**Fraud risk** estimates how likely fraud is. **Priority score** determines the relative "
                    "importance of an eligible candidate under the Main policy; it is not a percentage. "
                    "The sequential engine orders candidates within each step by priority score, then fraud risk "
                    "and transaction ID. Suppression is checked before assigning an investigation slot. "
                    "These explanations use recorded decisions and capacity counters; ground-truth labels do not influence them."
                )
                st.json(json.loads(chosen.to_json()))
                st.caption("isFraud is retrospective evaluation data, available in Audit Trail; it was unknown at decision time.")

with tab_audit:
    st.subheader(f"Decision Audit Trail · {policy_label}")
    st.caption("Retrospective candidate-level analysis: filter recorded decisions, review fraud labels and export the audit table.")
    a1, a2, a3, a4 = st.columns([1.2, 1.3, .85, 1])
    all_types = sorted(bytype["type"].dropna().astype(str).unique().tolist())
    with a1:
        audit_types = st.multiselect("Transaction type", all_types, default=all_types, key=f"audit_types_{policy}")
    with a2:
        audit_outcomes = st.multiselect("Decision outcome", list(OUTCOME_COLORS), default=list(OUTCOME_COLORS),
                                        key=f"audit_outcomes_{policy}")
    with a3:
        audit_step = st.selectbox("Operational step", [None]+sorted(audit["step"].dropna().unique().tolist()),
            format_func=lambda value: "All steps" if value is None else f"Step {int(value)}", key=f"audit_step_{policy}")
    with a4:
        audit_label = st.selectbox("Actual label", ["All labels", "Fraud", "Non-fraud"], key=f"audit_label_{policy}")
    filtered = filter_candidates(audit, types=audit_types, outcomes=audit_outcomes, step=audit_step, label=audit_label)
    metric_row([
        ("Matching candidates", count(len(filtered))),
        ("Investigated", count(filtered["selected_alert"].eq(1).sum())),
        ("Actual frauds in view", count(filtered["isFraud"].eq(1).sum())),
        ("Frauds detected in view", count((filtered["selected_alert"].eq(1)&filtered["isFraud"].eq(1)).sum())),
    ])
    audit_view = pd.DataFrame({
        "Transaction": filtered["transaction_id"].map(lambda value: f"TX-{value}"),
        "Step": filtered["step"], "Type": filtered["type"], "Amount": filtered["amount"],
        "Fraud risk (%)": pd.to_numeric(filtered["fraud_score"])*100,
        "Decision": filtered["sequential_decision"].map(OUTCOME_LABELS),
        "Actual label": filtered["isFraud"].map({1: "Fraud", 0: "Non-fraud"}),
    })
    st.dataframe(audit_view, hide_index=True, width="stretch", height=380,
        column_config={"Amount": st.column_config.NumberColumn(format="%.2f"),
                       "Fraud risk (%)": st.column_config.NumberColumn(format="%.1f%%")})
    st.download_button("Download filtered audit (CSV)", filtered.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"decision_audit_{size}_{policy}.csv", mime="text/csv")

with tab_monitor:
    st.subheader(f"Monitoring · {policy_label}")
    if monitoring.empty:
        st.info("No monitoring windows were exported for this policy.")
    else:
        window_size = int(settings.get("monitoring_window_size", monitoring["total_transactions"].max()))
        st.markdown('<div class="explain-panel"><strong>What is a monitoring window?</strong>'
                    +escape(monitoring_definition(monitoring, window_size))+"</div>", unsafe_allow_html=True)
        options = [name for name in MONITOR_METRICS if name in monitoring.columns]
        metric_key = f"monitor_metric_{policy}"
        if metric_key in st.session_state and st.session_state[metric_key] not in options:
            st.session_state[metric_key] = options[0]
        monitor_column = st.selectbox("What would you like to monitor?", options,
            format_func=lambda name: MONITOR_METRICS[name][0], key=metric_key)
        label, unit, explanation = MONITOR_METRICS[monitor_column]
        st.caption(explanation)
        chart_data = monitoring_series(monitoring, monitor_column)
        valid_values = chart_data.loc[chart_data["Value"].notna()]
        if valid_values.empty:
            st.info("This rate is undefined in every window because its denominator is zero.")
        else:
            fig = px.line(chart_data, x="Window", y="Value", markers=True,
                          labels={"Window": "Monitoring window", "Value": label+(" (%)" if unit == "percent" else "")},
                          hover_data={"Transactions": True, "First replay position": True,
                                      "Last replay position": True, "Step span": True})
            fig.update_traces(line=dict(color=POLICY_COLORS[policy_label], width=3),
                              marker=dict(size=8), connectgaps=False)
            fig.update_xaxes(dtick=1)
            if unit == "percent": fig.update_yaxes(ticksuffix="%", range=[0, 105])
            if unit == "money": fig.update_yaxes(tickprefix="€", tickformat=".3s")
            styled_plot(fig, height=360)
            st.markdown('<div class="insight-panel"><strong>What deserves attention</strong>'
                +escape(monitoring_insight(chart_data, monitor_column))+"</div>", unsafe_allow_html=True)
        if unit == "percent":
            st.caption("Undefined rates are shown as gaps; a gap does not mean 0% performance.")
        with st.expander("Window-by-window results"):
            table = pd.DataFrame({
                "Window": monitoring["monitoring_window"],
                "Transactions": monitoring["total_transactions"],
                "Replay positions": (monitoring["start_row"]+1).astype(str)+"–"+(monitoring["end_row"]+1).astype(str),
                "Step span": monitoring["start_step"].astype(str)+"–"+monitoring["end_step"].astype(str),
                "Candidates": monitoring["policy_candidate_alerts"],
                "Investigated": monitoring["selected_alerts"],
                "Frauds found": monitoring["frauds_detected"],
                "Frauds missed": monitoring["frauds_missed"],
                "Estimated cost": monitoring["total_operational_cost"].map(amount),
            })
            st.dataframe(table, hide_index=True, width="stretch")
        st.caption("Groups are the original monitoring windows exported by the Main; their boundaries are preserved.")

with st.expander("SQL methodology · queries used in this dashboard"):
    st.caption("Queries used by the actual reports: CTEs, JOINs, conditional aggregation and window functions.")
    sql_queries = {
        "KPI validation · CTE + JOIN": SQL_OVERVIEW,
        "Transaction types · CTE + LEFT JOIN": SQL_TYPE_ANALYSIS,
        "Step workload · ROW_NUMBER / SUM OVER": SQL_STEP_WORKLOAD,
        "Decision audit · ROW_NUMBER": SQL_AUDIT,
    }
    chosen_sql = st.selectbox("Explore SQL", list(sql_queries))
    st.code(sql_queries[chosen_sql].strip(), language="sql")
st.divider()
st.caption("Main /simulation/sequential → SQLite → SQL queries → Streamlit. "
           "Synthetic PaySim data · simulation-based analytics.")
