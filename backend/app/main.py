"""FastAPI application entry point."""
from fastapi import FastAPI
from app.api.router import router
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", description="DesignOS BUILD 01 backend foundation")
app.include_router(router, prefix=settings.api_prefix)

@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Simple process health endpoint."""
    return {"status": "ok"}
