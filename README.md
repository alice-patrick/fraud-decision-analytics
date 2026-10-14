# Fraud Decision Analytics

**SQL · SQLite · Python · pandas · Streamlit · Plotly**  
*Data Analytics portfolio project | Fraud operations & KPI reporting*

An interactive reporting application that turns **simulated fraud-investigation decisions** into clear operational insights. It compares **Static vs Adaptive** investigation policies, tracks analyst workload and makes individual alert decisions auditable.

**My focus in this repository is analytics—not training a fraud model.** The separate [Decision-Centric Fraud Framework](https://github.com/alice-patrick/decision-centric-fraud-framework) generates the scores and sequential decisions; this project validates, stores and analyses its results.

## What this project demonstrates

- **SQL:** CTEs, `JOIN`/`LEFT JOIN`, conditional aggregation, `ROW_NUMBER()` and cumulative `SUM() OVER (...)` in the [reporting dashboard code](dashboards/thesis_decision_dashboard.py).
- **Data integration and quality:** importing FastAPI JSON results into SQLite; reconciling investigation counts, fraud labels, per-step capacity and KPI totals before reporting.
- **Business reporting:** monitoring investigated, suppressed and capacity-rejected alerts, fraud coverage, operational workload and **estimated** costs.
- **Interactive analysis:** comparing policies, filtering investigation records and reviewing recorded decisions by transaction and operational step.

### Example business insight

In one **10,000-transaction sequential simulation** (50 analyst reviews per step, 3-step suppression), the Adaptive policy detected **30 frauds vs 27** for Static, while investigating **349 vs 313** alerts. Its modeled operational cost was **€18,547.72 lower** in that scenario.

*Illustrative simulation result, not realized financial savings. Results depend on configuration; the current importer defaults to 30 reviews per step, so a fresh default run will produce different totals.*

## The dashboard

| View | What you can analyse |
| --- | --- |
| **Overview** | KPIs and side-by-side policy comparison, including investigation volume, fraud detection and estimated cost |
| **Analyst Capacity** | Alert outcomes, capacity by operational step, prioritised investigation queue and decision explanations |
| **Audit Trail** | Candidate-level decisions, retrospective labels, filters and transaction-type patterns |
| **Monitoring** | Trends across the reporting windows exported by the main simulation |

**Interface reference:** the screenshots below are from an **earlier Analytics UI revision**. The current dashboard uses the four views above and the updated sequential reporting database.

![Earlier Analytics dashboard overview](docs/images/decision_dashboard_overview.png)

![Earlier Analytics investigation queue](docs/images/analyst_queue.png)

## How the reporting pipeline works

```text
Main Fraud Framework (scoring + sequential simulation)
    → GET /simulation/sequential
    → Validate API results and import to SQLite
    → SQL queries (CTEs, JOINs, aggregations, window functions)
    → Streamlit dashboard
```

The importer writes six reporting tables: `seq_runs`, `seq_policy_summary`, `seq_decisions`, `seq_transaction_types`, `seq_operational_steps` and `seq_monitoring_windows`. **`seq_decisions` contains alert candidates, not every transaction**; overall transaction totals come from the original simulation summary.

Both policies are compared using the **same sequential simulation settings**. No separate batch-only metrics or arbitrary global investigation cap are introduced by the analytics dashboard.

## Run locally (Windows)

**Prerequisite:** The [main framework](https://github.com/alice-patrick/decision-centric-fraud-framework) must be configured with its model and PaySim data, and its FastAPI server must be running. From the **main project's** folder, start it in a separate terminal:

```cmd
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8002
```

From **this Analytics repository**, in a second terminal:

```cmd
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python scripts\import_from_thesis_api.py --api-url http://127.0.0.1:8002
python -m streamlit run dashboards\thesis_decision_dashboard.py
```

If the main API runs on **8003**, use `--api-url http://127.0.0.1:8003` in the import command instead. The dashboard reads the resulting local file at `data/processed/fraud_investigation.db`; you do not need the API running just to inspect an already imported report.

## Scope and limitations

PaySim is **synthetic data**. The replay is offline, fraud labels are used **retrospectively** for evaluation, and financial impacts are **modeled estimates**—not observed bank losses or actual savings. This is a research/portfolio reporting application, **not a production fraud-monitoring service**.

**Related project:** [Decision-Centric Fraud Framework — simulation and ML layer](https://github.com/alice-patrick/decision-centric-fraud-framework)
