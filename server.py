"""
AIS Vessel Intelligence — FastAPI Backend
Serves the chat agent API + vessel data endpoints + static frontend.
"""

import os
import sys
import json
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from tools.vessel_tools import (
    get_vessel_track, get_vessel_position_at, get_vessel_info,
    summarize_voyage, find_vessels_near, detect_dark_activity,
    visualize_path, _resolve_identifier, TOOL_DISPATCH
)
from tools.db_connection import get_cursor
from agent.agent_loop import run_agent

app = FastAPI(title="AIS Vessel Intelligence", version="1.0.0")

# CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Session store for conversation history ──
conversations = {}


# ── Request/Response Models ──

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    map_data: Optional[dict] = None
    session_id: str


class VesselSearchRequest(BaseModel):
    query: str


class TrackRequest(BaseModel):
    identifier: str
    start_time: str
    end_time: str


class NearbyRequest(BaseModel):
    lat: float
    lon: float
    radius_km: float = 10.0
    timestamp: str
    tolerance_minutes: int = 15


class AOIRequest(BaseModel):
    coordinates: list[list[float]]  # List of [lat, lon] points
    start_time: str
    end_time: str


# ── Chat Endpoint ──

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Run the AI agent with the user's message."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key == "your_openai_api_key_here":
        raise HTTPException(400, "OpenAI API key not configured. Set it in .env")

    # Get or create conversation history
    history = conversations.get(req.session_id)

    result = run_agent(req.message, conversation_history=history)
    conversations[req.session_id] = result["messages"]

    # If a map was generated, extract track data for the frontend map
    map_data = None
    if result.get("map_files"):
        map_data = {"map_file": result["map_files"][-1]}

    return ChatResponse(
        response=result["response"],
        map_data=map_data,
        session_id=req.session_id
    )


@app.post("/api/chat/reset")
async def reset_chat(session_id: str = "default"):
    """Reset conversation history."""
    conversations.pop(session_id, None)
    return {"status": "ok"}


# ── Vessel Data Endpoints (for direct map interaction) ──

# @app.get("/api/vessels/search")
# async def search_vessels(q: str):
#     """Search vessels by name (partial match)."""
#     with get_cursor() as cur:
#         cur.execute("""
#             SELECT mmsi, vessel_name, vessel_type, length, width
#             FROM vessels
#             WHERE LOWER(vessel_name) LIKE LOWER(%s)
#             ORDER BY vessel_name
#             LIMIT 20
#         """, (f"%{q}%",))
#         rows = cur.fetchall()

#     return [
#         {"mmsi": r[0], "vessel_name": r[1], "vessel_type": r[2],
#          "length": r[3], "width": r[4]}
#         for r in rows
#     ]


@app.get("/api/vessels/search")
async def search_vessels(q: str):
    """Search vessels by MMSI or vessel name."""
    
    with get_cursor() as cur:
        if q.strip().isdigit():
            # Search by MMSI
            cur.execute("""
                SELECT mmsi, vessel_name, vessel_type, length, width
                FROM vessels
                WHERE CAST(mmsi AS TEXT) LIKE %s
                ORDER BY vessel_name
                LIMIT 20
            """, (f"%{q.strip()}%",))
        else:
            # Search by vessel name
            cur.execute("""
                SELECT mmsi, vessel_name, vessel_type, length, width
                FROM vessels
                WHERE LOWER(vessel_name) LIKE LOWER(%s)
                ORDER BY vessel_name
                LIMIT 20
            """, (f"%{q.strip()}%",))

        rows = cur.fetchall()

    return [
        {
            "mmsi": r[0],
            "vessel_name": r[1],
            "vessel_type": r[2],
            "length": r[3],
            "width": r[4],
        }
        for r in rows
    ]


@app.get("/api/vessels/{mmsi}/info")
async def vessel_info(mmsi: int):
    """Get vessel static info."""
    return get_vessel_info(str(mmsi))


@app.post("/api/vessels/track")
async def vessel_track(req: TrackRequest):
    """Get vessel track as GeoJSON for map rendering."""
    track_result = get_vessel_track(req.identifier, req.start_time, req.end_time)
    if "error" in track_result:
        raise HTTPException(404, track_result["error"])

    # Convert to GeoJSON for Leaflet
    features = []

    # Track line segments (speed-colored)
    points = track_result.get("track", [])
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]
        if p1.get("lat") is None or p2.get("lat") is None:
            continue

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [p1["lon"], p1["lat"]],
                    [p2["lon"], p2["lat"]]
                ]
            },
            "properties": {
                "type": "track_segment",
                "sog": p1.get("sog"),
                "cog": p1.get("cog"),
                "heading": p1.get("heading"),
                "timestamp": p1.get("timestamp"),
            }
        })

    # Start point
    if points:
        start = points[0]
        if start.get("lat") is not None:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [start["lon"], start["lat"]]
                },
                "properties": {
                    "type": "start",
                    "timestamp": start.get("timestamp"),
                    "sog": start.get("sog")
                }
            })

        end = points[-1]
        if end.get("lat") is not None:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [end["lon"], end["lat"]]
                },
                "properties": {
                    "type": "end",
                    "timestamp": end.get("timestamp"),
                    "sog": end.get("sog")
                }
            })

    geojson = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "mmsi": track_result.get("mmsi"),
            "vessel_name": track_result.get("vessel_name"),
            "total_points": track_result.get("total_points_in_range"),
            "points_returned": track_result.get("points_returned"),
        }
    }

    return geojson


@app.post("/api/vessels/gaps")
async def vessel_gaps(req: TrackRequest):
    """Get AIS gaps as GeoJSON."""
    gap_result = detect_dark_activity(
        req.identifier, req.start_time, req.end_time
    )
    if "error" in gap_result:
        raise HTTPException(404, gap_result["error"])

    features = []
    for gap in gap_result.get("gaps", []):
        sp = gap.get("start_position", {})
        ep = gap.get("end_position", {})
        if sp.get("lat") is not None and ep.get("lat") is not None:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [sp["lon"], sp["lat"]],
                        [ep["lon"], ep["lat"]]
                    ]
                },
                "properties": {
                    "type": "gap",
                    "gap_start": gap.get("gap_start"),
                    "gap_end": gap.get("gap_end"),
                    "duration_minutes": gap.get("duration_minutes"),
                    "jump_distance_km": gap.get("jump_distance_km"),
                    "implied_speed_knots": gap.get("implied_speed_knots"),
                }
            })

            # Gap endpoint markers
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [sp["lon"], sp["lat"]]},
                "properties": {"type": "gap_start", "time": gap.get("gap_start")}
            })
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [ep["lon"], ep["lat"]]},
                "properties": {"type": "gap_end", "time": gap.get("gap_end")}
            })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "mmsi": gap_result.get("mmsi"),
            "vessel_name": gap_result.get("vessel_name"),
            "gaps_found": gap_result.get("gaps_found"),
            "assessment": gap_result.get("assessment"),
        }
    }


@app.post("/api/vessels/nearby")
async def vessels_nearby(req: NearbyRequest):
    """Find vessels near a point."""
    result = find_vessels_near(
        req.lat, req.lon, req.radius_km,
        req.timestamp, req.tolerance_minutes
    )
    return result


@app.post("/api/vessels/aoi")
async def vessels_in_aoi(req: AOIRequest):
    """Find and group vessel points inside a user-defined area of interest (polygon)."""
    if not req.coordinates or len(req.coordinates) < 3:
        raise HTTPException(400, "At least 3 coordinates are required to form an area of interest polygon.")

    # Format the polygon coordinates into PostGIS WKT (Well-Known Text)
    # PostGIS MakePoint/WKT uses (lon, lat) order, so we swap our (lat, lon) inputs
    # Also, we must close the polygon loop in PostGIS WKT by repeating the start point at the end
    coords = [[float(c[0]), float(c[1])] for c in req.coordinates]
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    wkt_coords = ", ".join([f"{c[1]} {c[0]}" for c in coords])
    polygon_wkt = f"POLYGON(({wkt_coords}))"

    # Query the database
    with get_cursor() as cur:
        cur.execute("""
            SELECT ap.mmsi, v.vessel_name, ap.latitude, ap.longitude, ap.sog, ap.cog, ap.base_date_time
            FROM ais_positions ap
            LEFT JOIN vessels v ON ap.mmsi = v.mmsi
            WHERE ST_Within(
                ap.geom::geometry,
                ST_GeomFromText(%s, 4326)
            )
            AND ap.base_date_time BETWEEN %s AND %s
            ORDER BY ap.mmsi, ap.base_date_time ASC
        """, (polygon_wkt, req.start_time, req.end_time))

        rows = cur.fetchall()

    # Group by MMSI
    vessel_groups = {}
    for row in rows:
        mmsi = row[0]
        vessel_name = row[1] or f"MMSI: {mmsi}"
        lat = row[2]
        lon = row[3]
        sog = row[4]
        cog = row[5]
        timestamp = row[6].isoformat() if row[6] else None

        if mmsi not in vessel_groups:
            vessel_groups[mmsi] = {
                "mmsi": mmsi,
                "vessel_name": vessel_name,
                "points": []
            }
        vessel_groups[mmsi]["points"].append({
            "lat": lat,
            "lon": lon,
            "sog": sog,
            "cog": cog,
            "timestamp": timestamp
        })

    return list(vessel_groups.values())


@app.post("/api/vessels/voyage")
async def voyage_summary(req: TrackRequest):
    """Get voyage summary."""
    return summarize_voyage(req.identifier, req.start_time, req.end_time)


@app.get("/api/stats")
async def db_stats():
    """Get database statistics for the status bar."""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ais_positions")
        pos_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM vessels")
        vessel_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM ais_gaps")
        gap_count = cur.fetchone()[0]
        cur.execute("SELECT MIN(base_date_time), MAX(base_date_time) FROM ais_positions")
        time_range = cur.fetchone()

    return {
        "positions": pos_count,
        "vessels": vessel_count,
        "gaps": gap_count,
        "time_range": {
            "start": time_range[0].isoformat() if time_range[0] else None,
            "end": time_range[1].isoformat() if time_range[1] else None,
        }
    }


# ── Static file serving ──

# Serve frontend
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
