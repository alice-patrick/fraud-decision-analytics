"""Fraud Operations Analytics — recruiter-first reporting UI.

Data source: the existing sequential SQLite exports from the Main Framework.
This dashboard reports stored outputs; it never recalculates fraud predictions or decisions.

Run: python -m streamlit run dashboards/thesis_decision_dashboard.py
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("ANALYTICS_DB_PATH", str(ROOT / "data" / "processed" / "fraud_investigation.db")))
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
    page_title="Fraud Operations Analytics", page_icon="📊",
    layout="wide", initial_sidebar_state="expanded",
)
st.markdown("""<style>
.block-container {max-width:1220px; padding-top:1.7rem; padding-bottom:2.5rem;}
#MainMenu {visibility:hidden;}
.hero {background:linear-gradient(110deg,#18273a,#151c29 85%);
  border:1px solid #2e4155; border-left:4px solid #51c7bc;
  padding:22px 25px; border-radius:16px; margin-bottom:14px;}
.hero .label {font-size:.72rem; font-weight:700; color:#68d7c6; letter-spacing:.11em;}
.hero h1 {color:#f2f7ff; margin:5px 0 8px; font-size:2.05rem; letter-spacing:-.045em;}
.hero p {color:#b5c6d9; margin:0; font-size:.96rem;}
[data-testid="stMetric"] {background:#171e2a; border:1px solid #2d3b4c;
  border-top:2px solid #55b9be; border-radius:11px; padding:12px 16px; min-height:126px;}
[data-testid="stMetricLabel"] {color:#a7b8cb;}
[data-testid="stMetricValue"] {font-size:1.7rem;}
[data-testid="stTabs"] [data-baseweb="tab-highlight"]{background:#58c8ba;}
button[data-baseweb="tab"][aria-selected="true"]{color:#79ddca!important;}
section[data-testid="stSidebar"] {border-right:1px solid #303a4a;}
.insight {background:#172734; border:1px solid #28505a; border-left:3px solid #53c6b8;
  padding:15px 18px; border-radius:11px; color:#d5e2ed; margin:12px 0 16px; line-height:1.6;}
.insight strong {color:#f5fafc;}
.small-print {font-size:.77rem; color:#98adbf;}
</style>""", unsafe_allow_html=True)


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


def fmt_int(value) -> str:
    return f"{int(value):,}"


def chart_style(fig: go.Figure, height: int = 365) -> None:
    fig.update_layout(
        template="plotly_dark", height=height, margin=dict(l=10, r=10, t=18, b=14),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#cad8e7", size=12),
        legend=dict(orientation="h", x=0, y=1.11, title=""),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="rgba(140,160,180,.13)", zeroline=False)
    st.plotly_chart(fig, width="stretch")


def headline_text(total: int, fraud: int, reviews: int, detected: int) -> str:
    """A business interpretation, not a verbatim repetition of the four headline KPIs."""
    if not total:
        return "There are no evaluated transactions in this sample."
    reviewed_share = 100 * reviews / total
    if not fraud:
        return (f"Investigations covered <strong>{reviewed_share:.1f}%</strong> of transactions. "
                "This sample has no labelled fraud cases, so detection effectiveness cannot be assessed.")
    covered = 100 * detected / fraud
    return (f"Reviewing <strong>{reviewed_share:.1f}%</strong> of transactions captured "
            f"<strong>{covered:.1f}%</strong> of labelled fraud cases. "
            "This is an offline evaluation using synthetic data, not a live banking result.")


def policy_comparison(frame: pd.DataFrame) -> pd.DataFrame:
    records = []
    for label, p in (("Baseline (Static)", "static"), ("Alternative (Adaptive)", "adaptive")):
        item = frame.set_index("policy").loc[p]
        records.append({
            "Scenario": label,
            "Investigations": int(item.selected_alerts),
            "Fraud cases detected": int(item.frauds_detected),
            "Detection rate": f"{100 * float(item.recall):.1f}%" if item.total_frauds else "—",
            "Estimated cost (simulation)": f"{float(item.total_operational_cost):,.0f}",
        })
    return pd.DataFrame(records)


def transaction_summary(table: pd.DataFrame) -> pd.DataFrame:
    frame = table.copy()
    frame["Fraud rate"] = frame.apply(
        lambda r: 100 * float(r["actual_frauds"]) / float(r["transactions"])
        if r["transactions"] else float("nan"), axis=1,
    )
    return frame.rename(columns={
        "type": "Transaction type", "transactions": "Transactions",
        "actual_frauds": "Fraud cases", "investigated_alerts": "Investigated",
    })[["Transaction type", "Transactions", "Fraud cases", "Fraud rate"]]


def transaction_insight(frame: pd.DataFrame) -> str:
    """Differentiate transaction volume, observed fraud count and fraud rate."""
    if frame.empty:
        return "No transaction types are available."
    valid = frame.loc[frame["transactions"].gt(0)].copy()
    if valid.empty:
        return "No transactions are available in the type breakdown."
    volume = valid.sort_values(["transactions", "type"], ascending=[False, True]).iloc[0]
    if int(valid["actual_frauds"].sum()) == 0:
        return (f"<strong>{escape(str(volume['type']))}</strong> has the highest transaction volume "
                f"({fmt_int(volume['transactions'])}), but no fraud cases were observed in this sample.")
    count_leader = valid.sort_values(["actual_frauds", "type"], ascending=[False, True]).iloc[0]
    valid["observed_rate"] = valid["actual_frauds"] / valid["transactions"]
    rate_leader = valid.sort_values(["observed_rate", "transactions", "type"],
                                    ascending=[False, False, True]).iloc[0]
    result = (f"<strong>{escape(str(volume['type']))}</strong> has the most transactions, while "
              f"<strong>{escape(str(count_leader['type']))}</strong> has the most fraud cases. "
              f"The highest observed fraud rate is in <strong>{escape(str(rate_leader['type']))}</strong> "
              f"({rate_leader['observed_rate']:.2%}; "
              f"{fmt_int(rate_leader['actual_frauds'])} of {fmt_int(rate_leader['transactions'])} transactions).")
    if int(rate_leader["transactions"]) < 100:
        result += " This rate is based on a small group and should be interpreted cautiously."
    return result


def workload_insight(steps: pd.DataFrame) -> str:
    """Explain where capacity was lost rather than repeating overall totals."""
    if steps.empty:
        return "No investigation workload data are available."
    rejected = int(steps["capacity_rejected"].sum())
    unfilled = int(steps["unused_capacity"].sum())
    constrained = int(steps["capacity_rejected"].gt(0).sum())
    if rejected and unfilled:
        return (f"<strong>{fmt_int(rejected)} eligible alerts</strong> went unreviewed in "
                f"<strong>{constrained}</strong> capacity-constrained steps, while "
                f"<strong>{fmt_int(unfilled)} investigation slots</strong> were unused in other steps. "
                "Unused capacity cannot be transferred between steps; workload varies across the replay.")
    if rejected:
        return (f"<strong>{fmt_int(rejected)} eligible alerts</strong> went unreviewed because "
                f"capacity was exhausted in <strong>{constrained}</strong> steps.")
    if unfilled:
        return (f"No eligible alerts were excluded by capacity. "
                f"<strong>{fmt_int(unfilled)} slots</strong> remained unused during the replay.")
    return "Investigation capacity was fully used and no eligible alerts were excluded by capacity."


def monitoring_insight(windows: pd.DataFrame) -> str:
    """Explain monitoring extremes using actual fraud counts, not rates alone."""
    if windows.empty:
        return "No monitoring results are available."
    meaningful = windows.loc[windows["total_frauds"].gt(0)].copy()
    if meaningful.empty:
        return "No fraud cases occurred in these reporting groups, so detection rates are undefined."

    meaningful["measured_coverage"] = (
        meaningful["frauds_detected"] / meaningful["total_frauds"]
    )
    low = meaningful.sort_values(
        ["measured_coverage", "monitoring_window"], ascending=[True, True]
    ).iloc[0]
    high = meaningful.sort_values(
        ["measured_coverage", "monitoring_window"], ascending=[False, True]
    ).iloc[0]

    low_total = int(low["total_frauds"])
    low_missed = low_total - int(low["frauds_detected"])
    high_total = int(high["total_frauds"])
    high_found = int(high["frauds_detected"])
    result = (
        f"Detection rates ranged from <strong>{low['measured_coverage']:.1%}</strong> "
        f"to <strong>{high['measured_coverage']:.1%}</strong> across groups containing fraud. "
        f"Group <strong>{int(low['monitoring_window'])}</strong> missed "
        f"<strong>{fmt_int(low_missed)} of {fmt_int(low_total)}</strong> fraud cases. "
        f"The highest rate was in group <strong>{int(high['monitoring_window'])}</strong>: "
        f"<strong>{fmt_int(high_found)} of {fmt_int(high_total)}</strong> fraud cases detected."
    )
    if min(low_total, high_total) < 10:
        result += " Small fraud counts can make these percentages fluctuate sharply."
    return result + " Reporting groups are consecutive transaction batches, not calendar periods."


def audit_records(frame: pd.DataFrame, tx_type: str, outcome: str, label: str) -> pd.DataFrame:
    result = frame.copy()
    if tx_type != "All types":
        result = result.loc[result["type"].eq(tx_type)]
    if outcome != "All outcomes":
        result = result.loc[result["sequential_decision"].map({
            "alert": "Investigated", "suppressed": "Suppressed",
            "capacity_rejected": "No available slot",
        }).eq(outcome)]
    if label == "Fraud":
        result = result.loc[result["isFraud"].eq(1)]
    elif label == "Not fraud":
        result = result.loc[result["isFraud"].eq(0)]
    return result.sort_values(["step", "candidate_priority_rank"], kind="stable")


st.markdown(
    '<div class="hero"><div class="label">DATA ANALYTICS PORTFOLIO</div>'
    '<h1>Fraud Operations Analytics</h1>'
    '<p>A clear view of transaction activity, fraud trends and investigation performance.</p></div>',
    unsafe_allow_html=True,
)

if not DB_PATH.exists():
    st.error("No imported reporting database was found. Keep the existing SQLite database in "
             "`data/processed/fraud_investigation.db` and restart the dashboard.")
    st.stop()

try:
    db_stamp = DB_PATH.stat().st_mtime_ns
    missing, runs = describe_database(db_stamp)
except (sqlite3.Error, OSError, pd.errors.DatabaseError) as exc:
    st.error(f"Could not open the reporting database: {exc}")
    st.stop()

if missing or runs.empty:
    st.error("The existing SQLite file is missing the sequential reporting data. "
             "Restore your validated Analytics database rather than changing the dashboard.")
    st.stop()

run_options = (runs.assign(limit=pd.to_numeric(runs["limit"], errors="coerce"))
               .dropna(subset=["limit"])
               .sort_values(["limit", "imported_utc"])
               .drop_duplicates(subset=["limit"], keep="last"))
if run_options.empty:
    st.error("No reporting runs were found.")
    st.stop()

with st.sidebar:
    st.markdown("### Report filters")
    sizes = sorted(run_options["limit"].astype(int).tolist())
    size = st.selectbox("Transactions", sizes, index=len(sizes)-1,
                        format_func=lambda x: f"{x:,}")
    scenario = st.selectbox("Investigation strategy", ["Static", "Adaptive"], index=0,
                            help="Static is the baseline. Adaptive is an alternative strategy applied to the same transactions.")
    st.caption("Static = baseline · Adaptive = alternative")

policy = scenario.lower()
selected_run = run_options.loc[run_options["limit"].eq(size)].iloc[0]
run_id = str(selected_run["run_id"])
try:
    settings = json.loads(selected_run["parameters_json"])
    capacity = int(settings["alert_budget_per_step"])
    summaries = query_cached(SQL_OVERVIEW, run_id, None, db_stamp)
    steps = query_cached(SQL_STEP_WORKLOAD, run_id, policy, db_stamp)
    steps_all = pd.concat([
        query_cached(SQL_STEP_WORKLOAD, run_id, p, db_stamp)
        for p in ("static", "adaptive")
    ], ignore_index=True)
    issues = run_validation(summaries, steps_all, capacity)
    if issues:
        raise ValueError("; ".join(issues))
    types = query_cached(SQL_TYPE_ANALYSIS, run_id, policy, db_stamp)
    trends = query_cached(SQL_MONITORING, run_id, policy, db_stamp)
    candidates = query_cached(SQL_AUDIT, run_id, policy, db_stamp)
    if int(types["transactions"].sum()) != size:
        raise ValueError("Transaction-type totals do not match the selected sample.")
except (ValueError, TypeError, KeyError, sqlite3.Error, pd.errors.DatabaseError) as exc:
    st.error(f"Data quality check failed; results were hidden: {exc}")
    st.stop()

current = summaries.set_index("policy").loc[policy]
# Each tab has its own purpose. Do not reuse a chart or KPI set in another tab.
st.caption(f"{scenario} investigation strategy · Synthetic PaySim sample · Offline evaluation")
tab_overview, tab_types, tab_work, tab_audit = st.tabs([
    "Overview", "Transaction Patterns", "Investigation Performance", "Performance Monitoring",
])

with tab_overview:
    st.subheader("Business snapshot")
    st.caption("What happened across the evaluated transactions?")
    total, fraud, investigated, found = (
        int(current.total_transactions), int(current.total_frauds),
        int(current.selected_alerts), int(current.frauds_detected),
    )
    a, b, c, d = st.columns(4)
    a.metric("Total Transactions", fmt_int(total))
    b.metric("Fraud Rate", f"{100 * fraud / total:.2f}%" if total else "—",
             help=f"{fmt_int(fraud)} fraud cases among {fmt_int(total)} synthetic transactions.")
    c.metric("Investigations", fmt_int(investigated))
    d.metric("Fraud Detection Rate", f"{100 * found / fraud:.1f}%" if fraud else "—",
             help=f"{fmt_int(found)} of {fmt_int(fraud)} actual fraud cases were investigated. "
                  "Detection rate is undefined when there are no fraud cases.")
    st.markdown('<div class="insight"><strong>Business takeaway</strong><br>' +
                headline_text(total, fraud, investigated, found) + '</div>',
                unsafe_allow_html=True)

    with st.expander("Compare Investigation Strategies", expanded=False):
        st.caption("A simple comparison of investigation outcomes. Both strategies use the same transactions.")
        st.dataframe(policy_comparison(summaries), hide_index=True, width="stretch")
        diff_frauds = int(summaries.set_index("policy").loc["adaptive", "frauds_detected"]) - int(
            summaries.set_index("policy").loc["static", "frauds_detected"])
        diff_reviews = int(summaries.set_index("policy").loc["adaptive", "selected_alerts"]) - int(
            summaries.set_index("policy").loc["static", "selected_alerts"])
        st.caption(f"Adaptive vs Static: {diff_frauds:+,} fraud cases detected and {diff_reviews:+,} investigations"
                   " in this sample. Costs are simulated, not actual bank savings.")

with tab_types:
    st.subheader("Transaction Patterns")
    st.caption("Which transaction types dominate volume, and which have higher fraud rates?")
    if types.empty:
        st.info("No transaction categories were exported.")
    else:
        sorted_types = types.sort_values("transactions", ascending=True)
        fig = go.Figure(go.Bar(
            x=sorted_types["transactions"], y=sorted_types["type"], orientation="h",
            marker_color="#6ba9fa", text=sorted_types["transactions"], textposition="outside",
            hovertemplate="%{y}: %{x:,} transactions<extra></extra>",
        ))
        fig.update_layout(xaxis_title="Transactions", yaxis_title="", showlegend=False)
        chart_style(fig, height=350)

        st.markdown("**Fraud cases and fraud rate by type**")
        category_report = transaction_summary(types)
        st.dataframe(category_report.sort_values(["Fraud rate", "Fraud cases"], ascending=[False, False]),
                     hide_index=True, width="stretch",
                     column_config={
                         "Fraud rate": st.column_config.NumberColumn(label="Fraud rate", format="%.2f%%")
                     })
        st.markdown('<div class="insight"><strong>Business insight</strong><br>' +
                    transaction_insight(types) + '</div>', unsafe_allow_html=True)
        st.download_button("Export transaction summary (CSV)",
                           category_report.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"transactions_{size}_{policy}.csv", mime="text/csv")

with tab_work:
    st.subheader("Investigation Performance")
    st.caption("Were investigation teams fully utilised, and where were reviews missed?")
    if steps.empty:
        st.info("No workload records are available.")
    else:
        slots = int(steps["analyst_capacity"].sum())
        used = int(steps["investigated"].sum())
        blocked = int(steps["capacity_rejected"].sum())
        k1, k2 = st.columns(2)
        k1.metric("Investigation Capacity Used", f"{100 * used / slots:.1f}%" if slots else "—")
        k2.metric("Alerts Not Reviewed (Capacity)", fmt_int(blocked),
                  help="Eligible alerts excluded because their step had no investigation slots left.")
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=steps["step"], y=steps["investigated"], name="Investigated",
            marker_color="#55c8b0", hovertemplate="Step %{x}<br>%{y} investigations<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=steps["step"], y=steps["analyst_capacity"], name="Review capacity",
            mode="lines+markers", line=dict(color="#f3ba66", dash="dash", width=2),
            hovertemplate="Step %{x}<br>%{y} available slots<extra></extra>",
        ))
        fig.update_layout(xaxis_title="Review cycle (step)", yaxis_title="Investigations",
                          xaxis=dict(dtick=1), barmode="overlay")
        chart_style(fig, height=370)
        st.markdown('<div class="insight"><strong>Business insight</strong><br>' +
                    workload_insight(steps) + '</div>', unsafe_allow_html=True)

with tab_audit:
    st.subheader("Performance Monitoring")
    st.caption("How did fraud detection performance change through the transaction replay?")
    if trends.empty:
        st.info("No monitoring windows were exported.")
    else:
        windows = trends.sort_values("monitoring_window").copy()
        windows["Coverage"] = windows["recall"].where(windows["total_frauds"].gt(0)) * 100
        fig = go.Figure(go.Scatter(
            x=windows["monitoring_window"], y=windows["Coverage"],
            mode="lines+markers", line=dict(color="#8eb8ff", width=3),
            marker=dict(size=9), customdata=windows[["total_frauds", "frauds_detected"]],
            hovertemplate="Group %{x}<br>Fraud coverage: %{y:.1f}%<br>"
                          "Fraud cases: %{customdata[0]}<br>Detected: %{customdata[1]}<extra></extra>",
        ))
        fig.update_layout(yaxis_title="Fraud detection rate (%)", xaxis_title="Reporting group",
                          xaxis=dict(dtick=1), yaxis=dict(range=[0, 105], ticksuffix="%"))
        chart_style(fig, height=350)
        st.markdown('<div class="insight"><strong>Business insight</strong><br>' +
                    monitoring_insight(windows) + '</div>', unsafe_allow_html=True)
        st.caption("A gap means a reporting group had no fraud cases, so its detection rate is undefined.")

    with st.expander("Explore individual alert records", expanded=False):
        st.caption("This audit contains alert candidates only; it does not contain every transaction.")
        types_present = sorted(candidates["type"].dropna().astype(str).unique())
        f1, f2, f3 = st.columns(3)
        with f1:
            chosen_type = st.selectbox("Transaction type", ["All types", *types_present])
        with f2:
            chosen_outcome = st.selectbox(
                "Investigation outcome", ["All outcomes", "Investigated", "No available slot", "Suppressed"])
        with f3:
            chosen_label = st.selectbox("Actual fraud label", ["All labels", "Fraud", "Not fraud"])
        filtered = audit_records(candidates, chosen_type, chosen_outcome, chosen_label)
        st.caption(f"{fmt_int(len(filtered))} alert records match your filters.")
        if filtered.empty:
            st.info("No alerts match these filters.")
        else:
            show = pd.DataFrame({
                "Transaction": filtered["transaction_id"].map(lambda v: f"TX-{v}"),
                "Step": filtered["step"],
                "Type": filtered["type"],
                "Amount": filtered["amount"],
                "Fraud risk": pd.to_numeric(filtered["fraud_score"], errors="coerce") * 100,
                "Outcome": filtered["sequential_decision"].map({
                    "alert": "Investigated", "capacity_rejected": "No available slot",
                    "suppressed": "Suppressed"}),
                "Actual label": filtered["isFraud"].map({1:"Fraud", 0:"Not fraud"}),
            })
            st.dataframe(show, hide_index=True, width="stretch", height=325,
                         column_config={"Fraud risk": st.column_config.NumberColumn(format="%.1f%%")})
            st.download_button("Export filtered records (CSV)",
                               show.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"fraud_audit_{size}_{policy}.csv", mime="text/csv")

st.markdown(
    '<p class="small-print">Data: synthetic PaySim transactions and archived investigation decisions. '
    'All fraud labels and costs are retrospective / simulated.</p>',
    unsafe_allow_html=True,
)
