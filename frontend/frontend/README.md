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

## The 10 approved screens

All ten sponsor-approved designs are implemented: Login, Forgot password,
Dashboard, Patients list, Patient onboarding, Consent queue, Consent capture,
Consent success, Records & information retrieval, and Inbox.

The sidebar's remaining items (Review Queue, Escalations, Audit, Settings) appear
in navigation and route to a titled placeholder until their designs are approved.
Their backend endpoints already exist.

## Database-agnostic design (the adapter seam)

Components import domain types from `src/api/types.ts` only — never raw API
shapes. Each `src/api/*.ts` file is an adapter that maps today's backend to those
types. Anything the backend doesn't serve yet is fed from ONE file,
`src/api/_placeholder.ts`, behind clearly marked seams:

| Screen / field | Today | To make real |
| --- | --- | --- |
| Patients MRN / DOB / gender / status | synthesized deterministically | replace body of `listPatients` in `src/api/cases.ts` |
| Inbox threads | placeholder list | replace body of `listMessages` in `src/api/misc.ts` |
| Dashboard weekly chart | placeholder bars (tiles are live) | replace `workflowByDay` source in `src/api/misc.ts` |
| Forgot-password submit | confirmation only | point at a reset endpoint when one exists |

Wiring a real database later means changing adapter bodies and deleting the
matching placeholder export. No component changes.

## Wired to real endpoints

Login (`/auth/login`), dashboard count tiles, patients list (`/intake`), consent
queue and capture (`/consent/*`), records (`/rag/query` ready), users
(`/auth/users`). See `../docs/API_CONTRACT.md` for the full mapping.

## Structure

```
src/
  lib/apiClient.ts   single HTTP transport (JWT, form-login, page envelope)
  lib/auth.tsx       session context
  api/types.ts       domain model — the stable contract
  api/*.ts           adapters: backend shapes -> domain types
  api/_placeholder.ts   the one file to replace when real backends land
  components/        Sidebar, Topbar, Layout, ProtectedRoute, shared UI
  pages/             one file per screen
```
