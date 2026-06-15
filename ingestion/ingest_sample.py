"""
Quick ingestion of a small subset (50K rows) for dev/testing.
Usage: python ingestion/ingest_sample.py
"""

import os
import sys
import io
import time
import psycopg2
import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'ais_vessel_intel')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')

SAMPLE_SIZE = 500_000


def get_connection():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        dbname=DB_NAME
    )
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC';")
    conn.commit()
    return conn


def ingest_sample(csv_path):
    print(f"\n{'='*60}")
    print(f"AIS Sample Ingestion ({SAMPLE_SIZE:,} rows)")
    print(f"{'='*60}")
    print(f"Source: {csv_path}")

    # Read only the first SAMPLE_SIZE rows
    print(f"Reading {SAMPLE_SIZE:,} rows...")
    df = pd.read_csv(csv_path, nrows=SAMPLE_SIZE,
                     dtype={'mmsi': 'Int64', 'vessel_type': 'Int16',
                            'status': 'Int16', 'cargo': 'Int16'},
                     low_memory=False)
    print(f"Read {len(df):,} rows. Columns: {list(df.columns)}")

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    # Truncate existing data
    cur.execute("SELECT COUNT(*) FROM ais_positions")
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"[INFO] Truncating existing {existing:,} rows...")
        cur.execute("TRUNCATE TABLE ais_positions")
        cur.execute("TRUNCATE TABLE vessels")
        conn.commit()

    start_time = time.time()

    # ── 1. Insert positions ──
    print("Inserting positions...")
    df['base_date_time'] = pd.to_datetime(df['base_date_time'], errors='coerce')
    valid = df.dropna(subset=['mmsi', 'base_date_time']).copy()

    pos_cols = ['mmsi', 'base_date_time', 'longitude', 'latitude',
                'sog', 'cog', 'heading', 'status', 'draft']
    pos_data = valid[pos_cols].copy()
    pos_data['mmsi'] = pos_data['mmsi'].astype('Int64')

    buf = io.StringIO()
    pos_data.to_csv(buf, sep='\t', header=False, index=False, na_rep='')
    buf.seek(0)

    copy_sql = """
        COPY ais_positions (mmsi, base_date_time, longitude, latitude,
                            sog, cog, heading, status, draft)
        FROM STDIN WITH (FORMAT text, NULL '')
    """
    cur.copy_expert(copy_sql, buf)
    conn.commit()
    print(f"[OK] Inserted {len(valid):,} position rows.")

    # ── 2. Upsert vessels ──
    print("Upserting vessels...")
    vessel_cols = ['mmsi', 'vessel_name', 'imo', 'call_sign',
                   'vessel_type', 'length', 'width', 'cargo', 'transceiver']
    vessels = valid[vessel_cols].drop_duplicates(subset=['mmsi'])

    # Filter to rows with identity info
    mask = (
        (vessels['vessel_name'].notna() & (vessels['vessel_name'].astype(str).str.strip() != '')) |
        (vessels['imo'].notna() & (vessels['imo'].astype(str).str.strip() != '')) |
        (vessels['call_sign'].notna() & (vessels['call_sign'].astype(str).str.strip() != ''))
    )
    vessels = vessels[mask]

    def clean_str(v):
        if pd.isna(v) or str(v).strip() == '':
            return None
        return str(v).strip()

    def clean_num(v, cast=int):
        if pd.isna(v):
            return None
        try:
            return cast(v)
        except (ValueError, TypeError):
            return None

    upsert_sql = """
        INSERT INTO vessels (mmsi, vessel_name, imo, call_sign,
                            vessel_type, length, width, cargo, transceiver, last_updated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (mmsi) DO UPDATE SET
            vessel_name = COALESCE(NULLIF(EXCLUDED.vessel_name, ''), vessels.vessel_name),
            imo = COALESCE(NULLIF(EXCLUDED.imo, ''), vessels.imo),
            call_sign = COALESCE(NULLIF(EXCLUDED.call_sign, ''), vessels.call_sign),
            vessel_type = COALESCE(EXCLUDED.vessel_type, vessels.vessel_type),
            length = COALESCE(EXCLUDED.length, vessels.length),
            width = COALESCE(EXCLUDED.width, vessels.width),
            cargo = COALESCE(EXCLUDED.cargo, vessels.cargo),
            transceiver = COALESCE(NULLIF(EXCLUDED.transceiver, ''), vessels.transceiver),
            last_updated = NOW()
    """

    for _, row in vessels.iterrows():
        cur.execute(upsert_sql, (
            int(row['mmsi']),
            clean_str(row.get('vessel_name')),
            clean_str(row.get('imo')),
            clean_str(row.get('call_sign')),
            clean_num(row.get('vessel_type'), int),
            clean_num(row.get('length'), float),
            clean_num(row.get('width'), float),
            clean_num(row.get('cargo'), int),
            clean_str(row.get('transceiver')),
        ))
    conn.commit()
    print(f"[OK] Upserted {len(vessels):,} vessels.")

    # ── 3. Populate geom ──
    print("Building spatial geometry column...")
    cur.execute("""
        UPDATE ais_positions
        SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
        WHERE longitude IS NOT NULL AND latitude IS NOT NULL AND geom IS NULL
    """)
    conn.commit()
    print(f"[OK] Geom set for {cur.rowcount:,} rows.")

    # ── 4. Deduplicate ──
    print("Deduplicating...")
    cur.execute("""
        DELETE FROM ais_positions a
        USING ais_positions b
        WHERE a.ctid < b.ctid
          AND a.mmsi = b.mmsi
          AND a.base_date_time = b.base_date_time
    """)
    dupes = cur.rowcount
    conn.commit()
    print(f"[OK] Removed {dupes:,} duplicates.")

    # ── Summary ──
    elapsed = time.time() - start_time
    cur.execute("SELECT COUNT(*) FROM ais_positions")
    pos_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM vessels")
    vessel_count = cur.fetchone()[0]
    cur.execute("SELECT MIN(base_date_time), MAX(base_date_time) FROM ais_positions")
    time_range = cur.fetchone()

    cur.close()
    conn.close()

    print(f"\n{'='*60}")
    print(f"INGESTION COMPLETE")
    print(f"{'='*60}")
    print(f"Positions:      {pos_count:,}")
    print(f"Vessels:         {vessel_count:,}")
    print(f"Duplicates:      {dupes:,}")
    print(f"Time range:      {time_range[0]} → {time_range[1]}")
    print(f"Elapsed:         {elapsed:.1f}s")


if __name__ == '__main__':
    csv_path = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\shive\Downloads\ais-2025-12-24.csv'
    if not os.path.exists(csv_path):
        print(f"[ERROR] CSV not found: {csv_path}")
        sys.exit(1)
    ingest_sample(csv_path)
