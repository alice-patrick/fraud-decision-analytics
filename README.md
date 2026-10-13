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

