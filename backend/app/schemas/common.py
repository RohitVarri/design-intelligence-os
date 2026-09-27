"""Shared schema configuration."""
from pydantic import BaseModel, ConfigDict

class ORMModel(BaseModel):
    """Schema that can read SQLAlchemy model attributes."""
    model_config = ConfigDict(from_attributes=True)
