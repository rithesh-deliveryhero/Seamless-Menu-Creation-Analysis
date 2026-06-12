-- ============================================================
-- Script 2: DLQ lookup for failed-case GRIDs
-- Source:   dh-global-sales-data.raw_vendor.mds_dead_letter_prod
-- Filter:   is_sccs_enabled = true  (SCCS submissions only)
--           sf_grid IN (<grid_list>)
-- ============================================================

WITH case_grids AS (
  -- Paste or inject grid list from Script 1 output here
  -- Example: SELECT 'HTUBI1' AS grid_id UNION ALL SELECT 'HTY3G3' ...
  SELECT grid_id FROM UNNEST([/* GRID_LIST */]) AS grid_id
),

dlq_raw AS (
  SELECT
    d.global_entity_id,
    CAST(d.vendor_id AS STRING)                                               AS vendor_id,
    d.attributes.system                                                        AS system,
    d.submission_timestamp,
    d.status_code,
    d.submission_id,
    d.image_path,
    (SELECT value FROM UNNEST(d.custom_data) WHERE key = 'sf_grid')           AS grid_id,
    (SELECT value FROM UNNEST(d.custom_data) WHERE key = 'is_sccs_enabled')   AS is_sccs_enabled,
    (SELECT value FROM UNNEST(d.custom_data) WHERE key = 'message')           AS error_message,
    (SELECT value FROM UNNEST(d.custom_data) WHERE key = 'file_id')           AS file_id,
    CONCAT(
      'https://console.cloud.google.com/storage/browser/',
      'dh-menu-digitalised-images-prod/',
      REGEXP_REPLACE(d.image_path, r'\.json$', '')
    )                                                                          AS gcs_url
  FROM `dh-global-sales-data.raw_vendor.mds_dead_letter_prod` d
  WHERE d.attributes.system IN ('salesforce_acquisition', 'sf_menu_onboarding')
    AND (SELECT value FROM UNNEST(d.custom_data) WHERE key = 'is_sccs_enabled') = 'true'
    AND (SELECT value FROM UNNEST(d.custom_data) WHERE key = 'sf_grid')
        IN (SELECT grid_id FROM case_grids)
),

-- Take the most recent DLQ entry per GRID (a vendor may have retried)
ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY grid_id ORDER BY submission_timestamp DESC) AS rn
  FROM dlq_raw
)

SELECT
  grid_id,
  global_entity_id,
  vendor_id,
  system,
  submission_timestamp,
  submission_id,
  status_code,

  -- Dashboard bucket mapping
  CASE
    WHEN status_code IN (3017, 3015) THEN 'Not a Menu Document'
    WHEN status_code = 3014          THEN 'MDS Technical Failure'
    WHEN status_code IN (3010, 3011) THEN 'File Not Supported'
    ELSE                                  'MDS Technical Failure'
  END                                                          AS dashboard_error_bucket,

  error_message,
  image_path,
  gcs_url,
  file_id
FROM ranked
WHERE rn = 1
ORDER BY global_entity_id, submission_timestamp DESC
