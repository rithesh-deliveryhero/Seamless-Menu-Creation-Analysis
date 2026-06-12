# MDS Error Deep-Dive | June 12

## Objective
Root-cause analysis of MDS Processing Failed cases across all management entities,
covering the period **25 May – 12 June 2026**.

For each failed case the pipeline surfaces:
- GRID ID and submission metadata
- DLQ error code and full error message
- Bucketed error label (as shown on the MDS funnel dashboard)
- GCS public URL to the uploaded file image
- For resolution/size errors (status 3014): actual file dimensions and size from the GCS bucket

---

## Approach

### Step 1 — Identify failed cases (Script 1: `sql/01_case_history_failed.sql`)
Query `curated_data_shared_salesforce.case_history` for rows where
`newvalue = 'MDS Processing Failed'` within the analysis window.
Join to `curated_data_shared_salesforce.case` to resolve `grid__c` (GRID ID)
and `backend_id__c` (vendor ID) via the linked account.

### Step 2 — DLQ lookup (Script 2: `sql/02_dlq_lookup.sql`)
For each GRID, query `dh-global-sales-data.raw_vendor.mds_dead_letter_prod`
filtering on:
- `attributes.system IN ('salesforce_acquisition', 'sf_menu_onboarding')`
- `custom_data[key='is_sccs_enabled'] = 'true'`
- `custom_data[key='sf_grid'] = <GRID>`

Extract: `submission_id`, `status_code`, `image_path`, and the `message` field
from `custom_data`.

### Step 3 — Error code mapping
| Status Code | Raw Message Pattern | Dashboard Bucket |
|---|---|---|
| 3017 | "not recognized as a menu by the language model" | Not a Menu Document |
| 3015 | "does not look like a restaurant menu" | Not a Menu Document |
| 3014 | "Image resolution is too large" | MDS Technical Failure |
| 3014 | "Image file size too large" | MDS Technical Failure |
| 4xx  | File format not supported | File Not Supported |
| Other | — | MDS Technical Failure |

### Step 4 — GCS file inspection (Script 3: `scripts/03_gcs_inspect.sh`)
For all 3014 errors, run `gsutil ls -l` against the GCS path:
```
gs://dh-menu-digitalised-images-prod/<image_path_without_json>/
```
Record file name, size (bytes/MB), and format.

### Step 5 — Output
Consolidated CSV at `output/mds_error_deep_dive_jun12.csv` with one row per case.

---

## GCS Bucket URL Format
```
https://console.cloud.google.com/storage/browser/dh-menu-digitalised-images-prod/<image_path_without_extension>
```
Example:
```
https://console.cloud.google.com/storage/browser/dh-menu-digitalised-images-prod/sf_menu_onboarding/HF_EG_20260611T170635_1101885
```

---

## Key Findings (June 12 pilot — 5 cases)
| GRID | Entity | Error Code | Root Cause |
|---|---|---|---|
| HTUBI1 | FP_PH | 3014 | Resolution 232M pixels (limit: 30M) — raw uncompressed image |
| HTY3G3 | GV_IT | 3017 | Non-menu content submitted (storefront/logo) |
| HTUC7T | GV_PL | 3017 | Non-menu content submitted |
| HTUYXT | HF_EG | 3014 | Resolution 30.9M pixels (just 3% over limit) — high-DPI PDF |
| HTUYEF | TB_JO | 3017 | Non-menu content submitted |

**Status 3014 = pixel count cap (not file size cap).**
The HF_EG file was only 2.84 MB on disk but its rendered resolution exceeded 30,000,000 px.

---

## Files
```
sql/
  01_case_history_failed.sql   — Case history query (Step 1)
  02_dlq_lookup.sql            — DLQ lookup query (Step 2)
scripts/
  03_gcs_inspect.sh            — GCS file size inspection (Step 4)
  04_run_full_pipeline.sh      — End-to-end orchestration
output/
  mds_error_deep_dive_jun12.csv
```
