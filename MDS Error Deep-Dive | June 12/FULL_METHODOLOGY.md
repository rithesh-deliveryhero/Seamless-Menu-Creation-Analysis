# MDS Error Deep-Dive — Full Methodology & Runbook
**Project:** Seamless Menu Creation Analysis  
**GitHub:** https://github.com/rithesh-deliveryhero/Seamless-Menu-Creation-Analysis  
**Folder:** `MDS Error Deep-Dive | June 12`  
**Author:** Rithesh Nanda · Assisted by Claude Sonnet 4.6

---

## 0. Context & Objective

This project analyses why MDS (Menu Digitisation Service) rejects restaurant menu submissions. The MDS pipeline processes files submitted via Salesforce onboarding cases. When a file is rejected it lands in a DLQ (Dead Letter Queue). We used AI image classification (claude-sonnet-4-6) to determine whether each rejection was a genuine pipeline failure or whether the vendor submitted the wrong type of file altogether.

**Key finding:** ~32% of MDS errors are false negatives (genuine menus incorrectly rejected). ~29% are copy-menu instructions — vendors submitting a GRID/Backend ID instead of an actual menu.

---

## 1. Core Data Sources

### BigQuery Tables

| Table | Purpose |
|---|---|
| `fulfillment-dwh-production.curated_data_shared_vendor.fact_vso_vrm_mds_menu_funnel` | Main fact table — one row per onboarded vendor, all funnel flags |
| `fulfillment-dwh-production.curated_data_shared_vendor.agg_vso_vrm_mds_menu_funnel` | Aggregated stage counts by period/entity |
| `fulfillment-dwh-production.curated_data_shared_vendor.agg_vso_vrm_mds_menu_funnel_mds_error` | MDS error reason breakdown |
| `fulfillment-dwh-production.curated_data_shared_vendor.agg_vso_vrm_mds_scc_item_failures` | SCC item-level failure reasons |
| `fulfillment-dwh-production.curated_data_shared_vendor.agg_vso_vrm_mds_menu_funnel_sf_error` | SF-level error breakdown (category/product) |
| `fulfillment-dwh-production.curated_data_shared_salesforce.case` | SF cases — key fields: `grid__c`, `type`, `status`, `accountid` |
| `fulfillment-dwh-production.curated_data_shared_salesforce.case_history` | SF case history — `newvalue = 'MDS Processing Failed'` |
| `fulfillment-dwh-production.curated_data_shared_salesforce.account` | SF accounts — 401 columns; key: `grid__c`, `backend_id__c`, `shared_menu__c`, `type`, `clone_from__c` |
| `dh-global-sales-data.raw_vendor.mds_dead_letter_prod` | MDS DLQ — failed submissions with `custom_data` array |
| `dh-global-sales-data.raw_vendor.mds_digitalised_menu_prod` | MDS success table — `digitalised_images` nested array |
| `dh-central-salesforce-tech.dh_salesforce_scc_draft_menu.dh_salesforce_scc_job_info` | SCC job results — `items[]` with `reason` field |

### BigQuery Config
- **Billing project:** `dh-global-sales-data-dev`
- **Production project:** `fulfillment-dwh-production` (read-only via billing project)
- **Raw data project:** `dh-global-sales-data`
- **SCC job project:** `dh-central-salesforce-tech`

---

## 2. MDS Funnel Structure

### Key Fact Table Flags
```sql
is_funnel_total_onboarded          -- entry to funnel
is_funnel_menu_processing_case_present
is_funnel_no_menu_processing_case
is_funnel_automated_shared_menu    -- has_shared_menu=TRUE AND is_cloned_account=TRUE
is_funnel_cloned_or_manual_shared_menu  -- is_cloned_account=TRUE, has_shared_menu=FALSE
is_funnel_franchise_winback
is_funnel_mds_processed            -- reached MDS pipeline
is_funnel_mds_not_received
is_funnel_sccs_wrong_filetype_drop
is_funnel_applicable_for_digitization
is_funnel_mds_success
is_funnel_mds_errors               -- ← primary filter for this analysis
is_funnel_menu_file_not_present_nb
is_funnel_catalog_created / failed
is_funnel_category_created / failed
is_funnel_product_created / failed
is_funnel_drafts_created
is_funnel_retained_in_sf
is_funnel_drafts_not_retained
```

### Dashboard Bucket → DLQ Status Code Mapping
| Dashboard Bucket | DLQ Status Codes |
|---|---|
| Not a Menu Document | 3015 (salesforce_acquisition), 3017 (sf_menu_onboarding) |
| Lesser than 3 Items | 3013 |
| File Not Supported | 4032 (CSV/XLS too large), 3020 (PDF too large) |
| MDS Technical Failure | 3014 (resolution), 4027 (publishing), 4016 (language), 99 (internal) |
| Price Not Detected | 4007 |

### Status Code Meanings
- **3015:** "File does not look like a restaurant menu" — `salesforce_acquisition` system
- **3017:** "File not recognised as menu by LLM" — `sf_menu_onboarding` system
- **3014:** Pixel count exceeds 30M pixel limit (NOT file size in bytes)
- **3013:** Fewer than 3 items extracted
- **4032:** CSV/XLS input too large (files NOT stored in GCS image bucket)

---

## 3. SCCS Pipeline Details

### Custom Data Keys in DLQ/Results Tables
The `mds_dead_letter_prod` and `mds_digitalised_menu_prod` tables have a `custom_data ARRAY<STRUCT<key STRING, value STRING>>` field.

**Key fields to extract:**
```sql
(SELECT value FROM UNNEST(custom_data) WHERE key = 'sf_grid')           AS grid_id
(SELECT value FROM UNNEST(custom_data) WHERE key = 'is_sccs_enabled')   AS is_sccs_enabled
(SELECT value FROM UNNEST(custom_data) WHERE key = 'is_sccs_file_type') AS is_sccs_file_type
(SELECT value FROM UNNEST(custom_data) WHERE key = 'message')            AS error_message
(SELECT value FROM UNNEST(custom_data) WHERE key = 'target')             AS target
```

**Important:** The GRID ID key in custom_data is `sf_grid`, NOT `grid`. Use `sf_grid` always.

**System values:**
- `sf_menu_onboarding` — SCCS pipeline; is_sccs_enabled=true here
- `salesforce_acquisition` — older pipeline; is_sccs_enabled often false

**Vendor ID format differences:**
- `sf_menu_onboarding`: vendor_id = `IT949940` (entity prefix + number, no underscore)
- `salesforce_acquisition`: vendor_id = `949940` (number only, no prefix)
- Philippines (FP_PH): uses short hash codes like `cbv3`, `ndfu`

### GCS Image Bucket
- **Bucket:** `gs://dh-menu-digitalised-images-prod/`
- **Path format:** `{system}/{GEID}_{TIMESTAMP}_{VENDOR_ID}/image_1.{ext}`
- **Example:** `gs://dh-menu-digitalised-images-prod/sf_menu_onboarding/HF_EG_20260611T170635_1101885/image_1.pdf`
- **Console URL format:** `https://console.cloud.google.com/storage/browser/dh-menu-digitalised-images-prod/{system}/{GEID}_{TIMESTAMP}_{VENDOR_ID}`
- **File types found:** PDF, PNG, JPG (CSV/XLS are NOT stored here)
- **Check file:** `gsutil ls -l "gs://dh-menu-digitalised-images-prod/{path}/"` (always use trailing slash, auto-detects filename)

---

## 4. Getting the 726 MDS Error GRIDs (May 2026)

```sql
SELECT
  grid_id, global_entity_id, sub_entity, management_entity,
  vendor_id, onboarded_date, mds_error AS dashboard_error_bucket
FROM `fulfillment-dwh-production.curated_data_shared_vendor.fact_vso_vrm_mds_menu_funnel`
WHERE onboard_month   = '2026-05-01'
  AND account_source  = 'Non SSU'
  AND is_seamless_market = TRUE
  AND is_funnel_mds_errors = TRUE
ORDER BY global_entity_id, grid_id
```
This returns exactly 726 rows matching the dashboard (All Entities, Non SSU, Seamless, May 2026).

---

## 5. DLQ Lookup for All 726 GRIDs

```sql
WITH dlq_raw AS (
  SELECT
    (SELECT value FROM UNNEST(d.custom_data) WHERE key = 'sf_grid') AS grid_id,
    d.global_entity_id, CAST(d.vendor_id AS STRING) AS vendor_id,
    d.attributes.system AS system,
    d.submission_timestamp, d.status_code, d.submission_id,
    d.image_path,
    (SELECT value FROM UNNEST(d.custom_data) WHERE key = 'is_sccs_enabled') AS is_sccs_enabled,
    (SELECT value FROM UNNEST(d.custom_data) WHERE key = 'message') AS error_message,
    ROW_NUMBER() OVER (
      PARTITION BY (SELECT value FROM UNNEST(d.custom_data) WHERE key = 'sf_grid')
      ORDER BY d.submission_timestamp DESC
    ) AS rn
  FROM `dh-global-sales-data.raw_vendor.mds_dead_letter_prod` d
  WHERE d.attributes.system IN ('salesforce_acquisition','sf_menu_onboarding')
    AND (SELECT value FROM UNNEST(d.custom_data) WHERE key = 'sf_grid') IN (<<IN_CLAUSE>>)
)
SELECT grid_id, global_entity_id, vendor_id, system,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', submission_timestamp) AS submission_timestamp,
  status_code, submission_id, image_path, is_sccs_enabled, error_message
FROM dlq_raw WHERE rn = 1
```

All 726 GRIDs matched in the DLQ for May 2026.

---

## 6. AI Classification Pipeline

### Model Used
**claude-sonnet-4-6** (upgraded from Haiku after first pass)

### Classification Prompt (v3 — final version)
```
RULE 1 — BLANK/EMPTY → E, label "Blank Submission"
RULE 2 — BACKEND ID / GRID COPY REF → B
  Text "Backend ID", "GRID ID", vendor code + copy/refer/same-as instructions.
  QR code linking to DH brand (Glovo/Talabat/HungerStation/Yemeksepeti/Pedidosya/Foodpanda/Foodora/eFood) → B
RULE 3 — WEBSITE SCREENSHOT → E "Website Screenshot — invalid submission"
  Even if menu items visible. Exception: purely a DH-brand URL (no screenshot) → B
RULE 4 — ID / GOVERNMENT DOCS → E "Identity Document — irrelevant"
RULE 5 — LEGAL / CONTRACT → E "Legal/Contract Document — irrelevant"
RULE 6 — LOGO ONLY → C
RULE 7 — FOOD PHOTO (no prices) → D
RULE 8 — GENUINE MENU (dish name + price, physical/digital document) → A
RULE 9 — OTHER → E

Return JSON: {category_code, category_label, has_dish_and_price, has_copy_instructions_or_grid,
              is_website_screenshot, is_blank, confidence, brief_observation}
```

### Reclassification Rules (second pass, E cases only)
After the first pass, only E-classified cases were re-examined with these additions:
- **Website screenshots WITH item names + prices + categories** → reclassify to A (genuine menu)
- **Files with "sync from", "sync to", or 4-char alphanumeric account IDs** → reclassify to B (copy instruction)

### Item Count Prompt (for "Lesser than 3 Items" bucket)
Separate prompt asking Claude to count visible dish/product names and list up to 8.
If ≥3 visible → `false_negative_item_count = True`

### File Handling
- PDF → render first page at 100-120 DPI via `fitz` (pymupdf), send as JPEG base64
- PNG/JPG → send directly as base64
- XLSX/XLS → extract text content via `openpyxl`/`xlrd`, send as text prompt (not vision)
- CSV → not in GCS bucket, flag as N/A

### Processing
- 5 workers (ThreadPoolExecutor) for rate limit safety with Sonnet
- ~$4-5 total cost for 624 image files with Sonnet

---

## 7. Final Classification Results (May 2026, 726 GRIDs)

| Code | Category | Count | % | Description |
|---|---|---|---|---|
| A | Restaurant Menu (FN) | 176 | 24.2% | Genuine menus incorrectly rejected |
| B | Copy Menu Instructions | 210 | 28.9% | GRID ref / Backend ID / sync instructions / DH-brand QR |
| C | Logo / Branding | 35 | 4.8% | Logo only |
| D | Food Photo | 5 | 0.7% | Food photo, no prices |
| E | Irrelevant / Invalid | 214 | 29.5% | Blank, website screenshot, ID card, legal doc |
| N/A | Failed Excel/CSV | 82 | 11.3% | CSV/XLS not in GCS |

**False Negative Estimate:**  
137 (Restaurant Menu A) + 95% of 102 (Excel/CSV) = **~234 estimated FN (32.2%)**

**53 cases reclassified from E:**
- 20 → A (website screenshots with genuine menu items+prices)
- 33 → B (sync from/to instructions or vendor ID references)

---

## 8. GCS File Inspection (Status 3014 — Resolution Errors)

```bash
gsutil ls -l "gs://dh-menu-digitalised-images-prod/{path}/"
```

**Critical insight:** Status 3014 error message says "tot X max 30000000" — this is a **PIXEL COUNT** not file size in bytes. A 2.84 MB PDF can still fail if its rendered resolution exceeds 30,000,000 pixels (~5,477 × 5,477).

---

## 9. SCC Job Table Analysis

```sql
SELECT
  j.grid, j.type, j.status, j.timestamp,
  it.name AS item_name, it.reason
FROM `dh-central-salesforce-tech.dh_salesforce_scc_draft_menu.dh_salesforce_scc_job_info` j
CROSS JOIN UNNEST(j.items) AS it
WHERE j.grid IN (<<GRID_LIST>>)
  AND it.reason IS NOT NULL AND it.reason != ''
```

**Job types:** `gms-categories`, `gms-products`, `gms-product-options`  
**Cascade rule:** If `gms-categories` job has a failed item, all products in that category also fail.

---

## 10. MDS Extraction Excel — Menu Unnesting

For the HungerStation Drafts Not Retained analysis, we queried `mds_digitalised_menu_prod` and unnested the `digitalised_images` array:

```sql
WITH latest AS (
  SELECT
    (SELECT value FROM UNNEST(custom_data) WHERE key = 'sf_grid') AS grid_id,
    global_entity_id, CAST(vendor_id AS STRING) AS vendor_id,
    FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', submission_timestamp) AS submission_timestamp,
    digitalised_images,
    ROW_NUMBER() OVER (
      PARTITION BY (SELECT value FROM UNNEST(custom_data) WHERE key = 'sf_grid')
      ORDER BY submission_timestamp DESC
    ) AS rn
  FROM `dh-global-sales-data.raw_vendor.mds_digitalised_menu_prod`
  WHERE global_entity_id = 'HF_EG'
    AND CAST(vendor_id AS STRING) IN (<<VENDOR_IDS>>)
    AND EXISTS (SELECT 1 FROM UNNEST(custom_data) WHERE key = 'is_sccs_enabled' AND value = 'true')
    AND EXISTS (SELECT 1 FROM UNNEST(custom_data) WHERE key = 'is_sccs_file_type' AND value = 'true')
)
SELECT * FROM latest WHERE rn = 1
```

**Option groups format in output:** `[Group Name (M/O)] Sel1 / ArabicName - Price | Sel2 - Price  ||  [Group2] ...`

**Validation:** Count of `digitalised_images` items should equal `successful_products + failed_products` from fact table.

---

## 11. Case History Query (Live Data)

```sql
SELECT
  ch.global_entity_id, ch.caseid, ch.createddate AS failed_at,
  c.grid__c AS grid_id, c.status AS case_status, c.type,
  a.backend_id__c AS vendor_id, a.name AS account_name
FROM `fulfillment-dwh-production.curated_data_shared_salesforce.case_history` ch
JOIN `fulfillment-dwh-production.curated_data_shared_salesforce.case` c ON c.id = ch.caseid
JOIN `fulfillment-dwh-production.curated_data_shared_salesforce.account` a ON a.id = c.accountid
WHERE ch.newvalue = 'MDS Processing Failed'
  AND ch.createddate >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
  AND c.type = 'Menu Processing'
  AND c.grid__c IS NOT NULL
ORDER BY ch.global_entity_id, ch.createddate DESC
```

---

## 12. MDS Error Rate Weekly Analysis

```sql
SELECT
  global_entity_id,
  mds_error,
  SUM(total_mds_errors) AS error_count
FROM `fulfillment-dwh-production.curated_data_shared_vendor.agg_vso_vrm_mds_menu_funnel_mds_error`
WHERE time_grain = 'Week'
  AND account_source = 'Non SSU'
  AND onboard_week IN ('2026-05-18','2026-05-25','2026-06-01','2026-06-08')
GROUP BY 1, 2
HAVING SUM(total_mds_errors) > 0
ORDER BY global_entity_id, error_count DESC
```

**Priority thresholds used:** Rate ≥20% = High Rate; Errors ≥20 = High Volume.  
**Top urgent regions (May 2026):** GV_UA (51%), GV_IT (38%), HF_EG (32%), GV_PL (29%), FP_PH (25%), TB_JO (21%)

---

## 13. Key Salesforce Account Fields

**Field availability in BQ curated table (`curated_data_shared_salesforce.account`):**
- `grid__c` — GRID ID ✅
- `backend_id__c` — Vendor ID in MDS system ✅
- `shared_menu__c` — Shared menu reference (if set → shared menu case) ✅
- `clone_from__c` — Source account ID ✅
- `clone_from_branch_grid__c` — Source GRID ✅
- `type` — Account type: `Branch - Main`, `Branch - Virtual Restaurant`, etc. ✅
- `parentid` — Parent account in franchise hierarchy ✅
- `integration_partner__c` — **NOT in BQ curated table** ❌ (use SF export directly)
- `targeted_integrations_for_restaurant__c` — **NOT in BQ curated table** ❌

**`is_cloned_account` flag in fact table:** Empirically determined to be set when SF `type` IN (`Branch - Main`, `Branch - Virtual Restaurant`) AND the account has a parent or clone relationship. Not directly queryable from SF account — it's computed in the DBT model.

---

## 14. Shared Menu Bucket Analysis

**Automated Shared Menus:** `is_funnel_automated_shared_menu = TRUE`  
→ Triggered when `has_shared_menu = TRUE` AND `is_cloned_account = TRUE`

**Manual/Cloned Shared Menus:** `is_funnel_cloned_or_manual_shared_menu = TRUE`  
→ Triggered when `is_cloned_account = TRUE` AND `has_shared_menu = FALSE`

**Key finding (May 2026, HS + TB):**
- HungerStation: 1,309 Manual/Cloned (0 Automated) — all in HS_SA, no FEx
- Talabat: 800 Automated + 260 Manual/Cloned — Automated is 57.7% Franchise Extension (POS accounts)

---

## 15. PDF Generation

### Libraries
```python
pip3 install pymupdf anthropic openpyxl Pillow reportlab --break-system-packages
```

### Entity-Specific PDFs Structure
Each of the 4 entity PDFs (Glovo, Pandora, Talabat, HungerStation) uses:
- **Section 1 — Copy Menu Instructions:** Big % callout + breakdown by entity/country
- **Section 2 — Invalid Submission Breakdown:** Orange % callout + E sub-category table + C/D table
- **Section 3 — Valid Menus Incorrectly Rejected:** Summary paragraph only, no case pages
- **Case pages:** B (copy) first → C/D/E (invalid) — A/N/A cases NOT shown in case pages

### Entity Groupings
```python
ENTITY_GROUPS = {
    'Glovo':        lambda r: r['global_entity_id'].startswith('GV_'),
    'Pandora':      lambda r: r['global_entity_id'].startswith(('FP_','FO_','YS_','MJM_','DJ_','NP_')),
    'Talabat':      lambda r: r['global_entity_id'].startswith('TB_') or r['global_entity_id']=='HF_EG',
    'HungerStation':lambda r: r['global_entity_id'].startswith('HS_'),
}
```

### PDF v4 Summary Table
- Table 1: AI Classification (no Code column; rows: Restaurant Menu, Failed Excel/CSV, Copy Instructions, Logo, Food Photo, Irrelevant)
- FN line: `137 (Restaurant Menu confirmed FN) + 95% of 102 (Failed Excel/CSV) = ~234 (32.2%)`
- No Table 2 on cover page

---

## 16. Labelled Dataset

**Location:** `output/Dataset/`

| Folder | Files | Label |
|---|---|---|
| `Failed_Cases/` | 468 | B + C + D + E + N/A |
| `Good_Cases/` | 176 | A — genuine menus |
| `Mixed_Dataset/` | 644 | shuffled (seed=42) |
| `MDS_Error_Labelled_Dataset.xlsx` | 726 rows | 4 sheets + Legend |

**Excel columns:** Filename, GEID, Country, GRID ID, File Format, Error Bucket (Dashboard), DLQ Error Code, MDS Original Label, AI Ground Truth Label, AI Category Code, Has Dish & Price, Has Copy/GRID Ref, Reclassified?, Split (Failed/Good), AI Observation

**Reclassified rows** highlighted in light purple (53 total: 20→A, 33→B from original E).

---

## 17. Scripts Location

All scripts saved in GitHub repo under `MDS Error Deep-Dive | June 12/`:

| Script | Purpose |
|---|---|
| `sql/01_case_history_failed.sql` | Live case_history query for MDS Processing Failed |
| `sql/02_dlq_lookup.sql` | DLQ lookup with sf_grid and SCCS filters |
| `scripts/03_gcs_inspect.sh` | GCS bucket file inspection (gsutil) |
| `scripts/04_run_full_pipeline.sh` | End-to-end orchestration |
| `scripts/05_build_report_pdf.py` | PDF generation (reportlab + pymupdf + Anthropic) |

---

## 18. Quick Reference — Common Pitfalls

1. **`is_sccs_file_type` NOT in DLQ records** — only `is_sccs_enabled` is reliable in the DLQ. Don't filter by both.
2. **GCS path is a folder, not a file** — always use trailing slash and `gsutil ls` first to detect filename/extension.
3. **Status 3014 = pixel count cap (30M pixels), NOT file size**
4. **`sf_grid` is the GRID key in custom_data** — NOT `grid`
5. **Vendor ID format varies by system** — SF `backend_id__c` has underscores; DLQ `sf_menu_onboarding` removes underscore; `salesforce_acquisition` uses numeric-only
6. **agg table `time_grain` is capitalized** — `'Month'` not `'month'`, `'Week'` not `'week'`
7. **For Pedidosya (PY_AR)** — use `account_source_curated = 'Non SSU'` not `account_source`, due to SSU misclassification
8. **`integration_partner__c` not in BQ** — must come from SF export. No equivalent in curated tables.
9. **N/A (Excel/CSV) files not in GCS** — they're in Salesforce ContentDocument/ContentVersion, not the image bucket
10. **When counting items in "Lesser than 3 Items"** — MDS counted at extraction time; Claude counts from the image; discrepancy = false negative candidate

---

## 19. Cost Reference

| Task | Model | Files | Cost |
|---|---|---|---|
| 25-image pilot | claude-haiku-4-5 | 25 | ~$0.033 |
| Full 624-file classification | claude-sonnet-4-6 | 624 | ~$4-5 |
| E-case reclassification (267 files) | claude-sonnet-4-6 | 267 | ~$2 |

---

## 20. GitHub Repository Structure

```
Seamless-Menu-Creation-Analysis/
└── MDS Error Deep-Dive | June 12/
    ├── README.md                                    ← Methodology overview
    ├── FULL_METHODOLOGY.md                          ← This document
    ├── sql/
    │   ├── 01_case_history_failed.sql
    │   └── 02_dlq_lookup.sql
    ├── scripts/
    │   ├── 03_gcs_inspect.sh
    │   ├── 04_run_full_pipeline.sh
    │   └── 05_build_report_pdf.py
    └── output/
        ├── MDS_Error_May2026_Full_Review_v4.pdf    ← Full 726-case PDF (8/page)
        ├── MDS_Error_May2026_Full_Analysis_v4.xlsx ← Full Excel with all columns
        ├── MDS_Error_May2026_Glovo.pdf             ← Sales rep PDF — Glovo
        ├── MDS_Error_May2026_Pandora.pdf           ← Sales rep PDF — Pandora
        ├── MDS_Error_May2026_Talabat.pdf           ← Sales rep PDF — Talabat
        ├── MDS_Error_May2026_HungerStation.pdf     ← Sales rep PDF — HungerStation
        ├── submitted_files/                         ← 624 files named by Submission ID
        ├── downloaded_Files/                        ← 20 Salesforce-downloaded Excel/CSV files
        └── Dataset/
            ├── Failed_Cases/      (468 files — B/C/D/E/N/A)
            ├── Good_Cases/        (176 files — A, genuine menus)
            ├── Mixed_Dataset/     (644 files — shuffled seed=42)
            └── MDS_Error_Labelled_Dataset.xlsx
```
