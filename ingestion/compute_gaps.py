"""
AIS Gap Detection — Computes signal gaps ("dark activity") per vessel.
Populates the ais_gaps table.

Algorithm (Section 6 of the plan):
1. For each vessel, compute time deltas between consecutive positions
2. Flag gaps exceeding the threshold (default 30 min)
3. Compute jump distance and implied speed
4. Store in ais_gaps

Usage: python ingestion/compute_gaps.py [--threshold 30]
"""

import os
import sys
import time
import argparse
import psycopg2
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'ais_vessel_intel')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')

BATCH_SIZE = 500  # process this many vessels at a time


def get_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        dbname=DB_NAME
    )


def compute_gaps(threshold_minutes=10):
    """Compute AIS gaps for all vessels."""
    print(f"\n{'='*60}")
    print(f"AIS Gap Detection (threshold: {threshold_minutes} min)")
    print(f"{'='*60}")

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    # Clear existing gaps
    cur.execute("TRUNCATE TABLE ais_gaps")
    conn.commit()
    print("[OK] Cleared existing ais_gaps table.")

    # Get distinct vessel MMSIs
    cur.execute("SELECT DISTINCT mmsi FROM ais_positions ORDER BY mmsi")
    all_mmsis = [row[0] for row in cur.fetchall()]
    print(f"[OK] Found {len(all_mmsis):,} distinct vessels.")

    total_gaps = 0
    start_time = time.time()

    pbar = tqdm(total=len(all_mmsis), unit='vessels', desc='Computing gaps')

    # Process in batches to keep memory usage reasonable
    for i in range(0, len(all_mmsis), BATCH_SIZE):
        batch = all_mmsis[i:i+BATCH_SIZE]

        # Use window function to compute gaps for the entire batch at once
        # This SQL finds consecutive position pairs with time delta > threshold
        cur.execute("""
            INSERT INTO ais_gaps (mmsi, gap_start, gap_end, duration_minutes,
                                  start_lat, start_lon, end_lat, end_lon,
                                  jump_distance_km, implied_speed_knots)
            SELECT
                mmsi,
                base_date_time AS gap_start,
                next_time AS gap_end,
                EXTRACT(EPOCH FROM (next_time - base_date_time)) / 60.0 AS duration_minutes,
                latitude AS start_lat,
                longitude AS start_lon,
                next_lat AS end_lat,
                next_lon AS end_lon,
                -- Great-circle distance in km using PostGIS
                ST_Distance(
                    ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography,
                    ST_SetSRID(ST_MakePoint(next_lon, next_lat), 4326)::geography
                ) / 1000.0 AS jump_distance_km,
                -- Implied speed: distance_km / duration_hours * 0.539957 (km/h to knots)
                CASE
                    WHEN EXTRACT(EPOCH FROM (next_time - base_date_time)) > 0 THEN
                        (ST_Distance(
                            ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography,
                            ST_SetSRID(ST_MakePoint(next_lon, next_lat), 4326)::geography
                        ) / 1000.0)
                        / (EXTRACT(EPOCH FROM (next_time - base_date_time)) / 3600.0)
                        * 0.539957
                    ELSE 0
                END AS implied_speed_knots
            FROM (
                SELECT
                    mmsi,
                    base_date_time,
                    latitude,
                    longitude,
                    LEAD(base_date_time) OVER (PARTITION BY mmsi ORDER BY base_date_time) AS next_time,
                    LEAD(latitude) OVER (PARTITION BY mmsi ORDER BY base_date_time) AS next_lat,
                    LEAD(longitude) OVER (PARTITION BY mmsi ORDER BY base_date_time) AS next_lon
                FROM ais_positions
                WHERE mmsi = ANY(%s)
                  AND latitude IS NOT NULL
                  AND longitude IS NOT NULL
            ) sub
            WHERE next_time IS NOT NULL
              AND EXTRACT(EPOCH FROM (next_time - base_date_time)) / 60.0 > %s
        """, (batch, threshold_minutes))

        batch_gaps = cur.rowcount
        total_gaps += batch_gaps
        conn.commit()
        pbar.update(len(batch))

    pbar.close()

    # Summary stats
    elapsed = time.time() - start_time
    cur.execute("""
        SELECT COUNT(*),
               ROUND(AVG(duration_minutes)::numeric, 1),
               ROUND(MAX(duration_minutes)::numeric, 1),
               ROUND(AVG(jump_distance_km)::numeric, 1)
        FROM ais_gaps
    """)
    stats = cur.fetchone()

    cur.close()
    conn.close()

    print(f"\n{'='*60}")
    print(f"GAP DETECTION COMPLETE")
    print(f"{'='*60}")
    print(f"Total gaps found:     {total_gaps:,}")
    print(f"Avg gap duration:     {stats[1]} min")
    print(f"Max gap duration:     {stats[2]} min")
    print(f"Avg jump distance:    {stats[3]} km")
    print(f"Time elapsed:         {elapsed/60:.1f} minutes")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Compute AIS gaps')
    parser.add_argument('--threshold', type=int, default=10,
                        help='Gap threshold in minutes (default: 10)')
    args = parser.parse_args()

    compute_gaps(args.threshold)
