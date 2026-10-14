# Decision-Centric Fraud Detection Framework
**MSc Artificial Intelligence Dissertation | Python · Machine Learning · FastAPI · Streamlit**
An end-to-end research prototype that turns fraud-risk predictions into **prioritised investigation decisions** under limited analyst capacity. It compares **Static and Adaptive alert-selection policies** using fraud detection, analyst workload and simulated operational cost.
> **Research scope:** Synthetic PaySim transactions, offline chronological replay and simulation-based cost estimates. This is not a live banking or production fraud-monitoring system. The hosted demo is currently offline; screenshots and local run instructions are provided below.
## At a glance
| Evaluation | Static | Adaptive |
| --- | ---: | ---: |
| Investigated alerts | 313 | 349 |
| Frauds detected | 27 | **30** |
| Frauds missed | 41 | **38** |
| Precision | 8.6% | 8.6% |
| Recall | 39.7% | **44.1%** |
| Estimated operational cost | €1,745,391.01 | **€1,726,843.29** |
**Baseline configuration:** 10,000 transactions; 50 investigations per operational step; €10 assumed cost per investigation; Static threshold 0.50; Adaptive minimum risk threshold 0.30; Adaptive budget multiplier 1.40; repeat-alert suppression window of 3 operational steps.
In this scenario, Adaptive detected **3 additional frauds**, increased recall by **4.4 percentage points** and reduced estimated operational cost by **€18,547.72**, while investigating **36 additional alerts**. These are simulation results, not realised bank savings.
## Dashboard walkthrough
The Streamlit dashboard has five views, presented below in the same order as the interface.
### 1. Executive Summary
The Executive Summary compares Static and Adaptive outcomes under the selected operating configuration, including fraud coverage, investigation workload and estimated operational cost.
![Executive Summary dashboard](images/01_executive_summary.png)
#### Estimated cost impact
The cost-impact section explains the financial comparison within the Executive Summary.
**Estimated operational cost = investigation cost + estimated value of missed fraud.**
Investigation cost is the number of investigated alerts multiplied by the assumed review cost. The estimated value of missed fraud is the sum of the transaction amounts of missed fraud cases, used as a proxy for potential direct loss.
These figures support **comparative simulation** and do not represent observed banking losses.
![Estimated cost impact](images/01.1_cost_impact.png)
### 2. Sequential Workflow
Transactions are replayed chronologically. Candidate alerts pass through repeat-alert suppression, prioritisation and the analyst-capacity limit before entering the simulated investigation queue.
The view presents the seven-step process from transaction arrival to retrospective evaluation against known fraud labels.
![Sequential Workflow](images/02_sequential_workflow.png)
### 3. Analyst Capacity
This view separates three outcomes:
- **Investigated:** alerts selected for simulated investigation.
- **Suppressed:** repeat alerts filtered within the suppression window.
- **Capacity-rejected:** eligible alerts excluded because the operational step's investigation limit was reached.
| Alert outcome | Static | Adaptive |
| --- | ---: | ---: |
| Investigated | 313 | 349 |
| Suppressed | 13 | 21 |
| Capacity-rejected | 410 | 650 |
#### Static policy
![Analyst Capacity — Static](images/03_analyst_capacity%28static%29-%20Copy.png)
#### Adaptive policy
![Analyst Capacity — Adaptive](images/03.1_analyst_capacity%28adaptive%29.png)
An investigated alert is not automatically a confirmed fraud. In the baseline, 27 of the 313 Static investigations and 30 of the 349 Adaptive investigations corresponded to fraud in the retrospective evaluation labels.
### 4. Monitoring
The replay is divided into **10 consecutive reporting windows of 1,000 transactions**. These show changes in candidate alerts, investigations, missed fraud, recall and estimated operational cost.
Reporting windows are distinct from **operational steps**, where analyst capacity is applied and reset.
![Monitoring dashboard](images/04_monitoring.png)
### 5. Sensitivity Analysis
Seven operating parameters are examined one at a time: transaction volume, analyst capacity, investigation cost, suppression window, Adaptive budget multiplier, Static threshold and minimum Adaptive threshold.
Each experiment changes one parameter while holding the others fixed.
![Sensitivity Analysis experiments](images/05_sensitivity_analysis.png)
#### Sensitivity-analysis results
Across **45 reported comparisons**, Adaptive was preferred in **28**, Static in **11**, with **6 equivalent results**.
Preference is based on higher recall, or lower estimated cost when recall is tied. Policy performance therefore depends on the operating configuration.
![Sensitivity Analysis baseline and results](images/05.1_sensitivity_analysis%28KPIS%29.png)
## How the system works
1. **Transaction replay:** PaySim transactions are processed in chronological step order.
2. **Fraud-risk scoring:** Feature engineering and preprocessing feed a Logistic Regression model with probability calibration.
3. **Alert selection:** Static threshold rules or Adaptive eligibility rules identify candidate alerts.
4. **Repeat-alert suppression:** Repeated alerts are filtered within the configured suppression window.
5. **Prioritisation:** Eligible alerts are ordered using the selected policy; Adaptive uses cost-aware expected-benefit ranking.
6. **Analyst capacity:** The per-step investigation limit determines which alerts enter the queue and which are capacity-rejected.
7. **Evaluation:** Investigation decisions are compared retrospectively with fraud labels to calculate precision, recall, missed fraud, workload and estimated cost.
The ML pipeline uses scikit-learn `ColumnTransformer`, scaling, one-hot encoding, Logistic Regression and probability calibration. A **FastAPI backend** serves the decision and evaluation functionality to the **Streamlit dashboard**.
## Technology stack
**Python · pandas · NumPy · scikit-learn · FastAPI · Uvicorn · Streamlit · Matplotlib · pytest · Git/GitHub**
## Run locally
From the repository root on Windows (Command Prompt):
```cmd
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
python -m pip install streamlit
```
Place the PaySim dataset at `data/raw/AIML Dataset.csv` if it is not already present. Start the backend:
```cmd
python -m uvicorn app.api.main:app --reload --port 8002
```
In a **second terminal**, activate `.venv` again and start the UX dashboard:
```cmd
.venv\Scripts\activate.bat
python -m streamlit run app/ux_evaluation_dash.py
```
Open [http://localhost:8501](http://localhost:8501). API documentation is available at [http://127.0.0.1:8002/docs](http://127.0.0.1:8002/docs) while the backend is running.
## Testing and limitations
Earlier project documentation reported **88 passing automated tests** covering decision logic, analyst capacity, sequential simulation, API behaviour and dashboard calculations. Verify the current revision in your local environment:
```cmd
python -m pytest
```
**Limitations:** Synthetic rather than real bank data; offline replay rather than live streaming; simplified analyst-capacity and suppression assumptions; retrospective fraud labels; and hypothetical operational costs.
## Main contribution
The key contribution is the **decision layer between ML predictions and investigation actions**. It makes alert eligibility, prioritisation, workload constraints and operational trade-offs inspectable, rather than treating the classifier score as the final investigation decision.
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
