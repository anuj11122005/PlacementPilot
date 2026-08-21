from sqlalchemy import create_engine, text; engine = create_engine('postgresql://postgres:postgres@localhost:5432/placementpilot');
with engine.connect() as conn:
    res = conn.execute(text("SELECT text FROM chunks WHERE analysis_id = 'e8218390-bd9a-4915-8666-4fc4ed3c3c8b' AND source = 'resume'"))
    print('\n---CHUNK---\n'.join([r[0] for r in res]))
