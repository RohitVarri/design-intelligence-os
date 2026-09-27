"""Immutable snapshot, comparison, and restoration operations."""
import uuid
from typing import Any
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.design_state import DesignState
from app.models.project import Project
from app.models.version import DesignVersion

def create_version(db: Session, project_id: uuid.UUID, state: dict[str, Any], summary: str) -> DesignVersion:
    """Create the next complete snapshot and link it to the current version."""
    current = db.get(DesignState, project_id)
    number = db.scalar(select(func.max(DesignVersion.version_number)).where(DesignVersion.project_id == project_id)) or 0
    version = DesignVersion(project_id=project_id, version_number=number + 1,
        parent_version_id=current.current_version_id if current else None, state=state, change_summary=summary)
    db.add(version)
    db.flush()
    return version

def get_version(db: Session, project_id: uuid.UUID, version_id: uuid.UUID) -> DesignVersion:
    """Get a version scoped to its project or raise 404."""
    version = db.scalar(select(DesignVersion).where(DesignVersion.id == version_id, DesignVersion.project_id == project_id))
    if not version:
        raise HTTPException(404, "Design version not found")
    return version

def compare_versions(left: DesignVersion, right: DesignVersion) -> dict[str, Any]:
    """Return a recursive structural diff between two snapshots."""
    def diff(a: Any, b: Any, path: str = "") -> dict[str, Any]:
        if isinstance(a, dict) and isinstance(b, dict):
            out = {}
            for key in sorted(a.keys() | b.keys()):
                p = f"{path}.{key}" if path else key
                if key not in a: out[p] = {"before": None, "after": b[key]}
                elif key not in b: out[p] = {"before": a[key], "after": None}
                else: out.update(diff(a[key], b[key], p))
            return out
        return {} if a == b else {path or "$": {"before": a, "after": b}}
    return diff(left.state, right.state)

def restore_version(db: Session, project_id: uuid.UUID, version: DesignVersion) -> DesignState:
    """Restore snapshot as a new version so history remains append-only."""
    project = db.get(Project, project_id)
    if not project: raise HTTPException(404, "Project not found")
    current = db.get(DesignState, project_id)
    if not current: raise HTTPException(404, "Design state not found")
    restored = create_version(db, project_id, version.state, f"Restored from version {version.version_number}")
    current.state = version.state
    current.current_version_id = restored.id
    db.flush()
    return current
