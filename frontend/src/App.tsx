import React, { useState, useRef, useEffect } from 'react';
import { CheckCircle, AlertTriangle, ShieldCheck, FileSearch, UploadCloud, X } from 'lucide-react';
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

const LOADING_STAGES = [
  "Parsing resume & job description...",
  "Retrieving relevant context...",
  "Generating strict gap analysis...",
  "Fact-checking results with Verifier..."
];

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [jdText, setJdText] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState(0);
  const [error, setError] = useState('');
  const [fileError, setFileError] = useState('');
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (loading) {
      setLoadingStep(0);
      interval = setInterval(() => {
        setLoadingStep((prev) => Math.min(prev + 1, LOADING_STAGES.length - 1));
      }, 3500); // Progress to next cosmetic stage every 3.5 seconds
    }
    return () => clearInterval(interval);
  }, [loading]);

  const validateAndSetFile = (selectedFile: File) => {
    setFileError('');
    if (selectedFile.size > 5 * 1024 * 1024) {
      setFileError('File exceeds 5MB limit.');
      return;
    }
    const validTypes = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'];
    if (!validTypes.includes(selectedFile.type) && !selectedFile.name.endsWith('.pdf') && !selectedFile.name.endsWith('.docx')) {
      setFileError('Invalid file type. Only PDF and DOCX are supported.');
      return;
    }
    setFile(selectedFile);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError('Please provide a resume.');
      return;
    }
    if (jdText.length < 50) {
      setError('Job description must be at least 50 characters.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    const formData = new FormData();
    formData.append('resume', file);
    formData.append('jd_text', jdText);

    try {
      const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const response = await fetch(`${API_BASE_URL}/analyze`, {
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

  const clearFile = () => {
    setFile(null);
    setFileError('');
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <div className="container">
      <header>
        <h1>PlacementPilot</h1>
        <p className="subtitle">Strict Fact-Checked Gap Analysis</p>
      </header>

      {error && (
        <div className="error-alert animate-fade-in-up">
          <div>
            <AlertTriangle size={20} style={{ verticalAlign: 'middle', marginRight: '0.5rem' }} />
            {error}
          </div>
          <button onClick={() => setError('')}>Try Again</button>
        </div>
      )}

      {!result && !loading && (
        <form onSubmit={handleAnalyze} className="glass-panel">
          <div className="form-group">
            <label>Upload Resume (PDF/DOCX)</label>
            {!file ? (
              <div 
                className={`dropzone ${isDragging ? 'drag-active' : ''}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
              >
                <UploadCloud size={32} style={{ marginBottom: '0.5rem' }} />
                <p>Drag and drop your resume here, or click to browse</p>
                <p style={{ fontSize: '0.8rem', marginTop: '0.25rem' }}>Supports PDF and DOCX up to 5MB</p>
                <input 
                  type="file" 
                  accept=".pdf,.docx" 
                  ref={fileInputRef}
                  style={{ display: 'none' }}
                  onChange={(e) => {
                    if (e.target.files?.[0]) validateAndSetFile(e.target.files[0]);
                  }} 
                />
              </div>
            ) : (
              <div className="file-selected">
                <span>{file.name}</span>
                <button type="button" className="clear-btn" onClick={clearFile} aria-label="Clear file">
                  <X size={18} />
                </button>
              </div>
            )}
            {fileError && <div style={{ color: 'var(--danger)', fontSize: '0.875rem', marginTop: '0.5rem' }}>{fileError}</div>}
          </div>
          <div className="form-group">
            <label>Target Job Description</label>
            <textarea 
              rows={6} 
              placeholder="Paste the job description here..."
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
            />
            <span className={`char-counter ${jdText.length >= 50 ? 'valid' : 'invalid'}`}>
              {jdText.length}/50 characters {jdText.length < 50 ? '— add more detail' : '— looks good'}
            </span>
          </div>
          <button type="submit" className="btn" disabled={!file || jdText.length < 50}>
            <FileSearch size={20} />
            Analyze Match
          </button>
        </form>
      )}

      {loading && (
        <div className="glass-panel loader animate-fade-in-up">
          <div className="spinner"></div>
          <p className="loading-stage">{LOADING_STAGES[loadingStep]}</p>
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
            <div className="section animate-fade-in-up">
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
            <div className="refusal-block animate-fade-in-up">
              <h4><AlertTriangle size={24} /> Completely Unsupported</h4>
              <p>The candidate's resume does not provide enough context to evaluate ANY of the required skills.</p>
            </div>
          )}

          {result.unsupported_requirements && result.unsupported_requirements.length > 0 && (
            <div className="section animate-fade-in-up" style={{ marginTop: '2rem' }}>
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
