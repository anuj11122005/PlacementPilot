import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import os
import sys

# Connect to the default 'postgres' database to create 'placementpilot'
try:
    conn = psycopg2.connect(
        dbname="postgres",
        user="postgres",
        password="postgres", # Try default password from SETUP.md
        host="127.0.0.1",
        port="5455"
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    
    # Check if placementpilot exists
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = 'placementpilot'")
    if not cursor.fetchone():
        print("Creating placementpilot database...")
        cursor.execute('CREATE DATABASE placementpilot')
    else:
        print("placementpilot database already exists.")
        
    cursor.close()
    conn.close()
    
    # Now connect to placementpilot to create the vector extension
    conn = psycopg2.connect(
        dbname="placementpilot",
        user="postgres",
        password="postgres",
        host="127.0.0.1",
        port="5455"
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    print("Vector extension created.")
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
