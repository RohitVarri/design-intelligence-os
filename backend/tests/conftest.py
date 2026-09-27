"""Test fixtures using isolated in-memory SQLite."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.database import Base, get_db
from app.main import app as fastapi_app
from app import models  # noqa: F401
from app.core.actors import ActorContext, ActorType, get_actor_context

@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    def override_db():
        db = TestingSession()
        try: yield db
        finally: db.close()
    fastapi_app.dependency_overrides[get_db] = override_db
    fastapi_app.dependency_overrides[get_actor_context] = lambda: ActorContext(ActorType.USER, actor_id="test-user", trusted=True, test_only=True)
    with TestClient(fastapi_app) as test_client: yield test_client
    fastapi_app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()
