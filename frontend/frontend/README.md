# VitalAI Frontend

React + Vite + React Router + Tailwind SPA for the VitalAI system.

## Running

```bash
cp .env.example .env      # VITE_API_BASE_URL=http://localhost:8000
npm install
npm run dev               # http://localhost:5173
```

`npm run build` type-checks (TypeScript strict) and emits a production bundle to
`dist/`. The backend must allow the frontend origin via its `CORS_ORIGINS` env
(preconfigured for `http://localhost:5173`).

## Screens

All 25 sponsor-approved designs are implemented across two shells:

**Main app**: Login, Forgot password, Dashboard, Patients list, Patient
onboarding, Patient detail, Case detail, Consent queue, Consent capture,
Consent success, Records & information retrieval, Inbox, Compose, Review
queue, Add case, Escalations, Audit log, Audit event detail, Users, and
Settings.

**Platform Operations**: a separate shell with its own login gate
(`/platform-ops/login`), System Health, and Model & Risk Configuration.
It shares the same auth session as the main app but renders its own sidebar
and layout (`PlatformOpsLayout` in `src/pages/PlatformOps.tsx`).

Audit and Users are gated to the `admin` role via `<ProtectedRoute roles={["admin"]}>`
and are hidden from the sidebar for other roles.

## Database-agnostic design (the adapter seam)

Components import domain types from `src/api/types.ts` only: never raw API
shapes. Each `src/api/*.ts` file is an adapter that maps today's backend to those
types. Anything the backend doesn't serve yet is fed from ONE file,
`src/api/_placeholder.ts`, behind clearly marked seams:

| Screen / field | Today | To make real |
| --- | --- | --- |
| Dashboard weekly chart | placeholder bars (`placeholderWorkflowByDay`); count tiles and the Pending Reviews list are live | replace the `workflowByDay` source in `getDashboard` (`src/api/misc.ts`) |
| Consent queue form label | placeholder rotation (`placeholderConsentForms`); the queue itself is built from real cases + consent records | replace once a forms backend exists, in `listConsentQueue` (`src/api/consent.ts`) |
| Forgot-password submit | confirmation only, no request sent | point at a reset endpoint when one exists, in `ForgotPasswordPage.tsx` |
| Platform Ops login | accepts any input, no real auth check | wire to a real operator-auth endpoint |

`_placeholder.ts` also still exports `placeholderPatientFields` and
`placeholderMessages`, but neither is imported anywhere anymore: Patients
(MRN/DOB/gender/status) and Inbox now read real fields from `/patients` and
`/inbox`. Both exports are dead code kept for reference and can be deleted.

Wiring a real database later means changing adapter bodies and deleting the
matching placeholder export. No component changes.

## Wired to real endpoints

- Auth: login (`/auth/login`, OAuth2 form flow), current user (`/auth/me`),
  user management (`/auth/users`, elevate/department/active/grants)
- Dashboard: count tiles and Pending Reviews list, aggregated from `/intake`,
  `/audit`, and `/human-review`
- Patients (`/patients`) and Cases/Intake (`/intake`)
- Consent (`/consent/*`)
- Records: clinical documents (`/clinical-documents`) and RAG query (`/rag/query`)
- Inbox actions: approve draft, escalate, archive (`/approvals`, `/tasks/*`)
- Review queue (`/human-review/*`): claim, complete, reject, escalate, create
- Tasks / Escalations board (`/tasks/*`) with comments
- Audit (`/audit/*`), including chain verification and CSV export

## Structure

```
src/
  lib/apiClient.ts   single HTTP transport (JWT, form-login, page envelope)
  lib/auth.tsx        session context
  api/types.ts        domain model: the stable contract
  api/*.ts             adapters: backend shapes -> domain types
                        (auth, cases, consent, records, misc, tasks,
                         reviewTasks, audit)
  api/_placeholder.ts  the one file to replace when real backends land
  components/          Sidebar, Layout, ProtectedRoute, shared UI (ui.tsx)
  pages/               one file per screen, plus PlatformOps.tsx which
                        exports the whole Platform Operations shell
                        (login, layout, System Health, Model Config)
```
