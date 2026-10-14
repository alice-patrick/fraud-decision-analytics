# Fraud Operations Analytics

**SQL · Python · SQLite · pandas · Streamlit · Plotly**  
*Data Analyst portfolio project | Fraud patterns, operational KPIs and reporting*

A business-focused dashboard that analyses **synthetic payment transactions** and **simulated fraud-investigation results**. It turns raw reporting data into clear answers about transaction activity, where fraud occurs, investigation workload and changes in detection performance.

The focus of this repository is **data analytics and business reporting**, not model training. Investigation outcomes are imported from the separate [Decision-Centric Fraud Framework](https://github.com/alice-patrick/decision-centric-fraud-framework).

## Key findings from a 10,000-transaction sample

- **Fraud detection:** 313 investigations identified **27 of 68** labelled fraud cases (**39.7% detection rate**), while reviewing **3.1%** of transactions in the Static baseline.
- **Transaction patterns:** `PAYMENT` accounted for the most transactions (**5,465**), but `TRANSFER` had the highest observed fraud rate (**3.58%**, or 33 of 921 transactions).
- **Operational workload:** **410** eligible alerts were not investigated because capacity was full in four review steps, while **37** review slots went unused in other steps. Unused slots could not be transferred between steps in this simulation.

These are observations from one offline synthetic-data scenario, **not real-world banking performance**.

## Dashboard

### 1. Overview — the business snapshot

A concise view of transaction volume, fraud rate, investigations and detection performance. An optional comparison shows the **Static baseline** alongside the **Adaptive alternative**, without making model mechanics the focus.

![Fraud Operations Analytics — business overview and investigation strategy comparison](images/01_overview.png)

### 2. Transaction Patterns — where fraud is concentrated

Explores transaction volume and the difference between **fraud counts** and **fraud rates** across payment types. Includes a downloadable transaction summary.

![Transaction volumes, fraud counts, fraud rates and business insight](images/02_transaction_patterns.png)

### 3. Investigation Performance — where capacity is constrained

Shows review capacity by operational step and highlights where alerts were left uninvestigated. The emphasis is on understanding workload and identifying operational bottlenecks.

![Investigation capacity, alerts not reviewed and workload by step](images/03_investigation_performance.png)

### 4. Performance Monitoring — how results change

Tracks fraud detection rates across **consecutive transaction groups**, not calendar periods. Insights include the actual fraud counts behind percentages to avoid misleading interpretations of small samples.

![Fraud detection rates across reporting groups with business insight](images/04_monitoring.png)

<details>
<summary><strong>Additional view: Filterable investigation records</strong></summary>

The dashboard also provides transaction-type, investigation-outcome and actual-label filters, plus a CSV export of the selected alert records.

![Filterable alert records and CSV export](images/04.1_monitoring.png)

</details>

## Skills demonstrated

| Area | Application in this project |
| --- | --- |
| **SQL & SQLite** | CTEs, `JOIN` / `LEFT JOIN`, grouped aggregations, `ROW_NUMBER()` and cumulative `SUM() OVER (...)` for reporting |
| **Data preparation & validation** | Python/pandas import of structured API results, consistency checks and reusable reporting tables |
| **Business analysis** | Fraud-rate comparisons, investigation workload, capacity utilisation and evidence-based insights |
| **Data visualisation** | Streamlit dashboard, Plotly charts, interactive filters and CSV exports |

The report queries and dashboard are in [`dashboards/thesis_decision_dashboard.py`](dashboards/thesis_decision_dashboard.py). The validated API-to-SQLite import is in [`scripts/import_from_thesis_api.py`](scripts/import_from_thesis_api.py).

## Data flow

`Main Framework (sequential simulation)` → `FastAPI JSON` → `Validated Python import` → `SQLite / SQL analysis` → `Streamlit dashboard`

The [Main Framework](https://github.com/alice-patrick/decision-centric-fraud-framework) generates fraud scores and investigation decisions. **This Analytics repository reports and examines those existing outcomes**; it does not retrain models or recalculate fraud decisions.

## Run locally

**Windows / Command Prompt** — from this Analytics repository:

```cmd
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m streamlit run dashboards\thesis_decision_dashboard.py
```

Open **http://localhost:8501**. If `data/processed/fraud_investigation.db` already contains the imported sequential results, **you do not need to start the Main API** to view the dashboard.

**First-time setup (when the SQLite report database is missing):** start the Main Framework API in its own project folder, with its model and PaySim data configured:

```cmd
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8002
```

Then, from this Analytics repository, import the results before starting Streamlit:

```cmd
.venv\Scripts\activate.bat
python scripts\import_from_thesis_api.py --api-url http://127.0.0.1:8002
python -m streamlit run dashboards\thesis_decision_dashboard.py
```

If your Main API runs on port **8003**, replace `8002` with `8003` in the import command. The imported SQLite database is a local generated file and is not included in this repository.

## Scope

The data comes from **PaySim (synthetic financial transactions)** and an **offline sequential simulation**. Fraud labels are used retrospectively to evaluate results; cost estimates depend on simulation assumptions. This project is for **analysis and portfolio demonstration**, not live fraud monitoring.
