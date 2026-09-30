from app.auth.permissions import MANAGE_APPOINTMENTS_ALL, MANAGE_CASES, MANAGE_OWN_CALENDAR
from app.auth.rbac_registry import get_rbac_registry
from app.config import settings
from app.main import app
from app.models.user import UserRole


def _find(registry, method, path):
    return next(e for e in registry if e.method == method and e.path == path)


def test_finds_known_permission_gated_route():
    entry = _find(get_rbac_registry(app), "POST", "/api/v1/triage")
    assert entry.rbac_check == ("permission", frozenset({MANAGE_CASES}))


def test_finds_known_any_permission_gated_route():
    entry = _find(get_rbac_registry(app), "GET", "/api/v1/appointments")
    assert entry.rbac_check == (
        "any_permission",
        frozenset({MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR}),
    )


def test_finds_known_role_gated_route():
    entry = _find(get_rbac_registry(app), "GET", "/api/v1/llm/status")
    assert entry.rbac_check == ("roles", frozenset({UserRole.ADMIN, UserRole.OPERATOR}))


def test_reports_none_for_route_with_no_rbac_gate():
    entry = _find(get_rbac_registry(app), "GET", "/health")
    assert entry.rbac_check is None


def test_excludes_fastapi_internal_routes():
    paths = {e.path for e in get_rbac_registry(app)}
    assert "/openapi.json" not in paths
    assert "/docs" not in paths
    assert "/redoc" not in paths


def test_resolves_full_prefixed_paths():
    paths = {e.path for e in get_rbac_registry(app)}
    assert "/api/v1/triage" in paths
    assert "/health" in paths  # included without the /api/v1 prefix, confirms prefix
    # resolution is per-router (via _IncludedRouter.include_context.prefix), not hardcoded.


def test_total_route_count():
    registry = get_rbac_registry(app)
    # 72 real application routes as of this writing (71 after reconciling two
    # branches that each independently ported origin/feature/task-call-models,
    # so their two prior counts, 63 and 60, both already included the shared
    # base /calls and /tasks routes and can't just be summed; +1 for
    # POST /api/v1/calls/transcribe, the call-transcription connector).
    # Counted directly off the merged app's own route table, not derived from
    # either branch's stale number. Bump deliberately when a route is added or
    # removed; an unexpected change here means the walker itself regressed
    # (e.g. double-counting via bad recursion), not that this number merely
    # went stale.
    # 74 as of the inbox delete/read feature: +2 for DELETE /api/v1/tasks/{task_id}
    # and POST /api/v1/tasks/{task_id}/read.
    # 82 as of the appointments calendar feature (Plan 2): +8 for GET /doctors,
    # GET /appointments/calendar, GET /appointments/calendar/markers,
    # GET /appointments/day, GET /appointments/availability,
    # GET /appointments/{appointment_id}, PATCH /appointments/{appointment_id},
    # and POST /appointments/{appointment_id}/complete.
    # 83 as of the appointments data-paths feature (Plan 3): +1 for
    # POST /appointments/suggest.
    # 84 as of the dashboard workflow-status fix: +1 for GET /human-review/stats/daily.
    # 89 as of the settings page work: +5 for GET /settings, PATCH /settings,
    # POST /auth/me/password, GET /health/detailed, and GET /audit/incidents.
    # 91 as of the consent form snapshot work: +2 for
    # POST /consent/{consent_id}/resolve-review and GET /audit/verify.
    # 92 as of the corpus-as-documents work: +1 for GET /rag/documents.
    # 93 as of the provisional-patient work (build spec 9.0b): +1 for
    # POST /patients/{patient_id}/promote, which requires REGISTER_PATIENT.
    # 94 as of the consent queue fix: +1 for GET /consent/queue, which requires
    # CAPTURE_CONSENT (front desk, operators and admins, not clinicians) and
    # replaces a frontend page that listed intake cases and labelled them from
    # a hardcoded array of form names.
    # 97 as of the voicemail channel: the password reset work (6a98b8a) added 2
    # routes without bumping this (96 real), +1 for POST /voicemails/simulate
    # (MANAGE_CASES).
    # 98: +1 for GET /calls/{call_id}/audio (PLAY_VOICEMAIL).
    # 101 as of the registration form link: +2 for GET and POST
    # /public/registration/{token} (public, allowlisted) and +1 for
    # POST /consent/{consent_id}/verify (CAPTURE_CONSENT).
    # The five Twilio webhooks under /voice are mounted only with
    # TWILIO_ENABLED, so a dev .env that turns the line on adds them.
    # 104 as of the review queue: +3 for POST /human-review/{task_id}/reroute,
    # /link-patient and /reassign.
    # 105: +1 for GET /inbox/{task_id}.
    # 106: +1 for POST /inbox/{task_id}/reply (Write reply, D14).
    # 117 as of cases as episodes of care (M4): +8 for /cases (GET and POST,
    # GET and PATCH /{episode_id}, POST /{episode_id}/close, /reopen and
    # /contact, POST /move), +2 for POST /human-review/{task_id}/choose-case and
    # /case-close, +1 for PUT /patients/{patient_id}/doctor (ASSIGN_PATIENTS).
    # 120: +3 for the clinic mailbox in Settings, GET /integrations/outlook,
    # POST /integrations/outlook/connect and GET /integrations/outlook/callback.
    voice = 5 if settings.twilio_enabled else 0
    assert len({(e.method, e.path) for e in registry}) == 120 + voice
