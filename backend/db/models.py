import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Text, JSON, Boolean, DateTime
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Analysis(Base):
    __tablename__ = "analyses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String, default="completed")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    gap_summary = Column(Text, nullable=True)
    improvement_suggestions = Column(JSON, nullable=True)
    questions = Column(JSON, nullable=True)
    is_flagged_by_verifier = Column(Boolean, default=False)
    unsupported_requirements = Column(JSON, nullable=True)

class ChunkBase(Base):
    __abstract__ = True
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(String, index=True, nullable=True) # UUID as string, nullable for now if we just test chunks
    text = Column(Text, nullable=False)
    embedding = Column(Vector(384), nullable=False) # 384 dims for all-MiniLM-L6-v2
    section_type = Column(String, nullable=False)
    chunk_id = Column(String, nullable=False, unique=True)
    source = Column(String, nullable=False)
    
class ResumeChunk(ChunkBase):
    __tablename__ = "resume_chunks"

class JDChunk(ChunkBase):
    __tablename__ = "jd_chunks"
