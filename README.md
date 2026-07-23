# CSIT321 Capstone Monorepo

This repository is organised as a monorepo. Each top-level directory is a self-contained service or workspace.

## Structure

```
/
├── backend/     FastAPI backend- see backend/README.md for setup and API reference
├── frontend/    Frontend
├── docs/        Project documentation
└── .github/     CI pipelines
```

## Quick start

See [backend/README.md](backend/README.md) for the backend service.

## Frontend

React + Vite + React Router + Tailwind SPA. See [frontend/README.md](frontend/README.md).
All 10 sponsor-approved screens are implemented and wired to the backend; pages
and fields without a backend yet are served through an adapter seam
(`frontend/src/api/_placeholder.ts`) so a real database drops in without touching
UI components.
