# Feature Branch: Task & Call Models

## Purpose

This branch introduces the core Task and Call data models together with the initial manual call intake workflow for the VitalAI backend.

## Objectives

- Create Task and Call database models.
- Support manual call registration.
- Link calls to intake cases.
- Enable task creation for human workflows.
- Provide the foundation for future routing and escalation features.

## Main Components

- Call model
- Task model
- Alembic migrations
- Manual call endpoints
- Permission enforcement
- Unit and integration tests

## Integration

This work provides the foundation for:

- Human task management
- Call logging
- AI-assisted routing
- Human escalation workflows
- Queue management

## Review Changes

During code review this branch was updated to:

- Align migration numbering with the latest migration chain.
- Apply permission checks for call creation.
- Update tests to reflect permission requirements.
- Resolve migration conflicts with the main branch.

## Status

Completed feature branch.

The Task and Call models, manual call entry functionality, and review feedback were integrated into the project. The original routing implementation was later superseded by the newer integrated routing architecture during backend integration.

## Notes

This branch represents the foundational implementation for Task and Call entities. Subsequent integration branches extended and replaced portions of the routing workflow while retaining the underlying models and manual entry functionality.
