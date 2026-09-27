"""Revision-scoped research plan execution using the injected model runtime."""
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.actors import ActorContext
from app.models.intent import ProjectIntent
from app.models.intent import IntentStatus
from app.models.project import Project
from app.models.research_evidence import EvidenceSourceType, EvidenceTrust, ResearchEvidence
from app.models.research_plan import ResearchPlan, ResearchPlanStatus
from app.models.research_query import ResearchQuery, ResearchQueryStatus
from app.models.research_run import ResearchAttempt, ResearchAttemptStatus, ResearchResult, ResearchRun, ResearchRunStatus
from app.providers.contracts import TaskType
from app.providers.runtime import ProviderRuntime
from app.providers.schemas import ResearchResultsOutput
from app.services.intent import IntentExtractionService


class ResearchExecutionService:
    def execute_plan(self, db: Session, project_id: uuid.UUID, plan_id: uuid.UUID, runtime: ProviderRuntime, actor: ActorContext) -> ResearchRun:
        project = db.get(Project, project_id)
        if not project: raise HTTPException(404, "Project not found")
        plan = db.scalar(select(ResearchPlan).where(ResearchPlan.id == plan_id, ResearchPlan.project_id == project_id))
        if not plan: raise HTTPException(404, "Research plan not found")
        if project.current_intent_id != plan.intent_id:
            raise HTTPException(409, "Research plan is based on a stale intent revision")
        run = ResearchRun(project_id=project_id, intent_id=plan.intent_id, plan_id=plan.id, provider="task-router", status=ResearchRunStatus.RUNNING, started_at=datetime.now(timezone.utc))
        plan.status = ResearchPlanStatus.RUNNING
        db.add(run); db.flush()
        queries = db.scalars(select(ResearchQuery).where(ResearchQuery.plan_id == plan.id, ResearchQuery.status != ResearchQueryStatus.SKIPPED).order_by(ResearchQuery.created_at)).all()
        succeeded = 0
        for query in queries:
            attempt = ResearchAttempt(run_id=run.id, query_id=query.id, attempt_number=1, provider="task-router", status=ResearchAttemptStatus.RUNNING)
            db.add(attempt); db.flush()
            outcome = runtime.execute_sync(db, project_id=project_id, intent_id=plan.intent_id, task=TaskType.RESEARCH_QUERY,
                payload={"query":query.query, "research_area":query.research_area, "reason":query.reason},
                output_schema=ResearchResultsOutput, actor=actor, context_references={"plan_id":str(plan.id), "query_id":str(query.id)})
            attempt.ai_run_id = outcome.run.id
            attempt.provider = outcome.run.provider
            attempt.completed_at = datetime.now(timezone.utc)
            if outcome.accepted and outcome.candidate:
                payload = outcome.candidate.payload
                for item in payload.get("results", []):
                    result = ResearchResult(attempt_id=attempt.id, query_id=query.id, title=item["title"], claim=item["claim"],
                        source_name=item.get("source_name"), source_url=item.get("source_url"), citation=item.get("citation", {}),
                        raw_result_reference=outcome.run.output_reference, raw_result=item, status="untrusted")
                    db.add(result); db.flush()
                    evidence = ResearchEvidence(project_id=project_id, intent_id=plan.intent_id, result_id=result.id, title=result.title,
                        claim=result.claim, source_url=result.source_url, source_name=result.source_name, source_type=EvidenceSourceType.OTHER,
                        evidence=item["evidence"], related_requirement=item.get("related_requirement"), trust=EvidenceTrust.UNTRUSTED,
                        provenance={"source_type":"provider_result", "created_by":"ai", "ai_run_id":str(outcome.run.id), "research_run_id":str(run.id),
                                    "query_id":str(query.id), "result_id":str(result.id), "trust_reason":"Provider research is untrusted until review."})
                    db.add(evidence)
                attempt.status = ResearchAttemptStatus.SUCCEEDED
                query.status = ResearchQueryStatus.COMPLETED
                succeeded += 1
            else:
                attempt.status = ResearchAttemptStatus.MALFORMED if outcome.run.status.value == "malformed" else ResearchAttemptStatus.FAILED
                attempt.error = outcome.run.error or "Provider output rejected"
                query.status = ResearchQueryStatus.FAILED
            db.flush()
        run.completed_at = datetime.now(timezone.utc)
        run.status = ResearchRunStatus.SUCCEEDED if succeeded == len(queries) and queries else ResearchRunStatus.PARTIAL if succeeded else ResearchRunStatus.FAILED
        plan.status = ResearchPlanStatus.COMPLETED if succeeded == len(queries) and queries else ResearchPlanStatus.FAILED if not succeeded else ResearchPlanStatus.COMPLETED
        if run.status == ResearchRunStatus.SUCCEEDED:
            intent = db.get(ProjectIntent, plan.intent_id)
            if intent and intent.status == IntentStatus.READY_FOR_RESEARCH:
                IntentExtractionService.transition_status(intent, IntentStatus.RESEARCHED, actor="system", reason="Research plan completed successfully")
        db.flush()
        return run


research_execution_service = ResearchExecutionService()
