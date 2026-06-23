import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "processed" / "fraud_investigation.db"

st.set_page_config(
    page_title="Thesis Decision Analytics",
    page_icon="🧠",
    layout="wide",
)

st.title("🧠 Thesis Decision Analytics Dashboard")
st.caption(
    "Decision-centric fraud analytics using thesis FastAPI outputs, SQLite exports, "
    "adaptive alerting, analyst prioritization, cost analysis, and auditability."
)


@st.cache_data
def load_table(table_name: str) -> pd.DataFrame:
    connection = sqlite3.connect(DATABASE_PATH)
    df = pd.read_sql_query(f"SELECT * FROM {table_name}", connection)
    connection.close()
    return df


def format_money(value: float) -> str:
    if pd.isna(value):
        return "$0"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:,.1f}K"
    return f"${value:,.0f}"


def format_money_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    formatted_df = df.copy()
    for column in columns:
        if column in formatted_df.columns:
            formatted_df[column] = formatted_df[column].apply(format_money)
    return formatted_df


def calculate_precision_recall_at_k(data: pd.DataFrame) -> pd.DataFrame:
    ranked_alerts = (
        data[data["adaptive_alert"] == 1]
        .sort_values("rank_score", ascending=False)
        .reset_index(drop=True)
    )

    total_frauds = int(data["isFraud"].sum())
    rows = []

    for k in [50, 100, 250]:
        top_k = ranked_alerts.head(k)
        alerts_reviewed = len(top_k)
        frauds_found = int(top_k["isFraud"].sum())

        precision_at_k = frauds_found / alerts_reviewed if alerts_reviewed else 0
        recall_at_k = frauds_found / total_frauds if total_frauds else 0

        rows.append(
            {
                "k": k,
                "alerts_reviewed": alerts_reviewed,
                "frauds_found": frauds_found,
                "precision_at_k": precision_at_k,
                "recall_at_k": recall_at_k,
            }
        )

    return pd.DataFrame(rows)


try:
    df = load_table("thesis_decision_export")
    summary_df = load_table("thesis_operational_summary")
    curve_df = load_table("thesis_operating_curve")
except Exception as error:
    st.error(
        "Could not load thesis SQLite tables. First run:\n\n"
        "`py scripts/import_from_thesis_api.py`"
    )
    st.exception(error)
    st.stop()


# =========================================================
# Sidebar filters
# =========================================================

st.sidebar.header("Simulation Settings")

if "simulation_limit" in df.columns:
    available_limits = sorted(df["simulation_limit"].unique())

    selected_limit = st.sidebar.selectbox(
        "Simulation Limit",
        options=available_limits,
        index=len(available_limits) - 1,
    )

    df = df[df["simulation_limit"] == selected_limit].copy()
    summary_df = summary_df[summary_df["simulation_limit"] == selected_limit].copy()
    curve_df = curve_df[curve_df["simulation_limit"] == selected_limit].copy()
else:
    selected_limit = None


st.sidebar.header("Filters")

severity_options = sorted(df["severity"].dropna().unique())
type_options = sorted(df["type"].dropna().unique())

severity_filter = st.sidebar.multiselect(
    "Severity",
    options=severity_options,
    default=severity_options,
)

type_filter = st.sidebar.multiselect(
    "Transaction Type",
    options=type_options,
    default=type_options,
)

alert_filter = st.sidebar.selectbox(
    "Alert Status",
    ["All", "Alerts Only", "Non-alerts Only"],
    index=0,
)

filtered_df = df[
    (df["severity"].isin(severity_filter))
    & (df["type"].isin(type_filter))
].copy()

if alert_filter == "Alerts Only":
    filtered_df = filtered_df[filtered_df["adaptive_alert"] == 1].copy()
elif alert_filter == "Non-alerts Only":
    filtered_df = filtered_df[filtered_df["adaptive_alert"] == 0].copy()


# =========================================================
# Core metrics
# =========================================================

total_rows = len(filtered_df)
total_alerts = int(filtered_df["adaptive_alert"].sum())
total_frauds = int(filtered_df["isFraud"].sum())

true_positives = int(
    ((filtered_df["adaptive_alert"] == 1) & (filtered_df["isFraud"] == 1)).sum()
)

false_positives = int(
    ((filtered_df["adaptive_alert"] == 1) & (filtered_df["isFraud"] == 0)).sum()
)

missed_frauds = int(
    ((filtered_df["adaptive_alert"] == 0) & (filtered_df["isFraud"] == 1)).sum()
)

true_negatives = int(
    ((filtered_df["adaptive_alert"] == 0) & (filtered_df["isFraud"] == 0)).sum()
)

precision = true_positives / total_alerts if total_alerts else 0
recall = true_positives / total_frauds if total_frauds else 0
alert_rate = total_alerts / total_rows if total_rows else 0

selected_for_review = int(filtered_df["selected_for_review"].sum())

total_expected_benefit = float(
    filtered_df.loc[filtered_df["adaptive_alert"] == 1, "expected_benefit"].sum()
)

precision_at_k_df = calculate_precision_recall_at_k(filtered_df)


# =========================================================
# Tabs
# =========================================================

overview_tab, comparison_tab, queue_tab, audit_tab, gain_tab, curve_tab, precision_k_tab = st.tabs(
    [
        "Overview",
        "Static vs Adaptive",
        "Analyst Queue",
        "Audit Trail",
        "Adaptive Gain Analysis",
        "Operating Curve",
        "Precision@K",
    ]
)


# =========================================================
# Overview
# =========================================================

with overview_tab:
    st.subheader("Decision System KPIs")

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("Rows", f"{total_rows:,}")
    col2.metric("Alerts", f"{total_alerts:,}", delta=f"{alert_rate:.1%} alert rate")
    col3.metric("Frauds", f"{total_frauds:,}")
    col4.metric("Precision", f"{precision:.3f}")
    col5.metric("Recall", f"{recall:.3f}")

    st.metric("Total Expected Benefit from Alerts", format_money(total_expected_benefit))

    st.info(
        "This dashboard uses one selected simulation limit at a time. "
        "It is not showing all snapshots together."
    )

    st.subheader("Alert Funnel")

    funnel_df = pd.DataFrame(
        {
            "stage": [
                "Transactions",
                "Alerts",
                "Selected for Review",
                "Frauds Caught",
            ],
            "count": [
                total_rows,
                total_alerts,
                selected_for_review,
                true_positives,
            ],
        }
    )

    fig_funnel = px.funnel(
        funnel_df,
        x="count",
        y="stage",
        title="Fraud Decision Funnel",
    )

    st.plotly_chart(fig_funnel, use_container_width=True)

    st.subheader("Severity Breakdown")

    severity_df = (
        filtered_df[filtered_df["adaptive_alert"] == 1]
        .groupby("severity")
        .agg(
            alerts=("adaptive_alert", "sum"),
            confirmed_frauds=("isFraud", "sum"),
            avg_fraud_score=("fraud_score", "mean"),
            total_expected_benefit=("expected_benefit", "sum"),
        )
        .reset_index()
    )

    severity_df["avg_fraud_score"] = severity_df["avg_fraud_score"].round(4)

    st.dataframe(
        format_money_columns(severity_df, ["total_expected_benefit"]),
        use_container_width=True,
    )

    st.bar_chart(
        severity_df.set_index("severity")[["alerts", "confirmed_frauds"]],
        use_container_width=True,
    )

    st.subheader("Risk Score Distribution")

    score_df = filtered_df.copy()
    score_df["label"] = score_df["isFraud"].map({0: "Normal", 1: "Fraud"})

    fig_score = px.histogram(
        score_df,
        x="fraud_score",
        color="label",
        nbins=20,
        barmode="overlay",
        title="Fraud Score Distribution: Normal vs Fraud Transactions",
        labels={
            "fraud_score": "Fraud Score",
            "count": "Number of Transactions",
            "label": "Transaction Label",
        },
    )

    st.plotly_chart(fig_score, use_container_width=True)


# =========================================================
# Static vs Adaptive
# =========================================================

with comparison_tab:
    st.subheader("Static Threshold vs Adaptive Decision System")

    static_row = summary_df[summary_df["system"] == "static_threshold"].iloc[0]
    adaptive_row = summary_df[summary_df["system"] == "adaptive_decision_system"].iloc[0]

    cost_reduction = static_row["total_operational_cost"] - adaptive_row["total_operational_cost"]
    missed_loss_reduction = static_row["missed_fraud_cost"] - adaptive_row["missed_fraud_cost"]
    extra_frauds_caught = adaptive_row["frauds_caught"] - static_row["frauds_caught"]
    recall_improvement = adaptive_row["recall"] - static_row["recall"]
    precision_diff = adaptive_row["precision"] - static_row["precision"]

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric(
        "Cost Saved",
        format_money(cost_reduction),
        f"{cost_reduction / static_row['total_operational_cost']:.1%}",
    )

    col2.metric(
        "Missed Fraud Loss Reduced",
        format_money(missed_loss_reduction),
    )

    col3.metric(
        "Additional Frauds Caught",
        f"+{int(extra_frauds_caught)}",
    )

    col4.metric(
        "Recall",
        f"{adaptive_row['recall']:.1%}",
        f"+{recall_improvement:.1%}",
    )

    col5.metric(
        "Precision Change",
        f"{precision_diff:.3f}",
    )

    st.success(
        "The adaptive decision system catches more frauds and reduces missed-fraud cost "
        "compared with the static threshold baseline."
    )

    comparison_display = summary_df[
        [
            "system",
            "alerts",
            "frauds_caught",
            "missed_frauds",
            "false_positives",
            "precision",
            "recall",
            "frauds_per_100_alerts",
            "cost_per_fraud_caught",
            "missed_fraud_cost",
            "fraud_loss_prevented",
            "investigation_cost_total",
            "total_operational_cost",
            "cost_diff_vs_static",
        ]
    ].copy()

    money_cols = [
        "cost_per_fraud_caught",
        "missed_fraud_cost",
        "fraud_loss_prevented",
        "investigation_cost_total",
        "total_operational_cost",
        "cost_diff_vs_static",
    ]

    st.dataframe(
        format_money_columns(comparison_display, money_cols),
        use_container_width=True,
    )

    st.subheader("Confusion Matrix")

    confusion_df = pd.DataFrame(
        [
            {
                "Actual": "Fraud",
                "Predicted Alert": true_positives,
                "Predicted Non-Alert": missed_frauds,
            },
            {
                "Actual": "Normal",
                "Predicted Alert": false_positives,
                "Predicted Non-Alert": true_negatives,
            },
        ]
    )

    st.dataframe(confusion_df, use_container_width=True)

    heatmap_df = pd.DataFrame(
        [
            [true_positives, missed_frauds],
            [false_positives, true_negatives],
        ],
        index=["Actual Fraud", "Actual Normal"],
        columns=["Predicted Alert", "Predicted Non-Alert"],
    )

    fig_cm = px.imshow(
        heatmap_df,
        text_auto=True,
        title="Adaptive Decision Confusion Matrix",
        labels={
            "x": "Prediction",
            "y": "Actual Class",
            "color": "Count",
        },
    )

    st.plotly_chart(fig_cm, use_container_width=True)


# =========================================================
# Analyst Queue
# =========================================================

with queue_tab:
    st.subheader("Analyst Review Queue")

    queue_df = (
        filtered_df[filtered_df["selected_for_review"] == 1]
        .sort_values(["analyst_priority", "rank_score"], ascending=[True, False])
        .head(100)
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Rows in Queue", f"{len(queue_df):,}")
    col2.metric("Confirmed Frauds in Queue", f"{int(queue_df['isFraud'].sum()):,}")
    col3.metric(
        "Queue Precision",
        f"{(queue_df['isFraud'].sum() / len(queue_df)):.2%}" if len(queue_df) else "0.00%",
    )
    col4.metric(
        "Queue Value",
        format_money(float(queue_df["amount"].sum())) if len(queue_df) else "$0",
    )

    queue_columns = [
        "transaction_id",
        "step",
        "type",
        "amount",
        "fraud_score",
        "rank_score",
        "expected_benefit",
        "severity",
        "analyst_priority",
        "reason",
        "isFraud",
    ]

    st.dataframe(
        format_money_columns(
            queue_df[queue_columns],
            ["amount", "rank_score", "expected_benefit"],
        ),
        use_container_width=True,
    )

    st.info(
        "This tab shows only transactions selected for analyst review. "
        "It represents the actual analyst workload after ranking and capacity filtering."
    )


# =========================================================
# Audit Trail
# =========================================================

with audit_tab:
    st.subheader("Decision Audit Trail")

    total_static_alerts = int(filtered_df["static_alert"].sum())
    total_adaptive_alerts = int(filtered_df["adaptive_alert"].sum())
    total_overflow = int(filtered_df["budget_overflow"].sum())
    total_gain_frauds = int(filtered_df["adaptive_gain_fraud"].sum())

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Static Alerts", f"{total_static_alerts:,}")
    col2.metric("Adaptive Alerts", f"{total_adaptive_alerts:,}")
    col3.metric("Budget Overflow", f"{total_overflow:,}")
    col4.metric("Adaptive Gain Frauds", f"{total_gain_frauds:,}")

    st.subheader("Decision Outcome Breakdown")

    audit_summary = (
        filtered_df.groupby(
            [
                "static_alert",
                "adaptive_alert",
                "selected_for_review",
                "budget_overflow",
                "adaptive_gain_fraud",
            ]
        )
        .agg(
            transactions=("transaction_id", "count"),
            frauds=("isFraud", "sum"),
            total_amount=("amount", "sum"),
            avg_fraud_score=("fraud_score", "mean"),
        )
        .reset_index()
        .sort_values(["adaptive_gain_fraud", "frauds", "transactions"], ascending=False)
    )

    st.dataframe(
        format_money_columns(audit_summary, ["total_amount"]),
        use_container_width=True,
    )

    st.subheader("Audit Sample: Decisions Not Selected for Review")

    audit_df = (
        filtered_df[
            (filtered_df["adaptive_alert"] == 1)
            & (filtered_df["selected_for_review"] == 0)
        ]
        .sort_values(["budget_overflow", "rank_score"], ascending=[False, False])
        .head(250)
    )

    audit_columns = [
        "transaction_id",
        "step",
        "type",
        "amount",
        "fraud_score",
        "rank_score",
        "expected_benefit",
        "static_alert",
        "adaptive_alert",
        "adaptive_gain_fraud",
        "selected_for_review",
        "budget_overflow",
        "severity",
        "analyst_priority",
        "reason",
        "isFraud",
    ]

    st.dataframe(
        format_money_columns(
            audit_df[audit_columns],
            ["amount", "rank_score", "expected_benefit"],
        ),
        use_container_width=True,
    )


# =========================================================
# Adaptive Gain
# =========================================================

with gain_tab:
    st.subheader("Adaptive Gain Analysis")

    gain_df = filtered_df[filtered_df["adaptive_gain_fraud"] == 1].copy()

    static_caught = int(
        ((filtered_df["static_alert"] == 1) & (filtered_df["isFraud"] == 1)).sum()
    )

    adaptive_caught = int(
        ((filtered_df["adaptive_alert"] == 1) & (filtered_df["isFraud"] == 1)).sum()
    )

    additional_frauds = int(gain_df.shape[0])
    additional_loss_prevented = float(gain_df["amount"].sum())

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Static Frauds Caught", f"{static_caught:,}")
    col2.metric("Adaptive Frauds Caught", f"{adaptive_caught:,}")
    col3.metric("Additional Frauds", f"+{additional_frauds:,}")
    col4.metric("Additional Loss Prevented", format_money(additional_loss_prevented))

    st.success(
        "These are fraud cases missed by the static threshold but captured by the adaptive decision system."
    )

    if gain_df.empty:
        st.warning("No adaptive gain frauds found for the selected filters.")
    else:
        st.subheader("Additional Frauds by Severity")

        severity_gain = (
            gain_df.groupby("severity")
            .agg(
                additional_frauds=("transaction_id", "count"),
                total_amount=("amount", "sum"),
                avg_fraud_score=("fraud_score", "mean"),
            )
            .reset_index()
            .sort_values("additional_frauds", ascending=False)
        )

        st.dataframe(
            format_money_columns(severity_gain, ["total_amount"]),
            use_container_width=True,
        )

        st.bar_chart(
            severity_gain.set_index("severity")[["additional_frauds"]],
            use_container_width=True,
        )

        st.subheader("Additional Frauds by Transaction Type")

        type_gain = (
            gain_df.groupby("type")
            .agg(
                additional_frauds=("transaction_id", "count"),
                total_amount=("amount", "sum"),
                avg_fraud_score=("fraud_score", "mean"),
            )
            .reset_index()
            .sort_values("additional_frauds", ascending=False)
        )

        st.dataframe(
            format_money_columns(type_gain, ["total_amount"]),
            use_container_width=True,
        )

        st.bar_chart(
            type_gain.set_index("type")[["additional_frauds"]],
            use_container_width=True,
        )

        st.subheader("Adaptive Gain Transactions")

        gain_columns = [
            "transaction_id",
            "step",
            "type",
            "amount",
            "fraud_score",
            "rank_score",
            "severity",
            "static_alert",
            "adaptive_alert",
            "selected_for_review",
            "budget_overflow",
            "reason",
        ]

        st.dataframe(
            format_money_columns(
                gain_df[gain_columns].sort_values("rank_score", ascending=False),
                ["amount", "rank_score"],
            ),
            use_container_width=True,
        )


# =========================================================
# Operating Curve
# =========================================================

with curve_tab:
    st.subheader("Operating Curve")

    curve_display = curve_df[
        [
            "budget_multiplier",
            "alert_budget",
            "alerts",
            "frauds_caught",
            "missed_frauds",
            "precision",
            "recall",
            "frauds_per_100_alerts",
            "cost_per_fraud_caught",
            "total_operational_cost",
        ]
    ].copy()

    st.dataframe(
        format_money_columns(
            curve_display,
            ["cost_per_fraud_caught", "total_operational_cost"],
        ),
        use_container_width=True,
    )

    st.markdown("#### Recall and Precision by Alert Budget")
    st.line_chart(
        curve_df.set_index("budget_multiplier")[["recall", "precision"]],
        use_container_width=True,
    )

    st.markdown("#### Total Operational Cost by Alert Budget")
    st.line_chart(
        curve_df.set_index("budget_multiplier")[["total_operational_cost"]],
        use_container_width=True,
    )


# =========================================================
# Precision@K
# =========================================================

with precision_k_tab:
    st.subheader("Precision@K / Recall@K Operational Performance")

    # Table display
    display_precision_df = precision_at_k_df.copy()

    display_precision_df["precision_at_k_%"] = (
        display_precision_df["precision_at_k"] * 100
    ).map(lambda x: f"{x:.1f}%")

    display_precision_df["recall_at_k_%"] = (
        display_precision_df["recall_at_k"] * 100
    ).map(lambda x: f"{x:.1f}%")

    display_precision_df = display_precision_df.drop(
        columns=["precision_at_k", "recall_at_k"]
    )

    st.dataframe(display_precision_df, use_container_width=True)

    # Chart data (must remain numeric)
    chart_df = precision_at_k_df.copy()

    chart_df["precision_at_k_%"] = (
        chart_df["precision_at_k"] * 100
    ).round(1)

    chart_df["recall_at_k_%"] = (
        chart_df["recall_at_k"] * 100
    ).round(1)

    chart_df = chart_df.melt(
        id_vars="k",
        value_vars=["precision_at_k_%", "recall_at_k_%"],
        var_name="metric",
        value_name="percentage",
    )

    fig = px.line(
        chart_df,
        x="k",
        y="percentage",
        color="metric",
        markers=True,
        title="Precision@K and Recall@K",
    )

    fig.update_layout(
        xaxis_title="Top-K Analyst Queue",
        yaxis_title="Percentage",
        yaxis_range=[0, 100],
        legend_title_text="Metric",
    )

    st.plotly_chart(fig, use_container_width=True)

    best_k_row = precision_at_k_df.iloc[-1]

    st.info(
        f"At Top-{int(best_k_row['k'])}, the analyst queue finds "
        f"{int(best_k_row['frauds_found'])} frauds with "
        f"{best_k_row['precision_at_k'] * 100:.1f}% precision and "
        f"{best_k_row['recall_at_k'] * 100:.1f}% recall."
    )

    st.success(
        "As analyst capacity increases, recall improves because more frauds are reviewed. "
        "Precision naturally decreases because lower-ranked alerts enter the review queue."
    )

    st.info(
        "Data source: Thesis FastAPI decision export → SQLite tables → thesis decision analytics dashboard."
    )