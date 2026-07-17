from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .engine import brief_markdown, build_record, convert_legacy_record
from .exporter import export_repository
from .importer import ImportPipelineError, ImportService
from .repository import CatalystRepository, RepositoryError
from .query_studio import QueryStudio
from .handoff import create_handoff, read_handoff, validate_handoff
from .public_api import ApiRegistry, openapi_document, serve
from .validation import RecordValidationError, validate_record
from .workspaces import AccessDenied, WorkspaceService
from .connectors import ConnectorError, ConnectorService, normalize_connector_definition
from .analysis_artifacts import AnalysisArtifactError, AnalysisArtifactService
from .operations import OperationalError, OperationalService


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("input JSON must contain an object")
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Validate records and operate a persistent Catalyst Data repository")
    subparsers = result.add_subparsers(dest="command")

    brief = subparsers.add_parser("brief", help="build a canonical record and Markdown brief")
    brief.add_argument("input", type=Path)
    brief.add_argument("output", type=Path)

    validate = subparsers.add_parser("validate", help="validate a canonical catalyst-data-record/1.0 file")
    validate.add_argument("input", type=Path)

    upgrade = subparsers.add_parser("upgrade", help="upgrade a v1.0.x record to catalyst-data-record/1.0")
    upgrade.add_argument("input", type=Path)
    upgrade.add_argument("output", type=Path)

    init = subparsers.add_parser("init", help="initialize a SQLite repository and apply all migrations")
    init.add_argument("database", type=Path)

    migrate = subparsers.add_parser("migrate", help="apply ordered migrations")
    migrate.add_argument("database", type=Path)
    migrate.add_argument("--target", type=int)

    rollback = subparsers.add_parser("rollback", help="reverse one or more migrations")
    rollback.add_argument("database", type=Path)
    rollback.add_argument("--steps", type=int, default=1)

    status = subparsers.add_parser("status", help="show repository health and migration status")
    status.add_argument("database", type=Path)
    status.add_argument("--json", action="store_true")

    import_command = subparsers.add_parser("import", help="import canonical or authoring records from JSON or CSV")
    import_command.add_argument("database", type=Path)
    import_command.add_argument("input", type=Path)
    import_command.add_argument("--format", choices=("auto", "json", "csv"), default="auto")
    import_command.add_argument("--dry-run", action="store_true")
    import_command.add_argument("--continue-on-error", action="store_true")
    import_command.add_argument("--non-atomic", action="store_true", help="commit valid rows while reporting invalid rows")
    import_command.add_argument("--summary", type=Path, help="write the import summary as JSON")

    export = subparsers.add_parser("export", help="export repository records to JSON or CSV")
    export.add_argument("database", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--format", choices=("json", "csv"), default="json")

    inspect = subparsers.add_parser("inspect", help="inspect repository statistics or one record")
    inspect.add_argument("database", type=Path)
    inspect.add_argument("--record-id")

    review = subparsers.add_parser("review", help="show the measurement review queue")
    review.add_argument("database", type=Path)
    review.add_argument("--status", choices=("missing source", "needs evidence", "reviewable with caution", "reviewable"))
    review.add_argument("--limit", type=int, default=100)

    sources = subparsers.add_parser("sources", help="show immutable source version history")
    sources.add_argument("database", type=Path)
    sources.add_argument("--source-id")
    sources.add_argument("--limit", type=int, default=100)

    provenance = subparsers.add_parser("provenance", help="show append-only provenance events for a record")
    provenance.add_argument("database", type=Path)
    provenance.add_argument("record_id")
    provenance.add_argument("--limit", type=int, default=200)

    evidence = subparsers.add_parser("evidence", help="show a record evidence chain, revisions, gaps, and provenance")
    evidence.add_argument("database", type=Path)
    evidence.add_argument("record_id")


    indicators = subparsers.add_parser("indicators", help="show the governed indicator registry")
    indicators.add_argument("database", type=Path)
    indicators.add_argument("--indicator-id")
    indicators.add_argument("--limit", type=int, default=100)

    methods = subparsers.add_parser("methods", help="show immutable methodology version history")
    methods.add_argument("database", type=Path)
    methods.add_argument("--methodology-id")
    methods.add_argument("--limit", type=int, default=100)

    units = subparsers.add_parser("units", help="show governed unit definitions")
    units.add_argument("database", type=Path)
    units.add_argument("--unit-id")
    units.add_argument("--limit", type=int, default=100)

    convert = subparsers.add_parser("convert", help="convert a value between compatible governed units")
    convert.add_argument("database", type=Path)
    convert.add_argument("value", type=float)
    convert.add_argument("from_unit")
    convert.add_argument("to_unit")

    compare = subparsers.add_parser("compare", help="compare two records using indicator governance rules")
    compare.add_argument("database", type=Path)
    compare.add_argument("left_record_id")
    compare.add_argument("right_record_id")

    governance_events = subparsers.add_parser("governance-events", help="show indicator governance history")
    governance_events.add_argument("database", type=Path)
    governance_events.add_argument("indicator_id")
    governance_events.add_argument("--limit", type=int, default=200)


    questions = subparsers.add_parser("questions", help="show research and decision questions")
    questions.add_argument("database", type=Path)
    questions.add_argument("--question-id")
    questions.add_argument("--limit", type=int, default=100)

    instruments = subparsers.add_parser("instruments", help="show collection instruments and current versions")
    instruments.add_argument("database", type=Path)
    instruments.add_argument("--instrument-id")
    instruments.add_argument("--limit", type=int, default=100)

    datasets = subparsers.add_parser("datasets", help="show datasets and current versions")
    datasets.add_argument("database", type=Path)
    datasets.add_argument("--dataset-id")
    datasets.add_argument("--limit", type=int, default=100)

    observations = subparsers.add_parser("observations", help="show governed observations")
    observations.add_argument("database", type=Path)
    observations.add_argument("--record-id")
    observations.add_argument("--quality-status", choices=("valid","missing","censored","outlier","imputed","rejected"))
    observations.add_argument("--limit", type=int, default=200)

    lineage = subparsers.add_parser("lineage", help="show question-to-observation lineage for a record")
    lineage.add_argument("database", type=Path)
    lineage.add_argument("record_id")

    reviews = subparsers.add_parser("reviews", help="show the governed review workflow queue")
    reviews.add_argument("database", type=Path)
    reviews.add_argument("--state", choices=("draft","submitted","in-review","changes-requested","approved","rejected","superseded","archived"))
    reviews.add_argument("--reviewer")
    reviews.add_argument("--limit", type=int, default=100)

    review_history = subparsers.add_parser("review-history", help="show decisions, comments, quality, and approval snapshots")
    review_history.add_argument("database", type=Path)
    review_history.add_argument("record_id")

    review_assign = subparsers.add_parser("review-assign", help="assign a reviewer")
    review_assign.add_argument("database", type=Path); review_assign.add_argument("record_id"); review_assign.add_argument("reviewer"); review_assign.add_argument("--actor", required=True)

    review_submit = subparsers.add_parser("review-submit", help="submit a record for review")
    review_submit.add_argument("database", type=Path); review_submit.add_argument("record_id"); review_submit.add_argument("--actor", required=True); review_submit.add_argument("--notes")

    review_start = subparsers.add_parser("review-start", help="start an assigned review")
    review_start.add_argument("database", type=Path); review_start.add_argument("record_id"); review_start.add_argument("--actor", required=True); review_start.add_argument("--notes")

    review_decide = subparsers.add_parser("review-decide", help="record a review decision")
    review_decide.add_argument("database", type=Path); review_decide.add_argument("record_id")
    review_decide.add_argument("decision", choices=("changes_requested","approved","rejected","superseded","archived","reopened"))
    review_decide.add_argument("--actor", required=True); review_decide.add_argument("--reason"); review_decide.add_argument("--notes")

    review_comment = subparsers.add_parser("review-comment", help="append an immutable review comment")
    review_comment.add_argument("database", type=Path); review_comment.add_argument("record_id"); review_comment.add_argument("body")
    review_comment.add_argument("--actor", required=True); review_comment.add_argument("--visibility", choices=("internal","public"), default="internal")

    quality_assess = subparsers.add_parser("quality-assess", help="append a six-dimension quality assessment from JSON")
    quality_assess.add_argument("database", type=Path); quality_assess.add_argument("record_id"); quality_assess.add_argument("input", type=Path); quality_assess.add_argument("--actor", required=True)

    revisions = subparsers.add_parser("revisions", help="show immutable record revisions and semantic diffs")
    revisions.add_argument("database", type=Path); revisions.add_argument("record_id"); revisions.add_argument("--limit", type=int, default=100)

    query_save = subparsers.add_parser("query-save", help="save or version a query definition")
    query_save.add_argument("database", type=Path); query_save.add_argument("input", type=Path)
    query_save.add_argument("--name"); query_save.add_argument("--description"); query_save.add_argument("--actor", default="local")

    queries = subparsers.add_parser("queries", help="list saved query definitions")
    queries.add_argument("database", type=Path); queries.add_argument("--limit", type=int, default=100)

    query_run = subparsers.add_parser("query-run", help="execute an ad hoc or saved query and freeze its results")
    query_run.add_argument("database", type=Path); query_run.add_argument("query", help="saved query ID or JSON definition path")

    query_runs = subparsers.add_parser("query-runs", help="list immutable query runs")
    query_runs.add_argument("database", type=Path); query_runs.add_argument("--query-id"); query_runs.add_argument("--limit", type=int, default=100)

    query_results = subparsers.add_parser("query-results", help="show frozen records, comparisons, warnings, and summary")
    query_results.add_argument("database", type=Path); query_results.add_argument("run_id")

    query_brief = subparsers.add_parser("query-brief", help="write a reproducible Markdown brief from a frozen run")
    query_brief.add_argument("database", type=Path); query_brief.add_argument("run_id"); query_brief.add_argument("output", type=Path)

    export_bundle = subparsers.add_parser("export-bundle", help="create a reproducible query export bundle")
    export_bundle.add_argument("database", type=Path); export_bundle.add_argument("run_id"); export_bundle.add_argument("output", type=Path)
    export_bundle.add_argument("--format", choices=("zip","directory"), default="zip")

    api_key_create = subparsers.add_parser("api-key-create", help="create a protected API bearer token")
    api_key_create.add_argument("database", type=Path); api_key_create.add_argument("name")
    api_key_create.add_argument("--scope", action="append", choices=("records:read","records:write","handoffs:write","connectors:read","connectors:run","connectors:admin","admin:keys"), required=True)
    api_key_create.add_argument("--workspace-id", default="workspace:default")
    api_key_create.add_argument("--principal-id", default="principal:system")

    api_keys = subparsers.add_parser("api-keys", help="list API clients without exposing tokens")
    api_keys.add_argument("database", type=Path)

    api_key_revoke = subparsers.add_parser("api-key-revoke", help="revoke an API client")
    api_key_revoke.add_argument("database", type=Path); api_key_revoke.add_argument("key_id")

    api_serve = subparsers.add_parser("serve", help="serve the Catalyst Data HTTP API")
    api_serve.add_argument("database", type=Path); api_serve.add_argument("--host", default="127.0.0.1"); api_serve.add_argument("--port", type=int, default=8765)
    api_serve.add_argument("--allow-origin"); api_serve.add_argument("--public-base-url")

    openapi = subparsers.add_parser("openapi", help="write the OpenAPI 3.1 document")
    openapi.add_argument("output", type=Path); openapi.add_argument("--base-url", default="http://127.0.0.1:8765")

    handoff_create = subparsers.add_parser("handoff-create", help="create a typed platform handoff from repository records")
    handoff_create.add_argument("database", type=Path); handoff_create.add_argument("output", type=Path); handoff_create.add_argument("record_ids", nargs="+")
    handoff_create.add_argument("--target", required=True, choices=("knowledge-library","research-librarian","site-intelligence","workbench","research-lab","catalyst-analytics-r","catalyst-canvas","decision-studio","platform-core"))
    handoff_create.add_argument("--capability", required=True); handoff_create.add_argument("--api-base-url")
    handoff_create.add_argument("--action", choices=("record-reference","record-transfer","query-run-reference","export-bundle-reference"), default="record-reference")
    handoff_create.add_argument("--query-run-id"); handoff_create.add_argument("--bundle-uri")

    handoff_validate = subparsers.add_parser("handoff-validate", help="validate a catalyst-data-handoff/1.0 envelope")
    handoff_validate.add_argument("input", type=Path)

    handoff_receive = subparsers.add_parser("handoff-receive", help="store an incoming typed handoff receipt")
    handoff_receive.add_argument("database", type=Path); handoff_receive.add_argument("input", type=Path)


    institution_create = subparsers.add_parser("institution-create", help="create an institutional tenant")
    institution_create.add_argument("database", type=Path); institution_create.add_argument("name"); institution_create.add_argument("--institution-id"); institution_create.add_argument("--actor", default="system")

    institutions = subparsers.add_parser("institutions", help="list institutions")
    institutions.add_argument("database", type=Path)

    workspace_create = subparsers.add_parser("workspace-create", help="create an institutional workspace")
    workspace_create.add_argument("database", type=Path); workspace_create.add_argument("institution_id"); workspace_create.add_argument("name")
    workspace_create.add_argument("--workspace-id"); workspace_create.add_argument("--visibility", choices=("private","shared","institutional","public"), default="private")
    workspace_create.add_argument("--classification", choices=("public","internal","restricted","confidential"), default="internal"); workspace_create.add_argument("--actor", default="system")

    workspaces = subparsers.add_parser("workspaces", help="list institutional workspaces")
    workspaces.add_argument("database", type=Path); workspaces.add_argument("--institution-id")

    project_create = subparsers.add_parser("project-create", help="create a project inside a workspace")
    project_create.add_argument("database", type=Path); project_create.add_argument("workspace_id"); project_create.add_argument("name"); project_create.add_argument("--project-id"); project_create.add_argument("--actor", default="system")

    principal_create = subparsers.add_parser("principal-create", help="create a user, service, or group principal")
    principal_create.add_argument("database", type=Path); principal_create.add_argument("display_name"); principal_create.add_argument("--principal-type", choices=("user","service","group"), default="user"); principal_create.add_argument("--email"); principal_create.add_argument("--principal-id"); principal_create.add_argument("--actor", default="system")

    principals = subparsers.add_parser("principals", help="list access principals")
    principals.add_argument("database", type=Path)

    member_add = subparsers.add_parser("workspace-member-add", help="grant or update a workspace role")
    member_add.add_argument("database", type=Path); member_add.add_argument("workspace_id"); member_add.add_argument("principal_id")
    member_add.add_argument("role", choices=("viewer","contributor","analyst","reviewer","approver","publisher","administrator")); member_add.add_argument("--actor", required=True); member_add.add_argument("--expires-at")

    members = subparsers.add_parser("workspace-members", help="list workspace members")
    members.add_argument("database", type=Path); members.add_argument("workspace_id")

    access_set = subparsers.add_parser("record-access-set", help="assign a record to a workspace and governance policy")
    access_set.add_argument("database", type=Path); access_set.add_argument("record_id"); access_set.add_argument("workspace_id"); access_set.add_argument("--actor", required=True)
    access_set.add_argument("--project-id"); access_set.add_argument("--owner-principal-id"); access_set.add_argument("--steward-principal-id"); access_set.add_argument("--custodian-principal-id")
    access_set.add_argument("--visibility", choices=("private","shared","institutional","public")); access_set.add_argument("--classification", choices=("public","internal","restricted","confidential")); access_set.add_argument("--retention-policy-id")

    record_access = subparsers.add_parser("record-access", help="show access governance for one record")
    record_access.add_argument("database", type=Path); record_access.add_argument("record_id")

    workspace_records = subparsers.add_parser("workspace-records", help="list records visible inside a workspace")
    workspace_records.add_argument("database", type=Path); workspace_records.add_argument("workspace_id"); workspace_records.add_argument("--principal-id"); workspace_records.add_argument("--limit", type=int, default=100)

    visibility_set = subparsers.add_parser("record-visibility-set", help="set record visibility and classification")
    visibility_set.add_argument("database", type=Path); visibility_set.add_argument("record_id"); visibility_set.add_argument("visibility", choices=("private","shared","institutional","public")); visibility_set.add_argument("classification", choices=("public","internal","restricted","confidential")); visibility_set.add_argument("--actor", required=True)

    retention_create = subparsers.add_parser("retention-policy-create", help="create an institutional retention policy")
    retention_create.add_argument("database", type=Path); retention_create.add_argument("institution_id"); retention_create.add_argument("name"); retention_create.add_argument("--retention-days", type=int); retention_create.add_argument("--disposition-action", choices=("review","archive","delete"), default="review"); retention_create.add_argument("--policy-id"); retention_create.add_argument("--description"); retention_create.add_argument("--actor", default="system")

    retention_list = subparsers.add_parser("retention-policies", help="list retention policies")
    retention_list.add_argument("database", type=Path); retention_list.add_argument("--institution-id")

    legal_hold = subparsers.add_parser("legal-hold", help="set or release a record legal hold")
    legal_hold.add_argument("database", type=Path); legal_hold.add_argument("record_id"); legal_hold.add_argument("state", choices=("set","release")); legal_hold.add_argument("--actor", required=True); legal_hold.add_argument("--reason")

    disposition = subparsers.add_parser("disposition-check", help="check whether retention permits record disposition")
    disposition.add_argument("database", type=Path); disposition.add_argument("record_id"); disposition.add_argument("--as-of")

    access_events = subparsers.add_parser("access-events", help="show append-only access governance events")
    access_events.add_argument("database", type=Path); access_events.add_argument("--workspace-id"); access_events.add_argument("--record-id"); access_events.add_argument("--limit", type=int, default=200)

    workspace_export = subparsers.add_parser("workspace-export-manifest", help="create an auditable workspace export manifest")
    workspace_export.add_argument("database", type=Path); workspace_export.add_argument("workspace_id"); workspace_export.add_argument("principal_id"); workspace_export.add_argument("output", type=Path); workspace_export.add_argument("--actor")


    connector_register = subparsers.add_parser("connector-register", help="register or version a governed connector")
    connector_register.add_argument("database", type=Path); connector_register.add_argument("definition", type=Path)
    connector_register.add_argument("--actor", default="principal:system"); connector_register.add_argument("--no-activate", action="store_true")

    connectors = subparsers.add_parser("connectors", help="list connector operational status")
    connectors.add_argument("database", type=Path); connectors.add_argument("--workspace-id")

    connector_versions = subparsers.add_parser("connector-versions", help="list immutable connector versions")
    connector_versions.add_argument("database", type=Path); connector_versions.add_argument("connector_id")

    connector_activate = subparsers.add_parser("connector-activate", help="activate an immutable connector version")
    connector_activate.add_argument("database", type=Path); connector_activate.add_argument("connector_id"); connector_activate.add_argument("version"); connector_activate.add_argument("--actor", default="principal:system")

    connector_run = subparsers.add_parser("connector-run", help="run a connector synchronously")
    connector_run.add_argument("database", type=Path); connector_run.add_argument("connector_id"); connector_run.add_argument("--payload", type=Path); connector_run.add_argument("--source-uri"); connector_run.add_argument("--max-attempts", type=int)

    connector_runs = subparsers.add_parser("connector-runs", help="list connector run history")
    connector_runs.add_argument("database", type=Path); connector_runs.add_argument("--connector-id"); connector_runs.add_argument("--status", choices=("queued","running","succeeded","partial","failed","quarantined","dead-letter","cancelled")); connector_runs.add_argument("--limit", type=int, default=100)

    connector_run_show = subparsers.add_parser("connector-run-show", help="show one connector run with logs and reconciliation")
    connector_run_show.add_argument("database", type=Path); connector_run_show.add_argument("run_id")

    connector_replay = subparsers.add_parser("connector-replay", help="replay an immutable connector payload snapshot")
    connector_replay.add_argument("database", type=Path); connector_replay.add_argument("run_id")

    connector_schedule = subparsers.add_parser("connector-schedule", help="create or update a connector schedule")
    connector_schedule.add_argument("database", type=Path); connector_schedule.add_argument("connector_id"); connector_schedule.add_argument("frequency_minutes", type=int); connector_schedule.add_argument("--disabled", action="store_true"); connector_schedule.add_argument("--next-run-at"); connector_schedule.add_argument("--actor", default="principal:system")

    connector_due = subparsers.add_parser("connector-due", help="list connectors due for refresh")
    connector_due.add_argument("database", type=Path); connector_due.add_argument("--as-of"); connector_due.add_argument("--workspace-id")

    connector_run_due = subparsers.add_parser("connector-run-due", help="run all due connectors synchronously")
    connector_run_due.add_argument("database", type=Path); connector_run_due.add_argument("--as-of"); connector_run_due.add_argument("--workspace-id")

    connector_quarantine = subparsers.add_parser("connector-quarantine", help="list quarantined connector rows")
    connector_quarantine.add_argument("database", type=Path); connector_quarantine.add_argument("--connector-id"); connector_quarantine.add_argument("--status", choices=("open","released","discarded","resolved"), default="open"); connector_quarantine.add_argument("--limit", type=int, default=100)

    connector_quarantine_recover = subparsers.add_parser("connector-quarantine-recover", help="retry a quarantined row with the active connector version")
    connector_quarantine_recover.add_argument("database", type=Path); connector_quarantine_recover.add_argument("quarantine_id")

    connector_dead_letters = subparsers.add_parser("connector-dead-letters", help="list connector dead letters")
    connector_dead_letters.add_argument("database", type=Path); connector_dead_letters.add_argument("--connector-id"); connector_dead_letters.add_argument("--status", choices=("open","replayed","resolved","discarded"), default="open"); connector_dead_letters.add_argument("--limit", type=int, default=100)

    connector_dead_letter_replay = subparsers.add_parser("connector-dead-letter-replay", help="replay a connector dead letter")
    connector_dead_letter_replay.add_argument("database", type=Path); connector_dead_letter_replay.add_argument("dead_letter_id")

    connector_alerts = subparsers.add_parser("connector-alerts", help="list connector operational alerts")
    connector_alerts.add_argument("database", type=Path); connector_alerts.add_argument("--connector-id"); connector_alerts.add_argument("--status", choices=("open","acknowledged","resolved"), default="open"); connector_alerts.add_argument("--limit", type=int, default=100)

    connector_alert_update = subparsers.add_parser("connector-alert-update", help="acknowledge or resolve a connector alert")
    connector_alert_update.add_argument("database", type=Path); connector_alert_update.add_argument("alert_id"); connector_alert_update.add_argument("status", choices=("acknowledged","resolved"))

    handoff_receipts = subparsers.add_parser("handoff-receipts", help="list immutable handoff receipts")
    handoff_receipts.add_argument("database", type=Path); handoff_receipts.add_argument("--limit", type=int, default=100)

    analysis_register = subparsers.add_parser("analysis-register", help="register or version a reproducible analysis artifact")
    analysis_register.add_argument("database", type=Path); analysis_register.add_argument("definition", type=Path); analysis_register.add_argument("--actor", default="principal:system"); analysis_register.add_argument("--no-activate", action="store_true")

    analyses = subparsers.add_parser("analyses", help="list analysis artifacts")
    analyses.add_argument("database", type=Path); analyses.add_argument("--workspace-id"); analyses.add_argument("--status", choices=("draft","active","completed","failed","invalidated","superseded","archived"))

    analysis_show = subparsers.add_parser("analysis-show", help="show one analysis artifact")
    analysis_show.add_argument("database", type=Path); analysis_show.add_argument("artifact_id")

    analysis_versions = subparsers.add_parser("analysis-versions", help="list immutable analysis versions")
    analysis_versions.add_argument("database", type=Path); analysis_versions.add_argument("artifact_id")

    analysis_activate = subparsers.add_parser("analysis-activate", help="activate an immutable analysis version")
    analysis_activate.add_argument("database", type=Path); analysis_activate.add_argument("artifact_id"); analysis_activate.add_argument("version"); analysis_activate.add_argument("--actor", default="principal:system")

    analysis_run = subparsers.add_parser("analysis-run", help="freeze inputs and record a reproducible analysis run")
    analysis_run.add_argument("database", type=Path); analysis_run.add_argument("artifact_id"); analysis_run.add_argument("--record-id", action="append", dest="record_ids"); analysis_run.add_argument("--parameters", type=Path); analysis_run.add_argument("--output", type=Path, action="append", dest="outputs"); analysis_run.add_argument("--actor", default="principal:system")

    analysis_runs = subparsers.add_parser("analysis-runs", help="list analysis run history")
    analysis_runs.add_argument("database", type=Path); analysis_runs.add_argument("--artifact-id"); analysis_runs.add_argument("--status", choices=("queued","running","completed","failed","invalidated","superseded","cancelled")); analysis_runs.add_argument("--limit", type=int, default=100)

    analysis_run_show = subparsers.add_parser("analysis-run-show", help="show a run, frozen inputs, outputs, and warnings")
    analysis_run_show.add_argument("database", type=Path); analysis_run_show.add_argument("run_id"); analysis_run_show.add_argument("--include-payloads", action="store_true")

    analysis_package = subparsers.add_parser("analysis-package", help="create a deterministic reproducible analysis package")
    analysis_package.add_argument("database", type=Path); analysis_package.add_argument("run_id"); analysis_package.add_argument("output", type=Path); analysis_package.add_argument("--actor", default="principal:system")

    analysis_packages = subparsers.add_parser("analysis-packages", help="list analysis package export history")
    analysis_packages.add_argument("database", type=Path); analysis_packages.add_argument("--run-id")

    analysis_invalidate = subparsers.add_parser("analysis-invalidate", help="detect changed or missing upstream records")
    analysis_invalidate.add_argument("database", type=Path); analysis_invalidate.add_argument("--run-id")

    analysis_invalidation_resolve = subparsers.add_parser("analysis-invalidation-resolve", help="append an invalidation resolution")
    analysis_invalidation_resolve.add_argument("database", type=Path); analysis_invalidation_resolve.add_argument("invalidation_id"); analysis_invalidation_resolve.add_argument("action", choices=("acknowledged","rerun","accepted","resolved")); analysis_invalidation_resolve.add_argument("--actor", required=True); analysis_invalidation_resolve.add_argument("--notes")

    analysis_lineage_add = subparsers.add_parser("analysis-lineage-add", help="link a derived record to source records and an analysis run")
    analysis_lineage_add.add_argument("database", type=Path); analysis_lineage_add.add_argument("run_id"); analysis_lineage_add.add_argument("derived_record_id"); analysis_lineage_add.add_argument("source_record_ids", nargs="+"); analysis_lineage_add.add_argument("--transformation", type=Path); analysis_lineage_add.add_argument("--output-id"); analysis_lineage_add.add_argument("--actor", default="principal:system")

    analysis_lineage = subparsers.add_parser("analysis-lineage", help="inspect derived measurement lineage")
    analysis_lineage.add_argument("database", type=Path); analysis_lineage.add_argument("record_id")

    analysis_replication = subparsers.add_parser("analysis-replication-review", help="append an independent replication review")
    analysis_replication.add_argument("database", type=Path); analysis_replication.add_argument("run_id"); analysis_replication.add_argument("status", choices=("pending","confirmed","partial","failed","not-reproducible")); analysis_replication.add_argument("reviewer"); analysis_replication.add_argument("--notes"); analysis_replication.add_argument("--evidence", type=Path); analysis_replication.add_argument("--reproduced-run-id")


    backup_create = subparsers.add_parser("backup-create", help="create and verify an online SQLite backup")
    backup_create.add_argument("database", type=Path); backup_create.add_argument("output", type=Path); backup_create.add_argument("--actor", default="principal:system")

    backup_verify = subparsers.add_parser("backup-verify", help="verify backup checksum, integrity, and migration compatibility")
    backup_verify.add_argument("database", type=Path); backup_verify.add_argument("backup", type=Path)

    backups = subparsers.add_parser("backups", help="list immutable backup history")
    backups.add_argument("database", type=Path); backups.add_argument("--limit", type=int, default=100)

    restore = subparsers.add_parser("restore", help="restore a verified SQLite backup")
    restore.add_argument("database", type=Path); restore.add_argument("backup", type=Path); restore.add_argument("--target", type=Path); restore.add_argument("--force", action="store_true"); restore.add_argument("--actor", default="principal:system")

    restore_history = subparsers.add_parser("restore-history", help="list append-only restore events")
    restore_history.add_argument("database", type=Path); restore_history.add_argument("--limit", type=int, default=100)

    offline_queue = subparsers.add_parser("offline-queue", help="queue an operation for later synchronization")
    offline_queue.add_argument("database", type=Path); offline_queue.add_argument("operation_type", choices=("record-upsert","connector-run","query-run","analysis-run","handoff-receive","custom")); offline_queue.add_argument("payload", type=Path); offline_queue.add_argument("--workspace-id", default="workspace:default"); offline_queue.add_argument("--actor", default="principal:system"); offline_queue.add_argument("--max-attempts", type=int, default=3)

    offline_operations = subparsers.add_parser("offline-operations", help="list queued and synchronized offline operations")
    offline_operations.add_argument("database", type=Path); offline_operations.add_argument("--status", choices=("queued","running","succeeded","failed","cancelled")); offline_operations.add_argument("--workspace-id"); offline_operations.add_argument("--limit", type=int, default=100)

    offline_sync = subparsers.add_parser("offline-sync", help="process queued offline operations")
    offline_sync.add_argument("database", type=Path); offline_sync.add_argument("--workspace-id"); offline_sync.add_argument("--actor", default="principal:system"); offline_sync.add_argument("--limit", type=int, default=100); offline_sync.add_argument("--retry-failed", action="store_true")

    offline_sync_runs = subparsers.add_parser("offline-sync-runs", help="list immutable offline synchronization runs")
    offline_sync_runs.add_argument("database", type=Path); offline_sync_runs.add_argument("--limit", type=int, default=100)

    benchmark = subparsers.add_parser("benchmark", help="run and persist repository performance checks")
    benchmark.add_argument("database", type=Path); benchmark.add_argument("--iterations", type=int, default=3); benchmark.add_argument("--actor", default="principal:system")

    benchmarks = subparsers.add_parser("benchmarks", help="list repository performance history")
    benchmarks.add_argument("database", type=Path); benchmarks.add_argument("--limit", type=int, default=100)

    security_audit = subparsers.add_parser("security-audit", help="run database, key, connector-secret, and file-permission checks")
    security_audit.add_argument("database", type=Path); security_audit.add_argument("--actor", default="principal:system")

    security_events = subparsers.add_parser("security-events", help="list append-only security audit checks")
    security_events.add_argument("database", type=Path); security_events.add_argument("--limit", type=int, default=100)

    release_attest = subparsers.add_parser("release-attest", help="write a release file manifest and lightweight SBOM")
    release_attest.add_argument("database", type=Path); release_attest.add_argument("source_root", type=Path); release_attest.add_argument("output", type=Path); release_attest.add_argument("--actor", default="principal:system")

    attestations = subparsers.add_parser("attestations", help="list immutable release attestations")
    attestations.add_argument("database", type=Path); attestations.add_argument("--limit", type=int, default=100)

    readiness = subparsers.add_parser("operational-readiness", help="show backup, offline, benchmark, security, and attestation readiness")
    readiness.add_argument("database", type=Path)

    return result


def _print_status(repository: CatalystRepository, *, as_json: bool) -> None:
    health = repository.health()
    payload = {
        "healthy": health.healthy,
        "path": health.path,
        "exists": health.exists,
        "integrity": health.integrity,
        "foreign_keys": health.foreign_keys,
        "migration_version": health.migration_version,
        "latest_migration": health.latest_migration,
        "repository_id": health.repository_id,
        "record_count": health.record_count,
        "import_run_count": health.import_run_count,
        "migrations": repository.migration_status() if health.exists else [],
    }
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    print(f"repository: {payload['path']}")
    print(f"health: {'healthy' if payload['healthy'] else 'attention required'}")
    print(f"integrity: {payload['integrity']}")
    print(f"migrations: {payload['migration_version']}/{payload['latest_migration']}")
    print(f"records: {payload['record_count']}")
    print(f"import runs: {payload['import_run_count']}")


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    commands = {"brief", "validate", "upgrade", "init", "migrate", "rollback", "status", "import", "export", "inspect", "review", "sources", "provenance", "evidence", "indicators", "methods", "units", "convert", "compare", "governance-events", "questions", "instruments", "datasets", "observations", "lineage", "reviews", "review-history", "review-assign", "review-submit", "review-start", "review-decide", "review-comment", "quality-assess", "revisions", "query-save", "queries", "query-run", "query-runs", "query-results", "query-brief", "export-bundle", "api-key-create", "api-keys", "api-key-revoke", "serve", "openapi", "handoff-create", "handoff-validate", "handoff-receive", "handoff-receipts", "institution-create", "institutions", "workspace-create", "workspaces", "project-create", "principal-create", "principals", "workspace-member-add", "workspace-members", "record-access-set", "record-access", "workspace-records", "record-visibility-set", "retention-policy-create", "retention-policies", "legal-hold", "disposition-check", "access-events", "workspace-export-manifest", "connector-register", "connectors", "connector-versions", "connector-activate", "connector-run", "connector-runs", "connector-run-show", "connector-replay", "connector-schedule", "connector-due", "connector-run-due", "connector-quarantine", "connector-quarantine-recover", "connector-dead-letters", "connector-dead-letter-replay", "connector-alerts", "connector-alert-update", "analysis-register", "analyses", "analysis-show", "analysis-versions", "analysis-activate", "analysis-run", "analysis-runs", "analysis-run-show", "analysis-package", "analysis-packages", "analysis-invalidate", "analysis-invalidation-resolve", "analysis-lineage-add", "analysis-lineage", "analysis-replication-review", "backup-create", "backup-verify", "backups", "restore", "restore-history", "offline-queue", "offline-operations", "offline-sync", "offline-sync-runs", "benchmark", "benchmarks", "security-audit", "security-events", "release-attest", "attestations", "operational-readiness", "-h", "--help"}
    if len(args_list) == 2 and args_list[0] not in commands:
        args_list = ["brief", *args_list]
    args = parser().parse_args(args_list)
    if not args.command:
        parser().print_help()
        return 2
    try:
        if args.command == "validate":
            validate_record(_read(args.input))
            print(f"valid {args.input}")
            return 0
        if args.command == "upgrade":
            record = convert_legacy_record(_read(args.input))
            _write_json(args.output, record)
            print(f"wrote {args.output}")
            return 0
        if args.command == "brief":
            record = build_record(_read(args.input))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(brief_markdown(record), encoding="utf-8")
            json_output = args.output.with_suffix(".json")
            _write_json(json_output, record)
            print(f"wrote {args.output}")
            print(f"wrote {json_output}")
            return 0

        if args.command == "openapi":
            _write_json(args.output, openapi_document(args.base_url))
            print(f"wrote {args.output}")
            return 0
        if args.command == "handoff-validate":
            validate_handoff(_read(args.input))
            print(f"valid {args.input}")
            return 0

        repository = CatalystRepository(args.database)
        if args.command == "init":
            applied = repository.initialize()
            print(f"initialized {args.database}")
            print("applied migrations: " + (", ".join(map(str, applied)) if applied else "none"))
            return 0
        if args.command == "migrate":
            applied = repository.migrate(target=args.target)
            print("applied migrations: " + (", ".join(map(str, applied)) if applied else "none"))
            return 0
        if args.command == "rollback":
            rolled_back = repository.rollback(args.steps)
            print("rolled back migrations: " + ", ".join(map(str, rolled_back)))
            return 0
        if args.command == "status":
            _print_status(repository, as_json=args.json)
            return 0 if repository.health().healthy else 1
        if args.command == "import":
            service = ImportService(repository)
            atomic = not args.non_atomic
            summary = service.run(
                args.input,
                format_name=args.format,
                dry_run=args.dry_run,
                atomic=atomic,
                continue_on_error=args.continue_on_error or args.non_atomic,
            )
            payload = summary.to_dict()
            if args.summary:
                _write_json(args.summary, payload)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 1 if summary.failed else 0
        if args.command == "export":
            count = export_repository(repository, args.output, format_name=args.format)
            print(f"exported {count} record(s) to {args.output}")
            return 0
        if args.command == "inspect":
            repository.initialize()
            if args.record_id:
                record = repository.get_record(args.record_id)
                if record is None:
                    print(f"ERROR: record not found: {args.record_id}")
                    return 1
                print(json.dumps(record, indent=2, ensure_ascii=False))
            else:
                print(json.dumps(repository.stats(), indent=2))
            return 0
        if args.command == "review":
            repository.initialize()
            print(json.dumps(repository.review_queue(status=args.status, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "sources":
            repository.initialize()
            print(json.dumps(repository.source_history(args.source_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "provenance":
            repository.initialize()
            print(json.dumps(repository.provenance(args.record_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "evidence":
            repository.initialize()
            payload = repository.evidence(args.record_id)
            if payload is None:
                print(f"ERROR: record not found: {args.record_id}")
                return 1
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        if args.command == "indicators":
            repository.initialize()
            print(json.dumps(repository.indicator_registry(args.indicator_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "methods":
            repository.initialize()
            print(json.dumps(repository.methodology_history(args.methodology_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "units":
            repository.initialize()
            print(json.dumps(repository.unit_registry(args.unit_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "convert":
            repository.initialize()
            print(json.dumps({"value": args.value, "from_unit": args.from_unit, "to_unit": args.to_unit, "converted_value": repository.convert(args.value, args.from_unit, args.to_unit)}, indent=2))
            return 0
        if args.command == "compare":
            repository.initialize()
            print(json.dumps(repository.compare(args.left_record_id, args.right_record_id), indent=2, ensure_ascii=False))
            return 0
        if args.command == "governance-events":
            repository.initialize()
            print(json.dumps(repository.governance_events(args.indicator_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "questions":
            repository.initialize()
            print(json.dumps(repository.questions(args.question_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "instruments":
            repository.initialize()
            print(json.dumps(repository.instruments(args.instrument_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "datasets":
            repository.initialize()
            print(json.dumps(repository.datasets(args.dataset_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "observations":
            repository.initialize()
            print(json.dumps(repository.observations(args.record_id, quality_status=args.quality_status, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "lineage":
            repository.initialize()
            payload = repository.lineage(args.record_id)
            if payload is None:
                print(f"ERROR: record not found: {args.record_id}")
                return 1
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0

        if args.command == "reviews":
            repository.initialize(); print(json.dumps(repository.review_cases(state=args.state, reviewer=args.reviewer, limit=args.limit), indent=2, ensure_ascii=False)); return 0
        if args.command == "review-history":
            repository.initialize(); payload=repository.review_history(args.record_id)
            if payload is None: print(f"ERROR: record not found: {args.record_id}"); return 1
            print(json.dumps(payload, indent=2, ensure_ascii=False)); return 0
        if args.command == "review-assign":
            repository.initialize(); action=repository.assign_review(args.record_id,args.reviewer,args.actor); print(action); return 0
        if args.command == "review-submit":
            repository.initialize(); action=repository.submit_review(args.record_id,args.actor,args.notes); print(action); return 0
        if args.command == "review-start":
            repository.initialize(); action=repository.start_review(args.record_id,args.actor,args.notes); print(action); return 0
        if args.command == "review-decide":
            repository.initialize(); action=repository.decide_review(args.record_id,args.decision,args.actor,reason=args.reason,notes=args.notes); print(action); return 0
        if args.command == "review-comment":
            repository.initialize(); action=repository.add_review_comment(args.record_id,args.actor,args.body,visibility=args.visibility); print(action); return 0
        if args.command == "quality-assess":
            repository.initialize(); payload=_read(args.input); scores=payload.get("scores",payload); basis=payload.get("basis",{}) if isinstance(payload,dict) else {}
            action=repository.assess_quality(args.record_id,args.actor,scores,basis=basis); print(action); return 0
        if args.command == "revisions":
            repository.initialize(); print(json.dumps(repository.revision_history(args.record_id,limit=args.limit),indent=2,ensure_ascii=False)); return 0

        if args.command == "query-save":
            studio=QueryStudio(repository); definition=_read(args.input)
            print(json.dumps(studio.save(definition,name=args.name,description=args.description,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "queries":
            print(json.dumps(QueryStudio(repository).list_queries(limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "query-run":
            studio=QueryStudio(repository); candidate=Path(args.query)
            source=_read(candidate) if candidate.exists() else args.query
            print(json.dumps(studio.run(source),indent=2,ensure_ascii=False)); return 0
        if args.command == "query-runs":
            print(json.dumps(QueryStudio(repository).list_runs(query_id=args.query_id,limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "query-results":
            print(json.dumps(QueryStudio(repository).get_run(args.run_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "query-brief":
            path=QueryStudio(repository).write_brief(args.run_id,args.output); print(f"wrote {path}"); return 0
        if args.command == "export-bundle":
            print(json.dumps(QueryStudio(repository).export_bundle(args.run_id,args.output,bundle_format=args.format),indent=2,ensure_ascii=False)); return 0
        if args.command == "institution-create":
            service=WorkspaceService(repository); print(json.dumps(service.create_institution(args.name,institution_id=args.institution_id,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "institutions":
            print(json.dumps(WorkspaceService(repository).institutions(),indent=2,ensure_ascii=False)); return 0
        if args.command == "workspace-create":
            service=WorkspaceService(repository); print(json.dumps(service.create_workspace(args.institution_id,args.name,workspace_id=args.workspace_id,visibility=args.visibility,classification=args.classification,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "workspaces":
            print(json.dumps(WorkspaceService(repository).workspaces(institution_id=args.institution_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "project-create":
            print(json.dumps(WorkspaceService(repository).create_project(args.workspace_id,args.name,project_id=args.project_id,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "principal-create":
            print(json.dumps(WorkspaceService(repository).create_principal(args.display_name,principal_type=args.principal_type,email=args.email,principal_id=args.principal_id,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "principals":
            print(json.dumps(WorkspaceService(repository).principals(),indent=2,ensure_ascii=False)); return 0
        if args.command == "workspace-member-add":
            print(json.dumps(WorkspaceService(repository).add_member(args.workspace_id,args.principal_id,args.role,actor=args.actor,expires_at=args.expires_at),indent=2,ensure_ascii=False)); return 0
        if args.command == "workspace-members":
            print(json.dumps(WorkspaceService(repository).members(args.workspace_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "record-access-set":
            print(json.dumps(WorkspaceService(repository).assign_record(args.record_id,args.workspace_id,actor=args.actor,project_id=args.project_id,owner_principal_id=args.owner_principal_id,steward_principal_id=args.steward_principal_id,custodian_principal_id=args.custodian_principal_id,visibility=args.visibility,classification=args.classification,retention_policy_id=args.retention_policy_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "record-access":
            print(json.dumps(WorkspaceService(repository).record_access(args.record_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "workspace-records":
            print(json.dumps(WorkspaceService(repository).records(args.workspace_id,principal_id=args.principal_id,limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "record-visibility-set":
            print(json.dumps(WorkspaceService(repository).set_visibility(args.record_id,args.visibility,args.classification,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "retention-policy-create":
            print(json.dumps(WorkspaceService(repository).create_retention_policy(args.institution_id,args.name,retention_days=args.retention_days,disposition_action=args.disposition_action,policy_id=args.policy_id,description=args.description,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "retention-policies":
            print(json.dumps(WorkspaceService(repository).retention_policies(args.institution_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "legal-hold":
            print(json.dumps(WorkspaceService(repository).set_legal_hold(args.record_id,args.state=="set",actor=args.actor,reason=args.reason),indent=2,ensure_ascii=False)); return 0
        if args.command == "disposition-check":
            print(json.dumps(WorkspaceService(repository).can_dispose(args.record_id,as_of=args.as_of),indent=2,ensure_ascii=False)); return 0
        if args.command == "access-events":
            print(json.dumps(WorkspaceService(repository).events(workspace_id=args.workspace_id,record_id=args.record_id,limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "workspace-export-manifest":
            payload=WorkspaceService(repository).export_workspace_manifest(args.workspace_id,principal_id=args.principal_id,actor=args.actor); _write_json(args.output,payload); print(f"wrote {args.output}"); return 0
        if args.command == "connector-register":
            service=ConnectorService(repository); payload=_read(args.definition)
            print(json.dumps(service.register(payload,actor=args.actor,activate=not args.no_activate),indent=2,ensure_ascii=False)); return 0
        if args.command == "connectors":
            print(json.dumps(ConnectorService(repository).list(workspace_id=args.workspace_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "connector-versions":
            print(json.dumps(ConnectorService(repository).versions(args.connector_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "connector-activate":
            print(json.dumps(ConnectorService(repository).activate_version(args.connector_id,args.version,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "connector-run":
            payload=args.payload.read_bytes() if args.payload else None
            result=ConnectorService(repository).run(args.connector_id,payload=payload,source_uri=args.source_uri,max_attempts=args.max_attempts)
            print(json.dumps(result,indent=2,ensure_ascii=False)); return 0 if result["run"]["status"] in ("succeeded","partial") else 1
        if args.command == "connector-runs":
            print(json.dumps(ConnectorService(repository).runs(connector_id=args.connector_id,status=args.status,limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "connector-run-show":
            print(json.dumps(ConnectorService(repository).run_details(args.run_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "connector-replay":
            result=ConnectorService(repository).replay(args.run_id); print(json.dumps(result,indent=2,ensure_ascii=False)); return 0 if result["run"]["status"] in ("succeeded","partial") else 1
        if args.command == "connector-schedule":
            print(json.dumps(ConnectorService(repository).set_schedule(args.connector_id,args.frequency_minutes,enabled=not args.disabled,next_run_at=args.next_run_at,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "connector-due":
            print(json.dumps(ConnectorService(repository).due(as_of=args.as_of,workspace_id=args.workspace_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "connector-run-due":
            results=ConnectorService(repository).run_due(as_of=args.as_of,workspace_id=args.workspace_id); print(json.dumps(results,indent=2,ensure_ascii=False)); return 0 if all(item["run"]["status"] in ("succeeded","partial") for item in results) else 1
        if args.command == "connector-quarantine":
            print(json.dumps(ConnectorService(repository).quarantine(connector_id=args.connector_id,status=args.status,limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "connector-quarantine-recover":
            result=ConnectorService(repository).recover_quarantine(args.quarantine_id); print(json.dumps(result,indent=2,ensure_ascii=False)); return 0 if result["run"]["status"] in ("succeeded","partial") else 1
        if args.command == "connector-dead-letters":
            print(json.dumps(ConnectorService(repository).dead_letters(connector_id=args.connector_id,status=args.status,limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "connector-dead-letter-replay":
            result=ConnectorService(repository).replay_dead_letter(args.dead_letter_id); print(json.dumps(result,indent=2,ensure_ascii=False)); return 0 if result["run"]["status"] in ("succeeded","partial") else 1
        if args.command == "connector-alerts":
            print(json.dumps(ConnectorService(repository).alerts(connector_id=args.connector_id,status=args.status,limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "connector-alert-update":
            print(json.dumps(ConnectorService(repository).set_alert_status(args.alert_id,args.status),indent=2,ensure_ascii=False)); return 0
        if args.command == "api-key-create":
            payload = ApiRegistry(repository).create_key(args.name, args.scope, workspace_id=args.workspace_id, principal_id=args.principal_id)
            print(json.dumps(payload, indent=2))
            print("WARNING: store the token now; it cannot be recovered.", file=sys.stderr)
            return 0
        if args.command == "api-keys":
            print(json.dumps(ApiRegistry(repository).list_keys(), indent=2)); return 0
        if args.command == "api-key-revoke":
            revoked = ApiRegistry(repository).revoke(args.key_id)
            print("revoked" if revoked else "not found")
            return 0 if revoked else 1
        if args.command == "serve":
            print(f"serving Catalyst Data on http://{args.host}:{args.port}")
            serve(repository, args.host, args.port, allow_origin=args.allow_origin, public_base_url=args.public_base_url)
            return 0
        if args.command == "handoff-create":
            repository.initialize(); records=[]
            for record_id in args.record_ids:
                record=repository.get_record(record_id)
                if record is None: raise RepositoryError(f"record not found: {record_id}")
                records.append(record)
            from . import __version__
            payload=create_handoff(records,target_product=args.target,target_capability=args.capability,source_version=__version__,api_base_url=args.api_base_url,action=args.action,query_run_id=args.query_run_id,bundle_uri=args.bundle_uri)
            _write_json(args.output,payload); print(f"wrote {args.output}"); return 0
        if args.command == "handoff-receive":
            repository.initialize(); result=ApiRegistry(repository).receive_handoff(read_handoff(args.input)); print(json.dumps(result,indent=2)); return 0
        if args.command == "handoff-receipts":
            repository.initialize(); print(json.dumps(ApiRegistry(repository).receipts(args.limit),indent=2)); return 0
        if args.command == "backup-create":
            print(json.dumps(OperationalService(repository).create_backup(args.output,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "backup-verify":
            print(json.dumps(OperationalService(repository).verify_backup(args.backup),indent=2,ensure_ascii=False)); return 0
        if args.command == "backups":
            print(json.dumps(OperationalService(repository).backups(limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "restore":
            print(json.dumps(OperationalService(repository).restore_backup(args.backup,args.target,actor=args.actor,force=args.force),indent=2,ensure_ascii=False)); return 0
        if args.command == "restore-history":
            print(json.dumps(OperationalService(repository).restore_history(limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "offline-queue":
            print(json.dumps(OperationalService(repository).queue_operation(args.operation_type,_read(args.payload),workspace_id=args.workspace_id,actor=args.actor,max_attempts=args.max_attempts),indent=2,ensure_ascii=False)); return 0
        if args.command == "offline-operations":
            print(json.dumps(OperationalService(repository).operations(status=args.status,workspace_id=args.workspace_id,limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "offline-sync":
            result=OperationalService(repository).sync_offline(workspace_id=args.workspace_id,actor=args.actor,limit=args.limit,retry_failed=args.retry_failed); print(json.dumps(result,indent=2,ensure_ascii=False)); return 0 if result["status"] in ("completed","partial") else 1
        if args.command == "offline-sync-runs":
            print(json.dumps(OperationalService(repository).sync_runs(limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "benchmark":
            result=OperationalService(repository).benchmark(actor=args.actor,iterations=args.iterations); print(json.dumps(result,indent=2,ensure_ascii=False)); return 0 if result["status"] != "fail" else 1
        if args.command == "benchmarks":
            print(json.dumps(OperationalService(repository).benchmarks(limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "security-audit":
            result=OperationalService(repository).security_audit(actor=args.actor); print(json.dumps(result,indent=2,ensure_ascii=False)); return 0 if result["status"] != "fail" else 1
        if args.command == "security-events":
            print(json.dumps(OperationalService(repository).security_events(limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "release-attest":
            print(json.dumps(OperationalService(repository).create_release_attestation(args.source_root,args.output,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "attestations":
            print(json.dumps(OperationalService(repository).attestations(limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "operational-readiness":
            print(json.dumps(OperationalService(repository).readiness(),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-register":
            print(json.dumps(AnalysisArtifactService(repository).register(_read(args.definition),actor=args.actor,activate=not args.no_activate),indent=2,ensure_ascii=False)); return 0
        if args.command == "analyses":
            print(json.dumps(AnalysisArtifactService(repository).list(workspace_id=args.workspace_id,status=args.status),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-show":
            print(json.dumps(AnalysisArtifactService(repository).get(args.artifact_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-versions":
            print(json.dumps(AnalysisArtifactService(repository).versions(args.artifact_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-activate":
            print(json.dumps(AnalysisArtifactService(repository).activate_version(args.artifact_id,args.version,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-run":
            parameters=_read(args.parameters) if args.parameters else None
            outputs=[{"name":path.name,"path":str(path),"output_type":"document"} for path in (args.outputs or [])]
            print(json.dumps(AnalysisArtifactService(repository).run(args.artifact_id,record_ids=args.record_ids,parameters=parameters,outputs=outputs,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-runs":
            print(json.dumps(AnalysisArtifactService(repository).runs(artifact_id=args.artifact_id,status=args.status,limit=args.limit),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-run-show":
            print(json.dumps(AnalysisArtifactService(repository).run_details(args.run_id,include_payloads=args.include_payloads),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-package":
            print(json.dumps(AnalysisArtifactService(repository).export_package(args.run_id,args.output,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-packages":
            print(json.dumps(AnalysisArtifactService(repository).packages(args.run_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-invalidate":
            print(json.dumps(AnalysisArtifactService(repository).detect_invalidations(args.run_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-invalidation-resolve":
            print(json.dumps(AnalysisArtifactService(repository).resolve_invalidation(args.invalidation_id,args.action,actor=args.actor,notes=args.notes),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-lineage-add":
            transformation=_read(args.transformation) if args.transformation else None
            print(json.dumps(AnalysisArtifactService(repository).add_derived_lineage(args.run_id,args.derived_record_id,args.source_record_ids,transformation=transformation,output_id=args.output_id,actor=args.actor),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-lineage":
            print(json.dumps(AnalysisArtifactService(repository).derived_lineage(args.record_id),indent=2,ensure_ascii=False)); return 0
        if args.command == "analysis-replication-review":
            evidence=_read(args.evidence) if args.evidence else None
            print(json.dumps(AnalysisArtifactService(repository).add_replication_review(args.run_id,args.status,args.reviewer,notes=args.notes,evidence=evidence,reproduced_run_id=args.reproduced_run_id),indent=2,ensure_ascii=False)); return 0
        return 2
    except ImportPipelineError as exc:
        payload = exc.summary.to_dict()
        if getattr(args, "summary", None):
            _write_json(args.summary, payload)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1
    except (OSError, json.JSONDecodeError, ValueError, KeyError, RecordValidationError, RepositoryError, AccessDenied, ConnectorError, AnalysisArtifactError, OperationalError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
