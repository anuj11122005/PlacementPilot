import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

class AnalysisResponse(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    
    gap_summary: Optional[str] = None
    improvement_suggestions: Optional[List[str]] = None
    questions: Optional[List[str]] = None
    is_flagged_by_verifier: bool = False
    unsupported_requirements: Optional[List[str]] = None

    class Config:
        from_attributes = True

class HealthResponse(BaseModel):
    status: str
    service: str
