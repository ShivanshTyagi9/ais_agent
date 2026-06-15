"""
Core vessel query functions — the 7 "tools" exposed to the OpenAI agent.
Each function wraps SQL and returns structured data (dicts/lists).
"""

import os
import json
from datetime import datetime, timedelta
from tools.db_connection import get_cursor

# Import visualization lazily to avoid circular deps
MAPS_DIR = os.path.join(os.path.dirname(__file__), '..', 'maps')
os.makedirs(MAPS_DIR, exist_ok=True)


# ─────────────────────────────────────────────
# Helper: resolve vessel name or MMSI
# ─────────────────────────────────────────────

def _resolve_identifier(cur, identifier: str) -> list[int]:
    """Resolve a vessel name or MMSI string to a list of MMSIs."""
    identifier = identifier.strip()

    # If it's numeric, treat as MMSI
    if identifier.isdigit():
        return [int(identifier)]

    # Otherwise, search by name (case-insensitive partial match)
    cur.execute("""
        SELECT mmsi, vessel_name FROM vessels
        WHERE LOWER(vessel_name) LIKE LOWER(%s)
        ORDER BY last_updated DESC
    """, (f'%{identifier}%',))
    results = cur.fetchall()

    if not results:
        return []
    return [row[0] for row in results]


def _format_timestamp(ts) -> str:
    """Format a timestamp for JSON output."""
    if ts is None:
        return None
    return ts.isoformat()


# ─────────────────────────────────────────────
# Tool 1: get_vessel_track
# ─────────────────────────────────────────────

def get_vessel_track(identifier: str, start_time: str, end_time: str) -> dict:
    """
    Get the path/track of a vessel between two timestamps.
    Returns ordered list of {timestamp, lat, lon, sog, cog, heading}.
    Limits to 2000 points; downsamples if more exist.
    """
    with get_cursor() as cur:
        mmsis = _resolve_identifier(cur, identifier)
        if not mmsis:
            return {"error": f"No vessel found matching '{identifier}'"}

        mmsi = mmsis[0]  # use first match

        # Count points in range
        cur.execute("""
            SELECT COUNT(*) FROM ais_positions
            WHERE mmsi = %s AND base_date_time BETWEEN %s AND %s
        """, (mmsi, start_time, end_time))
        total_points = cur.fetchone()[0]

        if total_points == 0:
            return {"error": f"No position data for MMSI {mmsi} in the given time range",
                    "mmsi": mmsi}

        # If too many points, sample evenly
        limit = 2000
        if total_points > limit:
            # Use ntile to evenly sample
            cur.execute("""
                SELECT timestamp, lat, lon, sog, cog, heading FROM (
                    SELECT
                        base_date_time AS timestamp,
                        latitude AS lat,
                        longitude AS lon,
                        sog, cog, heading,
                        ROW_NUMBER() OVER (
                            PARTITION BY NTILE(%s) OVER (ORDER BY base_date_time)
                            ORDER BY base_date_time
                        ) AS rn
                    FROM ais_positions
                    WHERE mmsi = %s AND base_date_time BETWEEN %s AND %s
                ) sub WHERE rn = 1
                ORDER BY timestamp
            """, (limit, mmsi, start_time, end_time))
        else:
            cur.execute("""
                SELECT base_date_time, latitude, longitude, sog, cog, heading
                FROM ais_positions
                WHERE mmsi = %s AND base_date_time BETWEEN %s AND %s
                ORDER BY base_date_time
            """, (mmsi, start_time, end_time))

        rows = cur.fetchall()

        # Get vessel name
        cur.execute("SELECT vessel_name FROM vessels WHERE mmsi = %s", (mmsi,))
        name_row = cur.fetchone()
        vessel_name = name_row[0] if name_row else None

        points = []
        for row in rows:
            points.append({
                "timestamp": _format_timestamp(row[0]),
                "lat": row[1],
                "lon": row[2],
                "sog": row[3],
                "cog": row[4],
                "heading": row[5]
            })

        return {
            "mmsi": mmsi,
            "vessel_name": vessel_name,
            "total_points_in_range": total_points,
            "points_returned": len(points),
            "start_time": _format_timestamp(rows[0][0]) if rows else None,
            "end_time": _format_timestamp(rows[-1][0]) if rows else None,
            "track": points
        }


# ─────────────────────────────────────────────
# Tool 2: get_vessel_position_at
# ─────────────────────────────────────────────

def get_vessel_position_at(identifier: str, timestamp: str) -> dict:
    """
    Get the nearest position record to a given timestamp.
    Returns the position with the actual time delta.
    """
    with get_cursor() as cur:
        mmsis = _resolve_identifier(cur, identifier)
        if not mmsis:
            return {"error": f"No vessel found matching '{identifier}'"}

        mmsi = mmsis[0]

        # Find the closest position (before or after)
        cur.execute("""
            (SELECT base_date_time, latitude, longitude, sog, cog, heading, status, draft,
                    ABS(EXTRACT(EPOCH FROM (base_date_time - %s::timestamptz))) AS delta_sec
             FROM ais_positions
             WHERE mmsi = %s AND base_date_time <= %s
             ORDER BY base_date_time DESC LIMIT 1)
            UNION ALL
            (SELECT base_date_time, latitude, longitude, sog, cog, heading, status, draft,
                    ABS(EXTRACT(EPOCH FROM (base_date_time - %s::timestamptz))) AS delta_sec
             FROM ais_positions
             WHERE mmsi = %s AND base_date_time > %s
             ORDER BY base_date_time ASC LIMIT 1)
            ORDER BY delta_sec LIMIT 1
        """, (timestamp, mmsi, timestamp, timestamp, mmsi, timestamp))

        row = cur.fetchone()
        if not row:
            return {"error": f"No position data found for MMSI {mmsi}",
                    "mmsi": mmsi}

        delta_minutes = round(row[8] / 60, 1)

        # Get vessel name
        cur.execute("SELECT vessel_name FROM vessels WHERE mmsi = %s", (mmsi,))
        name_row = cur.fetchone()

        return {
            "mmsi": mmsi,
            "vessel_name": name_row[0] if name_row else None,
            "requested_time": timestamp,
            "actual_time": _format_timestamp(row[0]),
            "time_delta_minutes": delta_minutes,
            "latitude": row[1],
            "longitude": row[2],
            "sog": row[3],
            "cog": row[4],
            "heading": row[5],
            "status": row[6],
            "draft": row[7]
        }


# ─────────────────────────────────────────────
# Tool 3: get_vessel_info
# ─────────────────────────────────────────────

def get_vessel_info(identifier: str) -> dict:
    """Get static vessel identity info."""
    with get_cursor() as cur:
        mmsis = _resolve_identifier(cur, identifier)
        if not mmsis:
            return {"error": f"No vessel found matching '{identifier}'"}

        results = []
        for mmsi in mmsis[:5]:  # limit to 5 matches
            cur.execute("""
                SELECT mmsi, vessel_name, imo, call_sign, vessel_type,
                       length, width, cargo, transceiver, last_updated
                FROM vessels WHERE mmsi = %s
            """, (mmsi,))
            row = cur.fetchone()
            if row:
                # Also get data coverage
                cur.execute("""
                    SELECT MIN(base_date_time), MAX(base_date_time), COUNT(*)
                    FROM ais_positions WHERE mmsi = %s
                """, (mmsi,))
                coverage = cur.fetchone()

                results.append({
                    "mmsi": row[0],
                    "vessel_name": row[1],
                    "imo": row[2],
                    "call_sign": row[3],
                    "vessel_type": row[4],
                    "length": row[5],
                    "width": row[6],
                    "cargo": row[7],
                    "transceiver": row[8],
                    "last_updated": _format_timestamp(row[9]),
                    "data_coverage": {
                        "first_position": _format_timestamp(coverage[0]),
                        "last_position": _format_timestamp(coverage[1]),
                        "total_reports": coverage[2]
                    }
                })

        if len(results) == 1:
            return results[0]
        return {"matches": results, "count": len(results)}


# ─────────────────────────────────────────────
# Tool 4: summarize_voyage
# ─────────────────────────────────────────────

def summarize_voyage(identifier: str, start_time: str, end_time: str) -> dict:
    """
    Summarize a vessel's voyage: total distance, avg/max SOG,
    bounding box, start/end positions, number of reports.
    """
    with get_cursor() as cur:
        mmsis = _resolve_identifier(cur, identifier)
        if not mmsis:
            return {"error": f"No vessel found matching '{identifier}'"}

        mmsi = mmsis[0]

        # Basic stats
        cur.execute("""
            SELECT
                COUNT(*) AS report_count,
                MIN(base_date_time) AS first_time,
                MAX(base_date_time) AS last_time,
                AVG(sog) AS avg_sog,
                MAX(sog) AS max_sog,
                MIN(latitude) AS min_lat,
                MAX(latitude) AS max_lat,
                MIN(longitude) AS min_lon,
                MAX(longitude) AS max_lon
            FROM ais_positions
            WHERE mmsi = %s AND base_date_time BETWEEN %s AND %s
        """, (mmsi, start_time, end_time))
        stats = cur.fetchone()

        if not stats or stats[0] == 0:
            return {"error": f"No data for MMSI {mmsi} in range",
                    "mmsi": mmsi}

        # Start and end positions
        cur.execute("""
            SELECT latitude, longitude, sog, base_date_time
            FROM ais_positions
            WHERE mmsi = %s AND base_date_time BETWEEN %s AND %s
            ORDER BY base_date_time ASC LIMIT 1
        """, (mmsi, start_time, end_time))
        start_pos = cur.fetchone()

        cur.execute("""
            SELECT latitude, longitude, sog, base_date_time
            FROM ais_positions
            WHERE mmsi = %s AND base_date_time BETWEEN %s AND %s
            ORDER BY base_date_time DESC LIMIT 1
        """, (mmsi, start_time, end_time))
        end_pos = cur.fetchone()

        # Total distance (sum of consecutive segment distances)
        cur.execute("""
            SELECT COALESCE(SUM(segment_dist), 0) / 1000.0 AS total_km
            FROM (
                SELECT ST_Distance(
                    geom,
                    LEAD(geom) OVER (ORDER BY base_date_time)
                ) AS segment_dist
                FROM ais_positions
                WHERE mmsi = %s AND base_date_time BETWEEN %s AND %s
                  AND geom IS NOT NULL
            ) sub
        """, (mmsi, start_time, end_time))
        total_dist_km = cur.fetchone()[0]
        total_dist_nm = round(total_dist_km * 0.539957, 2) if total_dist_km else 0

        # Vessel name
        cur.execute("SELECT vessel_name FROM vessels WHERE mmsi = %s", (mmsi,))
        name_row = cur.fetchone()

        return {
            "mmsi": mmsi,
            "vessel_name": name_row[0] if name_row else None,
            "report_count": stats[0],
            "time_range": {
                "start": _format_timestamp(stats[1]),
                "end": _format_timestamp(stats[2]),
                "duration_hours": round((stats[2] - stats[1]).total_seconds() / 3600, 1) if stats[1] and stats[2] else None
            },
            "speed": {
                "avg_sog_knots": round(stats[3], 1) if stats[3] else None,
                "max_sog_knots": round(stats[4], 1) if stats[4] else None
            },
            "distance": {
                "total_km": round(total_dist_km, 2) if total_dist_km else 0,
                "total_nautical_miles": total_dist_nm
            },
            "bounding_box": {
                "min_lat": stats[5], "max_lat": stats[6],
                "min_lon": stats[7], "max_lon": stats[8]
            },
            "start_position": {
                "lat": start_pos[0], "lon": start_pos[1],
                "sog": start_pos[2], "time": _format_timestamp(start_pos[3])
            } if start_pos else None,
            "end_position": {
                "lat": end_pos[0], "lon": end_pos[1],
                "sog": end_pos[2], "time": _format_timestamp(end_pos[3])
            } if end_pos else None
        }


# ─────────────────────────────────────────────
# Tool 5: find_vessels_near
# ─────────────────────────────────────────────

def find_vessels_near(lat: float, lon: float, radius_km: float,
                      timestamp: str, tolerance_minutes: int = 15) -> dict:
    """
    Find vessels within radius_km of a point around a given time.
    Uses PostGIS ST_DWithin for efficient spatial search.
    """
    radius_meters = radius_km * 1000

    with get_cursor() as cur:
        ts = datetime.fromisoformat(timestamp)
        t_start = ts - timedelta(minutes=tolerance_minutes)
        t_end = ts + timedelta(minutes=tolerance_minutes)

        cur.execute("""
            SELECT DISTINCT ON (ap.mmsi)
                ap.mmsi,
                v.vessel_name,
                ap.latitude,
                ap.longitude,
                ap.sog,
                ap.cog,
                ap.base_date_time,
                ST_Distance(
                    ap.geom,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
                ) / 1000.0 AS distance_km
            FROM ais_positions ap
            LEFT JOIN vessels v ON ap.mmsi = v.mmsi
            WHERE ST_DWithin(
                ap.geom,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                %s
            )
            AND ap.base_date_time BETWEEN %s AND %s
            ORDER BY ap.mmsi, ap.base_date_time DESC
        """, (lon, lat, lon, lat, radius_meters, t_start, t_end))

        rows = cur.fetchall()

        vessels = []
        for row in rows:
            vessels.append({
                "mmsi": row[0],
                "vessel_name": row[1],
                "latitude": row[2],
                "longitude": row[3],
                "sog": row[4],
                "cog": row[5],
                "timestamp": _format_timestamp(row[6]),
                "distance_km": round(row[7], 2)
            })

        # Sort by distance
        vessels.sort(key=lambda x: x['distance_km'])

        return {
            "search_center": {"lat": lat, "lon": lon},
            "radius_km": radius_km,
            "time_window": {
                "center": timestamp,
                "from": _format_timestamp(t_start),
                "to": _format_timestamp(t_end)
            },
            "vessels_found": len(vessels),
            "vessels": vessels
        }


# ─────────────────────────────────────────────
# Tool 6: detect_dark_activity
# ─────────────────────────────────────────────

def detect_dark_activity(identifier: str, start_time: str, end_time: str,
                         gap_threshold_minutes: int = 30) -> dict:
    """
    Detect AIS signal gaps (dark activity) for a vessel in a time range.
    Returns gap periods with location context.
    """
    with get_cursor() as cur:
        mmsis = _resolve_identifier(cur, identifier)
        if not mmsis:
            return {"error": f"No vessel found matching '{identifier}'"}

        mmsi = mmsis[0]

        # Query precomputed gaps
        cur.execute("""
            SELECT gap_start, gap_end, duration_minutes,
                   start_lat, start_lon, end_lat, end_lon,
                   jump_distance_km, implied_speed_knots
            FROM ais_gaps
            WHERE mmsi = %s
              AND gap_start >= %s
              AND gap_end <= %s
              AND duration_minutes >= %s
            ORDER BY gap_start
        """, (mmsi, start_time, end_time, gap_threshold_minutes))

        rows = cur.fetchall()

        # Also find the largest interval even if below threshold
        cur.execute("""
            SELECT MAX(duration_minutes) FROM ais_gaps
            WHERE mmsi = %s AND gap_start >= %s AND gap_end <= %s
        """, (mmsi, start_time, end_time))
        max_gap = cur.fetchone()[0]

        # Vessel name
        cur.execute("SELECT vessel_name FROM vessels WHERE mmsi = %s", (mmsi,))
        name_row = cur.fetchone()

        gaps = []
        for row in rows:
            gaps.append({
                "gap_start": _format_timestamp(row[0]),
                "gap_end": _format_timestamp(row[1]),
                "duration_minutes": round(row[2], 1),
                "start_position": {"lat": row[3], "lon": row[4]},
                "end_position": {"lat": row[5], "lon": row[6]},
                "jump_distance_km": round(row[7], 2) if row[7] else None,
                "implied_speed_knots": round(row[8], 1) if row[8] else None
            })

        return {
            "mmsi": mmsi,
            "vessel_name": name_row[0] if name_row else None,
            "time_range": {"start": start_time, "end": end_time},
            "threshold_minutes": gap_threshold_minutes,
            "gaps_found": len(gaps),
            "max_gap_minutes": round(max_gap, 1) if max_gap else 0,
            "gaps": gaps,
            "assessment": (
                f"Found {len(gaps)} AIS gap(s) exceeding {gap_threshold_minutes} minutes."
                if gaps else
                f"No AIS gaps exceeding {gap_threshold_minutes} minutes detected. "
                f"Largest interval was {round(max_gap, 1) if max_gap else 0} minutes — "
                f"continuous transmission observed."
            )
        }


# ─────────────────────────────────────────────
# Tool 7: visualize_path
# ─────────────────────────────────────────────

def visualize_path(identifier: str, start_time: str, end_time: str) -> dict:
    """
    Generate an interactive Folium map of a vessel's track with AIS gaps.
    Returns the file path to the generated HTML map.
    """
    from visualization.map_generator import generate_vessel_map

    with get_cursor() as cur:
        mmsis = _resolve_identifier(cur, identifier)
        if not mmsis:
            return {"error": f"No vessel found matching '{identifier}'"}
        mmsi = mmsis[0]

        cur.execute("SELECT vessel_name FROM vessels WHERE mmsi = %s", (mmsi,))
        name_row = cur.fetchone()
        vessel_name = name_row[0] if name_row else str(mmsi)

    # Generate the map
    track_data = get_vessel_track(str(mmsi), start_time, end_time)
    if "error" in track_data:
        return track_data

    gap_data = detect_dark_activity(str(mmsi), start_time, end_time)
    gaps = gap_data.get("gaps", [])

    filename = f"track_{mmsi}_{start_time[:10]}_{end_time[:10]}.html".replace(':', '-')
    out_path = os.path.join(MAPS_DIR, filename)

    generate_vessel_map(
        track=track_data["track"],
        gaps=gaps,
        vessel_name=vessel_name,
        mmsi=mmsi,
        out_path=out_path
    )

    return {
        "mmsi": mmsi,
        "vessel_name": vessel_name,
        "map_file": os.path.abspath(out_path),
        "points_plotted": len(track_data["track"]),
        "gaps_highlighted": len(gaps),
        "message": f"Interactive map generated for {vessel_name} (MMSI: {mmsi}). "
                   f"The map shows {len(track_data['track'])} track points "
                   f"and highlights {len(gaps)} AIS gap(s)."
    }


# ─────────────────────────────────────────────
# Tool 8: list_vessels_with_dark_activity
# ─────────────────────────────────────────────

def list_vessels_with_dark_activity(start_time: str, end_time: str,
                                    min_gap_minutes: int = 30) -> dict:
    """
    List all vessels that have AIS signal gaps (dark activity) in a time window.
    """
    with get_cursor() as cur:
        cur.execute("""
            SELECT g.mmsi, v.vessel_name, g.gap_start, g.gap_end, g.duration_minutes,
                   g.start_lat, g.start_lon, g.end_lat, g.end_lon,
                   g.jump_distance_km, g.implied_speed_knots
            FROM ais_gaps g
            LEFT JOIN vessels v ON g.mmsi = v.mmsi
            WHERE g.gap_start >= %s
              AND g.gap_end <= %s
              AND g.duration_minutes >= %s
            ORDER BY g.gap_start
        """, (start_time, end_time, min_gap_minutes))
        
        rows = cur.fetchall()
        
        vessels = []
        for row in rows:
            vessels.append({
                "mmsi": row[0],
                "vessel_name": row[1],
                "gap_start": _format_timestamp(row[2]),
                "gap_end": _format_timestamp(row[3]),
                "duration_minutes": round(row[4], 1),
                "start_position": {"lat": row[5], "lon": row[6]},
                "end_position": {"lat": row[7], "lon": row[8]},
                "jump_distance_km": round(row[9], 2) if row[9] else None,
                "implied_speed_knots": round(row[10], 1) if row[10] else None
            })
            
        return {
            "time_range": {"start": start_time, "end": end_time},
            "min_gap_minutes": min_gap_minutes,
            "vessels_found": len(vessels),
            "vessels": vessels[:100]  # Limit to 100 results to avoid LLM context bloat
        }


# ─────────────────────────────────────────────
# Tool 9: resolve_location_to_coordinates
# ─────────────────────────────────────────────

def resolve_location_to_coordinates(location_name: str) -> dict:
    """
    Resolve a geographic place/landmark name to its lat/lon coordinates.
    """
    name_clean = location_name.strip().lower()
    
    # Pre-defined database-aligned local landmarks
    landmarks = {
        "seattle": {"lat": 47.6062, "lon": -122.3321, "description": "Seattle, Washington (Puget Sound)"},
        "puget sound": {"lat": 47.7000, "lon": -122.4000, "description": "Puget Sound, Washington"},
        "elliott bay": {"lat": 47.6000, "lon": -122.3700, "description": "Elliott Bay, Seattle, Washington"},
        "houston": {"lat": 29.7604, "lon": -95.3698, "description": "Houston, Texas"},
        "houston ship channel": {"lat": 29.8000, "lon": -95.1000, "description": "Houston Ship Channel, Texas"},
        "galveston": {"lat": 29.3013, "lon": -94.7977, "description": "Galveston, Texas"},
        "galveston bay": {"lat": 29.5000, "lon": -94.9000, "description": "Galveston Bay, Texas"},
        "new york": {"lat": 40.7128, "lon": -74.0060, "description": "New York City, New York"},
        "hudson river": {"lat": 40.8000, "lon": -73.9600, "description": "Hudson River, New York"},
        "san diego": {"lat": 32.7157, "lon": -117.1611, "description": "San Diego, California"},
        "miami": {"lat": 25.7617, "lon": -80.1918, "description": "Miami, Florida"},
        "port everglades": {"lat": 26.0900, "lon": -80.1200, "description": "Port Everglades, Fort Lauderdale, Florida"},
        "port fourchon": {"lat": 29.1100, "lon": -90.2000, "description": "Port Fourchon, Louisiana"},
        "gulf of mexico": {"lat": 28.0000, "lon": -90.0000, "description": "Gulf of Mexico region"},
    }
    
    # Exact match check
    if name_clean in landmarks:
        return {"location": location_name, "resolved": True, **landmarks[name_clean]}
        
    # Substring search check
    for key, value in landmarks.items():
        if key in name_clean or name_clean in key:
            return {"location": location_name, "resolved": True, **value}
            
    return {
        "location": location_name,
        "resolved": False,
        "lat": None,
        "lon": None,
        "error": "Location not found in local port registry. Ask the user for coordinates or estimate if appropriate."
    }


# ─────────────────────────────────────────────
# Tool dispatch registry (used by the agent)
# ─────────────────────────────────────────────

TOOL_DISPATCH = {
    "get_vessel_track": get_vessel_track,
    "get_vessel_position_at": get_vessel_position_at,
    "get_vessel_info": get_vessel_info,
    "summarize_voyage": summarize_voyage,
    "find_vessels_near": find_vessels_near,
    "detect_dark_activity": detect_dark_activity,
    "visualize_path": visualize_path,
    "list_vessels_with_dark_activity": list_vessels_with_dark_activity,
    "resolve_location_to_coordinates": resolve_location_to_coordinates,
}
