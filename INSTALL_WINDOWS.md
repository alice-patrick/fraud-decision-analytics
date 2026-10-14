# Apply the Fraud Decision Analytics UI update

This package **only updates the Streamlit dashboard and README**, adds a screenshot guide, and includes two screenshots supplied by you. It does **not** touch the Main Framework, SQLite, importer, or API settings.

1. In the Analytics CMD, stop Streamlit with **Ctrl+C**. You may leave the Main API running.
2. Back up `dashboards/thesis_decision_dashboard.py` and `README.md` from `C:\Users\PATRI\fraud-decision-analytics`.
3. Unzip the package **into** `C:\Users\PATRI\fraud-decision-analytics`, allowing replacement of `dashboards\thesis_decision_dashboard.py` and `README.md`.
4. Start the dashboard again:

```cmd
cd /d C:\Users\PATRI\fraud-decision-analytics
.venv\Scripts\activate.bat
python -m streamlit run dashboards\thesis_decision_dashboard.py
```

5. Open **Overview** and expand **Explore Transaction Flow · Static**. Switch the sidebar policy to **Adaptive** and verify the corresponding chart. **Audit Trail** should now show only the filtered decision audit and its CSV export.

No new API import, model training, or SQLite recovery is required.

When the screenshots are complete, stage the dashboard, README and genuine image files for GitHub:

```cmd
git add dashboards/thesis_decision_dashboard.py README.md docs/SCREENSHOT_GUIDE.md docs/images/03_transaction_flow_static.png docs/images/05_investigation_queue_static.png
git commit -m "Move transaction flow to Overview and refresh Analytics documentation"
git push origin main
```

If you add further Adaptive screenshots, include them in `git add` after the files actually exist.
