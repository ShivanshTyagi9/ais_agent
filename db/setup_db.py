"""
Database setup script — creates the ais_vessel_intel database and runs schema.sql.
Usage: python db/setup_db.py
"""

import os
import sys
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'ais_vessel_intel')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')


def create_database():
    """Create the database if it doesn't exist."""
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        dbname='postgres'
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Check if database exists
    cur.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)
    )
    if cur.fetchone():
        print(f"[OK] Database '{DB_NAME}' already exists.")
    else:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
        print(f"[OK] Created database '{DB_NAME}'.")

    cur.close()
    conn.close()


def run_schema():
    """Execute schema.sql against the target database."""
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(schema_path, 'r') as f:
        schema_sql = f.read()

    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        dbname=DB_NAME
    )
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(schema_sql)
    print("[OK] Schema applied successfully.")

    # Verify PostGIS
    cur.execute("SELECT PostGIS_Version();")
    version = cur.fetchone()[0]
    print(f"[OK] PostGIS version: {version}")

    # List tables
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name;
    """)
    tables = [row[0] for row in cur.fetchall()]
    print(f"[OK] Tables created: {', '.join(tables)}")

    cur.close()
    conn.close()


if __name__ == '__main__':
    print("=" * 60)
    print("AIS Vessel Intelligence — Database Setup")
    print("=" * 60)

    try:
        create_database()
        run_schema()
        print("\n[SUCCESS] Database is ready.")
    except Exception as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
