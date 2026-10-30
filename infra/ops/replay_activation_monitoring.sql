-- ADR-0032 activation monitoring (REPLAY_OUTCOME_AUDIT §17.10, §19). Read only.
--
--   psql "$DSN" -v since="'2026-10-30T00:00:00Z'" -f infra/ops/replay_activation_monitoring.sql
--
-- `since` is the activation deploy time (UTC). Every check row must report 0 violations; the
-- last query is the basis-code distribution (informational). Pair it with
-- `python -m querycure.ops verify-integrity` (rebuild check) and the worker logs
-- (`ReportContractError`, `finalize_failed`). Nothing here writes: one READ ONLY transaction.

BEGIN READ ONLY;

WITH replay_reports AS (
    SELECT r.id AS run_id, r.status, r.outcome AS run_outcome, r.finalized_at,
           ir.builder_version, ir.md_renderer_version, ir.report_schema_version,
           ir.outcome AS report_outcome, ir.final_status,
           convert_from(j.content, 'UTF8')::jsonb AS report,
           convert_from(ma.content, 'UTF8')::jsonb AS manifest,
           (SELECT e.payload FROM investigation_events e
             WHERE e.run_id = r.id AND e.type = 'run.concluded') AS concluded,
           (SELECT e.payload ? 'source_snapshot' FROM investigation_events e
             WHERE e.run_id = r.id AND e.type = 'replay.status_changed'
               AND e.payload->>'from' IS NULL ORDER BY e.seq LIMIT 1) AS marked,
           (SELECT count(*) FROM run_artifacts ra WHERE ra.run_id = r.id
               AND ra.role IN ('input.replay_source.manifest',
                               'input.replay_source.report_json')) AS snapshot_links
    FROM investigation_runs r
    JOIN investigation_reports ir ON ir.run_id = r.id
    JOIN artifacts j ON j.id = ir.report_json_artifact_id
    JOIN replay_manifests m ON m.run_id = r.id
    JOIN artifacts ma ON ma.id = m.manifest_artifact_id
    WHERE r.kind = 'experiment_replay' AND r.finalized_at >= CAST(:since AS TIMESTAMPTZ)
),
all_reports AS (
    SELECT ir.run_id, ir.builder_version, ir.md_renderer_version, ir.report_schema_version,
           convert_from(j.content, 'UTF8')::jsonb AS report,
           convert_from(ma.content, 'UTF8')::jsonb -> 'report' AS manifest_report
    FROM investigation_reports ir
    JOIN investigation_runs r ON r.id = ir.run_id
    JOIN artifacts j ON j.id = ir.report_json_artifact_id
    JOIN replay_manifests m ON m.run_id = ir.run_id
    JOIN artifacts ma ON ma.id = m.manifest_artifact_id
    WHERE r.finalized_at >= CAST(:since AS TIMESTAMPTZ)
),
checks AS (
    -- 1. A verified replay must rest on the reproduced-source basis and the source's own
    --    recommendation (provenance), and the report must agree with the sealed basis.
    SELECT '1_verified_replay_without_reproduced_source_basis' AS check_name, run_id
    FROM replay_reports
    WHERE report_outcome = 'verified_recommendation'
      AND (concluded->'replay_basis'->>'code' IS DISTINCT FROM 'reproduced_source_recommendation'
           OR report->'recommendation'->>'origin' IS DISTINCT FROM 'source_run'
           OR report->'recommendation'->>'source_run_id' IS NULL
           OR report->'replay_result'->'source'->>'run_id'
              IS DISTINCT FROM report->'recommendation'->>'source_run_id'
           OR snapshot_links <> 2)
    UNION ALL
    -- 2. Outcome and basis disagree anywhere (run row, report row, report JSON, manifest).
    SELECT '2_outcome_contradicts_basis_or_layers', run_id FROM replay_reports
    WHERE run_outcome IS DISTINCT FROM report_outcome
       OR report->>'outcome' IS DISTINCT FROM report_outcome
       OR manifest->>'outcome' IS DISTINCT FROM report_outcome
       OR (concluded ? 'replay_basis'
           AND report->'replay_result'->'basis' IS DISTINCT FROM concluded->'replay_basis')
       OR (concluded->'replay_basis'->>'code' = 'reproduced_source_recommendation')
          IS DISTINCT FROM (report_outcome = 'verified_recommendation')
          AND concluded ? 'replay_basis'
    UNION ALL
    -- 3. A snapshot-era replay (marker or links) sealed with the legacy builder.
    SELECT '3_snapshot_replay_sealed_with_v1', run_id FROM replay_reports
    WHERE builder_version = 'report-builder@1' AND (marked OR snapshot_links > 0)
    UNION ALL
    -- 4. A completed snapshot-era replay without a sealed basis.
    SELECT '4_completed_snapshot_replay_without_basis', run_id FROM replay_reports
    WHERE final_status = 'completed' AND (marked OR snapshot_links > 0)
      AND NOT (concluded ? 'replay_basis')
    UNION ALL
    -- 5. A legacy-contract replay sealed with anything but report-builder@1, or with a basis.
    SELECT '5_legacy_replay_not_sealed_as_legacy', run_id FROM replay_reports
    WHERE NOT coalesce(marked, false) AND snapshot_links = 0
      AND (builder_version <> 'report-builder@1' OR concluded ? 'replay_basis')
    UNION ALL
    -- 6. Marker and links disagree (a damaged snapshot record).
    SELECT '6_snapshot_marker_or_links_missing', run_id FROM replay_reports
    WHERE coalesce(marked, false) <> (snapshot_links = 2)
    UNION ALL
    -- 7. Builder, renderer and schema are not one released contract, or the layers disagree.
    SELECT '7_report_contract_mismatch', run_id FROM all_reports
    WHERE (builder_version, md_renderer_version, report_schema_version) NOT IN
              (('report-builder@1', 'report-md@1', 1), ('report-builder@2', 'report-md@2', 2))
       OR report->>'builder_version' IS DISTINCT FROM builder_version
       OR (report->>'schema_version')::int IS DISTINCT FROM report_schema_version
       OR manifest_report->>'builder_version' IS DISTINCT FROM builder_version
       OR manifest_report->>'md_renderer_version' IS DISTINCT FROM md_renderer_version
       OR (manifest_report->>'report_schema_version')::int
          IS DISTINCT FROM report_schema_version
    UNION ALL
    -- 8. A new non-replay report sealed with the legacy builder (version skew).
    SELECT '8_new_ordinary_report_sealed_with_v1', ir.run_id
    FROM investigation_reports ir JOIN investigation_runs r ON r.id = ir.run_id
    WHERE r.kind <> 'experiment_replay' AND ir.builder_version = 'report-builder@1'
      AND r.finalized_at >= CAST(:since AS TIMESTAMPTZ)
    UNION ALL
    -- 9. A terminal run that was never sealed (finalization failed and fell back).
    SELECT '9_terminal_run_without_seal', r.id FROM investigation_runs r
    WHERE r.status IN ('completed', 'failed', 'cancelled') AND r.finalized_at IS NULL
      AND r.updated_at >= CAST(:since AS TIMESTAMPTZ)
    UNION ALL
    -- 10. Replay attempts that ended in an internal error (a refused seal dead-letters here).
    SELECT '10_replay_attempt_internal_error', a.replay_run_id FROM replay_attempts a
    WHERE a.kind = 'experiment' AND a.failure_code = 'internal_error'
      AND a.finished_at >= CAST(:since AS TIMESTAMPTZ)
)
SELECT c.check_name, count(x.run_id) AS violations,
       coalesce(string_agg(x.run_id::text, ' ' ORDER BY x.run_id::text)
                FILTER (WHERE x.run_id IS NOT NULL), '') AS run_ids
FROM (VALUES ('1_verified_replay_without_reproduced_source_basis'),
             ('2_outcome_contradicts_basis_or_layers'), ('3_snapshot_replay_sealed_with_v1'),
             ('4_completed_snapshot_replay_without_basis'),
             ('5_legacy_replay_not_sealed_as_legacy'), ('6_snapshot_marker_or_links_missing'),
             ('7_report_contract_mismatch'), ('8_new_ordinary_report_sealed_with_v1'),
             ('9_terminal_run_without_seal'), ('10_replay_attempt_internal_error')
     ) AS c(check_name)
LEFT JOIN checks x ON x.check_name = c.check_name
GROUP BY c.check_name ORDER BY c.check_name;

-- Distribution (informational): basis codes of replays sealed since activation, per day.
SELECT date_trunc('day', r.finalized_at) AS day,
       coalesce(e.payload->'replay_basis'->>'code', '(legacy, no basis)') AS basis,
       ir.builder_version, count(*)
FROM investigation_runs r
JOIN investigation_reports ir ON ir.run_id = r.id
LEFT JOIN investigation_events e ON e.run_id = r.id AND e.type = 'run.concluded'
WHERE r.kind = 'experiment_replay' AND r.finalized_at >= CAST(:since AS TIMESTAMPTZ)
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

ROLLBACK;
