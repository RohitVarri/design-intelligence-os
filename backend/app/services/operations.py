"""Design-operation proposal boundary; proposals are recorded but never execute state edits."""
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.operation import DesignOperation, OperationActor, OperationStatus, OperationSource, OperationType
from app.models.project import Project
from app.schemas.operation import OperationCreate
from app.core.actors import ActorContext
from app.services.operation_executor import OperationExecutor

class OperationService:
    def create_proposal(self, db: Session, project_id: uuid.UUID, data: OperationCreate, actor: ActorContext, executor: OperationExecutor | None = None) -> DesignOperation:
        executor = executor or OperationExecutor()
        return executor.propose(db, project_id, data, actor)

    def record_human_selection(self, db: Session, project_id: uuid.UUID, direction_id: uuid.UUID, direction_name: str, previous_status: str) -> DesignOperation:
        """Record the user's explicit direction choice as the applied operation event."""
        operation = DesignOperation(project_id=project_id, operation_type=OperationType.SELECT_DIRECTION,
            actor=OperationActor.USER, target=f"design_direction:{direction_id}", property="status",
            old_value=previous_status, new_value="selected", scope="project",
            reason=f"User explicitly selected the design direction '{direction_name}'.",
            source=OperationSource.USER_REQUEST, status=OperationStatus.APPLIED)
        db.add(operation); db.flush(); return operation

    def list(self, db: Session, project_id: uuid.UUID) -> list[DesignOperation]:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        return list(db.scalars(select(DesignOperation).where(DesignOperation.project_id == project_id).order_by(DesignOperation.created_at.desc())))

operation_service = OperationService()
