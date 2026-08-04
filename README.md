# Feature Branch: Appointment Model

## Purpose

This branch introduces the appointment domain model used by the VitalAI backend. It establishes the database entities, schemas, and supporting components required for appointment scheduling and management.

## Objectives

- Introduce the Appointment model.
- Define appointment status lifecycle.
- Integrate appointments with existing users and intake cases.
- Support future scheduling APIs.
- Prepare the database schema through Alembic migrations.

## Main Components

- Appointment SQLAlchemy model
- Appointment status enumeration
- Database migration
- Model registration
- Supporting schemas

## Integration

This branch provides the foundation for:

- Appointment booking
- Appointment management
- Calendar integration
- Clinical scheduling workflows

## Status

Completed feature branch.
Integrated into the project as the foundation for appointment functionality.

## Notes

This branch focuses on the data model only. Business logic and scheduling workflows are implemented in later feature branches.
