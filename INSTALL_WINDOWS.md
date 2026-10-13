# Fixing Windows `WinError 32` after successful sequential import

The Main API simulation succeeded and six SQLite tables were written. The old
importer did not close its SQLite connection before replacing the database.

## Recover without re-running the 1k/3k/10k simulations

1. Stop every Streamlit terminal with **Ctrl+C**, close DB Browser for SQLite,
   VS Code SQLite database preview, and other programs that may hold the .db open.
2. Replace `scripts/import_from_thesis_api.py` and
   `dashboards/thesis_decision_dashboard.py` with the matching files in this ZIP;
   add `scripts/recover_pending_sqlite.py`.
3. In CMD:

```cmd
cd /d C:\Users\PATRI\fraud-decision-analytics
.venv\Scripts\activate.bat
python scripts\recover_pending_sqlite.py
```

The recovery script reads the existing `data/processed/fraud_investigation.pending.db`,
checks SQLite integrity, all six tables, and Static/Adaptive counts. It backs
up your previous `fraud_investigation.db` before replacing it. If Windows still
holds the file open, nothing is overwritten and you can retry after closing it.

4. If recovery succeeds:

```cmd
python -m streamlit run dashboards\thesis_decision_dashboard.py
```

## If the pending file is absent

With the Main API running in a separate CMD on your desired port (default 8002;
8003 also works), run the corrected importer:

```cmd
set "THESIS_API_BASE_URL=http://127.0.0.1:8003"
python scripts\import_from_thesis_api.py
```

**Do not type the `(.venv) C:\...>` prompt.** Type only CMD commands.

The Main Framework code is not changed by these files.
