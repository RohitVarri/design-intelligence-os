"""Shared database locks for project-scoped source changes and operations."""
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project


def lock_project(db: Session, project_id: uuid.UUID) -> Project:
    """Lock and refresh a project row before any source or design-state mutation.

    PostgreSQL writers of reasoning inputs use this same row lock so an
    operation can hold it from freshness validation through commit.
    """
    # Some existing workflows intentionally prepare a new intent and then
    # generate its questions in the same transaction. Flush those local
    # changes before refreshing the identity-mapped Project row under lock.
    db.flush()
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if project is None:
        raise HTTPException(404, "Project not found")
    return project
