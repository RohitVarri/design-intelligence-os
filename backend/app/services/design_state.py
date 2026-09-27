"""Structured design-state operations."""
import uuid
from typing import Any
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.design_state import DesignState
from app.models.project import Project
from app.models.version import DesignVersion
from app.services.versioning import create_version

DEFAULT_STATE: dict[str, Any] = {"pages": [], "components": [], "design_tokens": {}, "ux_navigation": {}, "assets": [], "design_laws": [], "metadata": {}, "direction_selection": {}, "design_plan": {}}

def create_initial_design_state(db: Session, project_id: uuid.UUID) -> DesignState:
    """Create an empty state with the first recoverable version; idempotency conflicts are explicit."""
    if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
    if db.get(DesignState, project_id): raise HTTPException(409, "Design state already exists")
    version = create_version(db, project_id, DEFAULT_STATE.copy(), "Initial design state")
    state = DesignState(project_id=project_id, state=DEFAULT_STATE.copy(), current_version_id=version.id)
    db.add(state)
    db.flush()
    return state

def get_design_state(db: Session, project_id: uuid.UUID) -> DesignState:
    """Return current project state or 404."""
    state = db.get(DesignState, project_id)
    if not state: raise HTTPException(404, "Design state not found")
    return state

def update_design_state(db: Session, project_id: uuid.UUID, state_data: dict[str, Any], summary: str) -> DesignState:
    """Persist state update and its full snapshot in the same transaction."""
    current = get_design_state(db, project_id)
    version = create_version(db, project_id, state_data, summary)
    current.state = state_data
    current.current_version_id = version.id
    db.flush()
    return current

def surgical_edit(db: Session, project_id: uuid.UUID, path: str, value: Any, summary: str) -> DesignState:
    """Apply one dot-path update to a deep copy, preserving all other state."""
    import copy
    state = get_design_state(db, project_id)
    updated = copy.deepcopy(state.state)
    parts = path.split(".")
    node: Any = updated
    try:
        for part in parts[:-1]: node = node[int(part)] if isinstance(node, list) else node[part]
        key = parts[-1]
        if isinstance(node, list): node[int(key)] = value
        else: node[key] = value
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise HTTPException(422, f"Invalid edit path: {path}") from exc
    return update_design_state(db, project_id, updated, summary)
