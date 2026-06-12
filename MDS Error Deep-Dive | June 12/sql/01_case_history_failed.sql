-- ============================================================
-- Script 1: MDS Processing Failed cases (May 25 – Jun 12 2026)
-- Source:   fulfillment-dwh-production (curated SF tables)
-- Billing:  dh-global-sales-data-dev
-- ============================================================

SELECT
  ch.global_entity_id,
  ch.caseid,
  ch.createddate                    AS failed_at,
  c.grid__c                         AS grid_id,
  c.status                          AS case_status,
  c.type                            AS case_type,
  c.subject,
  a.backend_id__c                   AS vendor_id,
  a.name                            AS account_name
FROM `fulfillment-dwh-production.curated_data_shared_salesforce.case_history` ch
JOIN `fulfillment-dwh-production.curated_data_shared_salesforce.case` c
  ON c.id = ch.caseid
JOIN `fulfillment-dwh-production.curated_data_shared_salesforce.account` a
  ON a.id = c.accountid
WHERE ch.newvalue    = 'MDS Processing Failed'
  AND ch.createddate >= TIMESTAMP('2026-05-25')
  AND ch.createddate <  TIMESTAMP('2026-06-13')   -- inclusive of Jun 12
  AND c.type         = 'Menu Processing'
  AND c.grid__c      IS NOT NULL
ORDER BY ch.global_entity_id, ch.createddate DESC
