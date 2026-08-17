import pytest
import os
import sys
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app, get_db
from generation.generator import GroundedGenerator
from schemas import AnalysisResponse

client = TestClient(app)

from datetime import datetime, timezone

def override_get_db():
    try:
        db = MagicMock(spec=Session)
        def mock_add(obj):
            if hasattr(obj, 'created_at') and getattr(obj, 'created_at', None) is None:
                obj.created_at = datetime.now(timezone.utc)
        db.add.side_effect = mock_add
        yield db
    finally:
        pass

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture
def mock_pipeline_components():
    with patch("main.generator", new_callable=MagicMock) as mock_generator, \
         patch("main.retriever", new_callable=MagicMock) as mock_retriever, \
         patch("main.store", new_callable=MagicMock) as mock_store, \
         patch("main.embedder", new_callable=MagicMock) as mock_embedder:
        
        yield mock_generator, mock_retriever, mock_store, mock_embedder

def test_full_mismatch_short_circuit(mock_pipeline_components, tmp_path):
    """
    Test that when all JD chunks return unconfident, the pipeline short-circuits
    and returns a full refusal without calling the generator,
    matching RULES.md Rule 4.
    """
    mock_generator, mock_retriever, mock_store, mock_embedder = mock_pipeline_components
    
    # Setup mock retriever to always return is_confident=False
    mock_retriever.search.return_value = {
        "is_confident": False,
        "chunks": [],
        "confidence_score": 0.2,
        "metrics": {"top_1_similarity": 0.2, "section_bonus": 0.0, "bm25_bonus": 0.0}
    }
    
    # Create a dummy resume PDF
    dummy_pdf_path = tmp_path / "dummy_resume.pdf"
    dummy_pdf_path.write_bytes(b"dummy pdf content")
    
    with patch("main.parse_resume", return_value="Resume text"):
        with patch("main.parse_jd", return_value="Unrelated JD text"):
            with patch("main.chunk_text") as mock_chunk:
                # Mock chunk_text to return valid chunks
                def side_effect_chunk(text, source):
                    if source == "resume":
                        return [{"chunk_id": "r1", "text": "Resume text", "section_type": "general", "source": "resume"}]
                    return [{"chunk_id": "j1", "text": "Unrelated JD text", "section_type": "general", "source": "jd"}]
                mock_chunk.side_effect = side_effect_chunk
                
                with open(dummy_pdf_path, "rb") as f:
                    response = client.post(
                        "/analyze",
                        data={"jd_text": "Need unrelated skills"},
                        files={"resume": ("dummy_resume.pdf", f, "application/pdf")}
                    )

    assert response.status_code == 200
    data = response.json()
    
    # Verify the fast path refusal occurred
    assert data["gap_summary"] == GroundedGenerator.REFUSAL_STRING
    assert data["unsupported_requirements"] == ["Unrelated JD text"]
    
    # Verify the LLM was not called
    mock_generator.generate.assert_not_called()
