import React, { useState } from 'react';
import { Upload, FileText, CheckCircle, AlertTriangle, ShieldCheck, FileSearch } from 'lucide-react';
import './index.css';

interface AnalysisResponse {
  id: string;
  status: string;
  gap_summary: string | null;
  improvement_suggestions: string[] | null;
  questions: string[] | null;
  is_flagged_by_verifier: boolean;
  unsupported_requirements: string[] | null;
}

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [jdText, setJdText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<AnalysisResponse | null>(null);

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !jdText) {
      setError('Please provide both a resume and a job description.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    const formData = new FormData();
    formData.append('resume', file);
    formData.append('jd_text', jdText);

    try {
      const response = await fetch('http://localhost:8000/analyze', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Analysis failed.');
      }

      const data: AnalysisResponse = await response.json();
      setResult(data);
    } catch (err: any) {
      setError(err.message || 'An unexpected error occurred.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <header>
        <h1>PlacementPilot</h1>
        <p className="subtitle">Strict Fact-Checked Gap Analysis</p>
      </header>

      {!result && !loading && (
        <form onSubmit={handleAnalyze} className="glass-panel">
          <div className="form-group">
            <label>Upload Resume (PDF/DOCX)</label>
            <input 
              type="file" 
              accept=".pdf,.docx" 
              onChange={(e) => setFile(e.target.files?.[0] || null)} 
            />
          </div>
          <div className="form-group">
            <label>Target Job Description</label>
            <textarea 
              rows={6} 
              placeholder="Paste the job description here..."
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
            />
          </div>
          {error && <div style={{ color: 'var(--danger)', marginBottom: '1rem' }}>{error}</div>}
          <button type="submit" className="btn" disabled={!file || !jdText}>
            <FileSearch size={20} />
            Analyze Match
          </button>
        </form>
      )}

      {loading && (
        <div className="glass-panel loader">
          <div className="spinner"></div>
          <p>Running multi-stage RAG pipeline & verifying claims...</p>
        </div>
      )}

      {result && (
        <div className="glass-panel">
          <button 
            className="btn" 
            style={{ marginBottom: '2rem', width: 'auto' }}
            onClick={() => setResult(null)}
          >
            New Analysis
          </button>

          {result.gap_summary !== "Not enough context to evaluate this." && (
            <div className="section">
              <h3 className="section-title"><CheckCircle size={24} color="var(--accent)" /> Confirmed Gap Analysis</h3>
              <div className="card">
                <p style={{ whiteSpace: 'pre-wrap' }}>{result.gap_summary}</p>
                {result.is_flagged_by_verifier && (
                  <div className="fact-checked-badge">
                    <ShieldCheck size={14} /> Fact-Checked by Verifier
                  </div>
                )}
              </div>

              {result.improvement_suggestions && result.improvement_suggestions.length > 0 && (
                <>
                  <h3 className="section-title" style={{ marginTop: '2rem' }}>Improvement Suggestions</h3>
                  <div className="card">
                    <ul>
                      {result.improvement_suggestions.map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                  </div>
                </>
              )}

              {result.questions && result.questions.length > 0 && (
                <>
                  <h3 className="section-title" style={{ marginTop: '2rem' }}>Targeted Interview Questions</h3>
                  <div className="card">
                    <ul>
                      {result.questions.map((q, i) => <li key={i}>{q}</li>)}
                    </ul>
                  </div>
                </>
              )}
            </div>
          )}

          {result.gap_summary === "Not enough context to evaluate this." && (
            <div className="refusal-block">
              <h4><AlertTriangle size={24} /> Completely Unsupported</h4>
              <p>The candidate's resume does not provide enough context to evaluate ANY of the required skills.</p>
            </div>
          )}

          {result.unsupported_requirements && result.unsupported_requirements.length > 0 && (
            <div className="section" style={{ marginTop: '2rem' }}>
              <h3 className="section-title" style={{ color: 'var(--danger)' }}><AlertTriangle size={24} /> Insufficient Context (Not Evaluated)</h3>
              <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem', fontSize: '0.9rem' }}>
                The following JD requirements were bypassed because the retriever could not confidently find supporting evidence in the resume. The LLM was not allowed to guess.
              </p>
              {result.unsupported_requirements.map((req, i) => (
                <div key={i} className="refusal-block">
                  <h4>Missing Evidence</h4>
                  <p>{req}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default App;
