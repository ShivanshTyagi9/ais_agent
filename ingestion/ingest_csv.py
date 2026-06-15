"""
Bulk CSV ingestion for AIS position data.
Loads ais-2025-12-24.csv (~8.6M rows) into PostgreSQL using chunked COPY for speed.

OPTIMIZED: Uses pandas to_csv → StringIO → COPY FROM STDIN for ~10-20x speedup
over row-by-row iteration.

Usage: python ingestion/ingest_csv.py [path_to_csv]
"""

import os
import sys
import io
import time
import math
import psycopg2
import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'ais_vessel_intel')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')

CHUNK_SIZE = 100_000  # rows per chunk (larger = faster with vectorized approach)


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


def count_csv_lines(csv_path):
    """Fast line count for progress bar."""
    count = 0
    with open(csv_path, 'rb') as f:
        for _ in f:
            count += 1
    return count - 1  # subtract header


def ingest_positions(chunk_df, cur):
    """Bulk insert position rows using COPY via pandas to_csv → StringIO."""
    pos_cols = ['mmsi', 'base_date_time', 'longitude', 'latitude',
                'sog', 'cog', 'heading', 'status', 'draft']

    # Parse timestamps
    chunk_df['base_date_time'] = pd.to_datetime(
        chunk_df['base_date_time'], errors='coerce'
    )

    # Drop rows with no timestamp or mmsi
    valid = chunk_df.dropna(subset=['mmsi', 'base_date_time']).copy()
    if len(valid) == 0:
        return 0

    # Select and prepare position columns
    pos_data = valid[pos_cols].copy()
    pos_data['mmsi'] = pos_data['mmsi'].astype('Int64')

    # Write to StringIO as tab-separated (vectorized, much faster than iterrows)
    buf = io.StringIO()
    pos_data.to_csv(buf, sep='\t', header=False, index=False, na_rep='')
    buf.seek(0)

    copy_sql = """
        COPY ais_positions (mmsi, base_date_time, longitude, latitude,
                            sog, cog, heading, status, draft)
        FROM STDIN WITH (FORMAT text, NULL '')
    """
    cur.copy_expert(copy_sql, buf)
    return len(valid)


def upsert_vessels(chunk_df, cur):
    """Upsert vessel identity info (vectorized extraction, batch execute)."""
    vessel_cols = ['mmsi', 'vessel_name', 'imo', 'call_sign',
                   'vessel_type', 'length', 'width', 'cargo', 'transceiver']

    # Only keep rows with some identity info
    has_cols = [c for c in ['vessel_name', 'imo', 'call_sign'] if c in chunk_df.columns]
    if not has_cols:
        return 0

    vessels = chunk_df[vessel_cols].drop_duplicates(subset=['mmsi']).copy()

    # Filter to rows that have at least one identity field
    mask = pd.Series(False, index=vessels.index)
    for col in has_cols:
        mask |= vessels[col].notna() & (vessels[col].astype(str).str.strip() != '')
    vessels = vessels[mask]

    if len(vessels) == 0:
        return 0

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

    # Build params list (vectorized)
    def clean_str(v):
        if pd.isna(v) or str(v).strip() == '':
            return None
        return str(v).strip()

    def clean_int(v):
        if pd.isna(v):
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    def clean_float(v):
        if pd.isna(v):
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    params_list = []
    for _, row in vessels.iterrows():
        params_list.append((
            int(row['mmsi']),
            clean_str(row.get('vessel_name')),
            clean_str(row.get('imo')),
            clean_str(row.get('call_sign')),
            clean_int(row.get('vessel_type')),
            clean_float(row.get('length')),
            clean_float(row.get('width')),
            clean_int(row.get('cargo')),
            clean_str(row.get('transceiver')),
        ))

    cur.executemany(upsert_sql, params_list)
    return len(params_list)


def ingest_csv(csv_path):
    """Main ingestion function."""
    print(f"\n{'='*60}")
    print(f"AIS CSV Ingestion (Optimized)")
    print(f"{'='*60}")
    print(f"Source: {csv_path}")
    file_size_mb = os.path.getsize(csv_path) / (1024 * 1024)
    print(f"File size: {file_size_mb:.1f} MB")

    # Count lines for progress bar
    print("Counting rows (fast binary scan)...")
    total_rows = count_csv_lines(csv_path)
    print(f"Total rows: {total_rows:,}")

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    # Check current row count
    cur.execute("SELECT COUNT(*) FROM ais_positions")
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"\n[INFO] ais_positions already has {existing:,} rows. Truncating...")
        cur.execute("TRUNCATE TABLE ais_positions")
        cur.execute("TRUNCATE TABLE vessels")
        conn.commit()
        print("[OK] Tables truncated.")

    rows_inserted = 0
    vessels_upserted = 0
    start_time = time.time()

    pbar = tqdm(total=total_rows, unit='rows', desc='Ingesting',
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]')

    for chunk_df in pd.read_csv(csv_path, chunksize=CHUNK_SIZE,
                                 dtype={'mmsi': 'Int64', 'vessel_type': 'Int16',
                                        'status': 'Int16', 'cargo': 'Int16'},
                                 low_memory=False):

        # 1. Bulk insert positions (fast: pandas to_csv → COPY)
        n_inserted = ingest_positions(chunk_df, cur)
        rows_inserted += n_inserted

        # 2. Upsert vessels (slower but small volume)
        n_vessels = upsert_vessels(chunk_df, cur)
        vessels_upserted += n_vessels

        conn.commit()
        pbar.update(len(chunk_df))

    pbar.close()

    # 3. Populate geom column from lon/lat
    print("\nBuilding spatial geometry column (geom)...")
    t0 = time.time()
    cur.execute("""
        UPDATE ais_positions
        SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
        WHERE longitude IS NOT NULL
          AND latitude IS NOT NULL
          AND geom IS NULL
    """)
    geom_updated = cur.rowcount
    conn.commit()
    print(f"[OK] Geom populated for {geom_updated:,} rows ({time.time()-t0:.1f}s).")

    # 4. Deduplicate
    print("Removing duplicates on (mmsi, base_date_time)...")
    t0 = time.time()
    cur.execute("""
        DELETE FROM ais_positions a
        USING ais_positions b
        WHERE a.ctid < b.ctid
          AND a.mmsi = b.mmsi
          AND a.base_date_time = b.base_date_time
    """)
    dupes_removed = cur.rowcount
    conn.commit()
    print(f"[OK] Removed {dupes_removed:,} duplicate rows ({time.time()-t0:.1f}s).")

    # Summary
    elapsed = time.time() - start_time
    cur.execute("SELECT COUNT(*) FROM ais_positions")
    final_pos_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM vessels")
    final_vessel_count = cur.fetchone()[0]

    cur.close()
    conn.close()

    print(f"\n{'='*60}")
    print(f"INGESTION COMPLETE")
    print(f"{'='*60}")
    print(f"Positions loaded:    {final_pos_count:,}")
    print(f"Vessels catalogued:  {final_vessel_count:,}")
    print(f"Duplicates removed:  {dupes_removed:,}")
    print(f"Time elapsed:        {elapsed/60:.1f} minutes")
    print(f"Throughput:          {rows_inserted/max(elapsed,1):,.0f} rows/sec")


if __name__ == '__main__':
    csv_path = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\shive\Downloads\ais-2025-12-24.csv'

    if not os.path.exists(csv_path):
        print(f"[ERROR] CSV not found: {csv_path}")
        sys.exit(1)

    ingest_csv(csv_path)
