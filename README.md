Fraud Decision Analytics
SQL · SQLite · Python · pandas · Streamlit · Plotly | Data Analytics Portfolio Project
A reporting and investigation-analytics application for exploring fraud-alert decisions under limited analyst capacity. It transforms the outputs of a decision simulation into SQL-based operational reports, making it easier to compare investigation policies, examine alert outcomes, monitor workload and audit individual decisions.
The focus of this repository is data analysis and reporting, not model development. It is the analytics companion to the Decision-Centric Fraud Detection Framework, which generates the transaction scores and simulation decisions.
Scope: Synthetic PaySim transaction data and offline simulation results. This is a portfolio/research prototype, not a live fraud-detection service. Financial impact values are modeled estimates, not realized savings.

What this project demonstrates
- SQL analysis: Common Table Expressions (CTEs), JOIN / LEFT JOIN, conditional aggregations, grouped reporting and window functions (ROW_NUMBER, running SUM OVER).
- Data integration: Importing structured JSON results from a FastAPI endpoint into normalized-purpose SQLite reporting tables.
- Data validation: Reconciling transaction-level decisions with policy summaries, fraud counts, capacity limits and cost metrics before reporting them.
- Operational reporting: Comparing Static and Adaptive policies using investigations, detected and missed fraud, precision, recall, suppression, capacity rejection and estimated cost.
- Interactive analysis: Filtering by scenario, policy, operational step and transaction attributes; examining decision explanations and monitoring trends.
Reporting workflow
Main Fraud Framework
  PaySim sample → model scoring → Static / Adaptive sequential simulation
                        |
                        v
              GET /simulation/sequential
                        |
                        v
Analytics importer (scripts/import_from_thesis_api.py)
  Validate response → write six SQLite reporting tables
                        |
                        v
SQLite (data/processed/fraud_investigation.db)
                        |
                        v
Parameterized SQL queries (CTEs, JOINs, aggregations, windows)
                        |
                        v
Streamlit reporting dashboard (dashboards/thesis_decision_dashboard.py)
Separation of responsibilities: The Main Framework performs scoring, prioritization, repeat-alert suppression and analyst-capacity simulation. This repository does not recalculate model probabilities or rerun those decisions. It analyzes the recorded outputs. Both policies are taken from the same sequential API response for each imported scenario; batch-only and sequential metrics are not mixed.
Dashboard walkthrough
The current application has four views, with a shared sidebar to select a transaction count and Static or Adaptive policy. The comparison remains visible for both policies.
View	Question answered	What it includes
Overview	How did the policies perform?	KPI cards, Static vs Adaptive comparison, frauds found/missed, precision, recall and modeled cost
Analyst Capacity	Where did the investigation workload go?	Candidate alerts, investigated/suppressed/capacity-rejected outcomes, capacity by operational step, prioritized queue and explanations
Audit Trail	Why was a candidate investigated or not?	Transaction-level decisions, filters, retrospective fraud labels and a transaction-type flow
Monitoring	How do the results change across the replay?	Reporting-window metrics and operational trends from the Main simulation


The dashboard exposes its actual SQL reporting queries in an expandable methodology section. The sidebar changes which imported results are reported; it does not retrain the model or change the saved simulation.
Screenshots from the earlier Analytics UI
The image files below are already committed under docs/images/ and illustrate the original Analytics reporting concept. They are archival screenshots, not captures of the latest sequential-dashboard layout or its current KPI values. Updated screenshots should replace them after the current UI is captured.
Analytics overview (earlier UI)

Static vs Adaptive reporting (earlier UI)

Investigation queue (earlier UI)

Decision audit (earlier UI)

SQLite data model
The importer creates six reporting tables, each associated with a simulation run and (where applicable) its policy:
Table	Reporting purpose
seq_runs	Transaction count, API parameters, source endpoint and import metadata
seq_policy_summary	One Static and one Adaptive sequential KPI summary per run
seq_decisions	Candidate-alert records, priorities and actual sequential decision outcomes
seq_transaction_types	Transaction-type aggregates over all evaluated transactions, including transactions that did not become alert candidates
seq_operational_steps	Workload, accepted investigations, suppression and unused capacity per chronological step
seq_monitoring_windows	Original monitoring-window metrics exported by the Main Framework


Important distinction: seq_decisions contains candidate alerts rather than every PaySim transaction. Total-transaction counts and all-transaction type summaries therefore come from their respective API summary tables, not from COUNT(*) over seq_decisions.
The SQL queries use bound parameters for selected runs/policies rather than string-interpolated filters. The reports use CTEs to aggregate candidate decisions and JOINs to compare those aggregates with the original API summaries. Window functions rank candidates within operational steps and calculate cumulative investigation workload.
KPI definitions
Metric	Meaning
Candidate alerts	Transactions flagged by the selected decision policy before sequential capacity/suppression outcomes
Investigated	Candidate alerts accepted after suppression and the per-step capacity check
Suppressed	Repeat-entity candidate alerts filtered by the configured suppression window
Capacity-rejected	Non-suppressed candidates that could not be investigated because the step's slots were full
Precision	Detected frauds / investigated alerts
Recall	Detected frauds / total frauds in the evaluated synthetic transactions
Modeled operational cost	Assumed investigation cost + estimated missed-fraud cost


Fraud labels in the audit and performance reports are retrospective PaySim ground truth, not information assumed to be available to investigators when a decision was made.
Run locally (Windows)
Prerequisite: Run the Main Framework API with its model and sample dataset available. The analytics app cannot generate simulation outputs by itself.
1. Install the Analytics dependencies in this repository:
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
2. In a separate terminal, start the Main API from the Main Framework repository:
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8002
If 8002 is already in use, you may run the Main API on 8003 instead. Leave this terminal open. Verify the endpoint at http://127.0.0.1:8002/docs (or :8003/docs). The relevant endpoint is /simulation/sequential, not /sequential or /decision_export.
3. Import sequential results from the Analytics repository:
python scripts\import_from_thesis_api.py
If the Main API is running on 8003, use:
python scripts\import_from_thesis_api.py --api-url http://127.0.0.1:8003
By default, the importer requests 1,000, 3,000 and 10,000 transactions. To use particular sizes:
python scripts\import_from_thesis_api.py --limits 1000 10000
Configuration matters: The checked-in importer currently uses alert_budget_per_step = 30 in BASE_PARAMS. If comparing the Analytics results to a Main UX scenario that uses 50 investigations per step, change that value to 50 in scripts/import_from_thesis_api.py before importing, and ensure the remaining parameters also match. Different capacity and suppression settings can legitimately produce different KPI values. The dashboard displays the parameters of the imported run.
4. Start the Analytics dashboard:
python -m streamlit run dashboards\thesis_decision_dashboard.py
Open the local Streamlit address shown in the terminal (typically http://localhost:8501). Once imported, the SQLite reports can be viewed without keeping the Main API running; the API is required again only when refreshing the dataset.
Validation and tests
The importer checks the returned data before saving it, including the consistency of candidate counts, selected alerts, detected frauds, per-step capacity and policy summaries. The dashboard also checks reconciliation between SQL-derived audit counts and the imported API KPIs; inconsistent reporting results are not presented as valid comparisons.
Regression tests and frozen sequential-response fixtures are available in tests/. Run them with the Analytics environment activated:
python -m unittest discover -s tests -v
Tests include SQL query behavior, API-to-SQL reconciliations, edge cases and Streamlit UI checks. The SQLite database is locally generated and ignored by Git; it is not shipped as a live production data source.
Troubleshooting
- Missing seq_* tables: The current database was built with an earlier importer. Run scripts/import_from_thesis_api.py with the Main API active.
- Connection refused (WinError 10061): The Main API is not running at the supplied address. Start it in a separate terminal, then retry.
- 404 from /sequential: The correct endpoint includes the router prefix: /simulation/sequential.
- Port already in use (WinError 10048): Run the Main API on 8003 and pass --api-url http://127.0.0.1:8003 to the importer.
- SQLite locked (WinError 32): Close Streamlit, SQLite viewers and other processes using the database before importing. See [Windows recovery instructions](INSTALL_WINDOWS.md) for older pending imports.
- Screenshots not rendering: Image paths are relative to this README. Existing images live under [`docs/images/`](docs/images/), not images/.
Project boundaries
This repository is intentionally scoped to analytics, SQL reporting and auditability. The predictive model, original decision-engine logic, experimental methodology and Main UX application belong to the companion Decision-Centric Fraud Detection Framework.
The project uses synthetic transactions, simulated investigation decisions and hypothetical costs; it does not process real bank customer transactions or demonstrate production deployment.
