# Screenshot capture guide — Fraud Decision Analytics

All screenshots should use the **same imported 10,000-transaction run** and a consistent browser width / zoom (e.g. 80–90% browser zoom if KPI cards are cut off).

The app has **four** tabs. The Sankey is in **Overview → Explore Transaction Flow**, not Audit Trail. Use the sidebar **Decision policy** selector to capture both policies; the Overview comparison table already compares Static and Adaptive regardless of the selected policy.

## Recommended paired filenames

| Dashboard section | Static | Adaptive |
| --- | --- | --- |
| Overview KPI cards + comparison | `01_overview_static.png` | `02_overview_adaptive.png` |
| Overview → Transaction Flow | `03_transaction_flow_static.png` | `04_transaction_flow_adaptive.png` |
| Analyst Capacity → Queue / decision explanation | `05_investigation_queue_static.png` | `06_investigation_queue_adaptive.png` |
| Audit Trail → candidate audit | `07_audit_static.png` | `08_audit_adaptive.png` |
| Monitoring → trend chart | `09_monitoring_static.png` | `10_monitoring_adaptive.png` |

Save to **`docs/images/`**. Two Static screenshots (`03_transaction_flow_static.png` and `05_investigation_queue_static.png`) are included, using your own current screenshots. Replace those files only if you take clearer current captures.

**Capture checklist:**

- Show the selected policy name in the heading or sidebar where possible.
- For Overview, ensure all four KPI cards and the policy comparison are visible. Avoid cropping the right side.
- For Transaction Flow, expand **Explore Transaction Flow** first. Choose **All transactions** for both policies; close any open dropdown before capture.
- For queues, show an actual selected transaction plus **Alert Decision Explanation** where possible.
- For Monitoring, close the metric dropdown so that the plotted trend is visible.
- Keep 10,000 transactions selected on all views. Do **not** claim the Static and Adaptive screenshots represent different dataset runs.

## After capturing Adaptive screenshots

Add the exact image filenames from this table to `docs/images/`, then include the paired image links near the corresponding README sections. Only link images after the files exist; this avoids broken GitHub previews. For example:

```md
**Static**  
![Transaction flow — Static](docs/images/03_transaction_flow_static.png)

**Adaptive**  
![Transaction flow — Adaptive](docs/images/04_transaction_flow_adaptive.png)
```

For a recruiter-oriented README, keep the strongest 2–4 screenshots visible and put additional images in expandable details if needed.
