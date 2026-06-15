# AIS Vessel Intelligence System — Plan of Action

## 1. High-Level Architecture

```
[Historical CSVs]      [Live AIS feed]
        \                    /
         \                  /
        Ingestion / ETL layer
                 |
     PostgreSQL + PostGIS + TimescaleDB
     (ais_positions, vessels, ais_gaps, tracks_simplified)
                 |
        Python query/tool layer
     (get_track, get_gaps, find_near, etc.)
                 |
      OpenAI function-calling agent
                 |
        +-------+--------+
        |                |
   Chat answers   Visualization module
                  (Folium maps, standalone or agent-triggered)
```

The core principle: the LLM never touches raw rows. It calls well-defined Python/SQL functions ("tools"), gets back small structured JSON results, and reasons over those.

---

## 2. Database Schema

### `ais_positions` (TimescaleDB hypertable, partitioned by `base_date_time`)

| column | type | notes |
|---|---|---|
| mmsi | BIGINT | vessel identifier |
| base_date_time | TIMESTAMPTZ | reporting time |
| geom | GEOGRAPHY(POINT, 4326) | derived from lon/lat for spatial queries |
| longitude | DOUBLE PRECISION | |
| latitude | DOUBLE PRECISION | |
| sog | REAL | speed over ground (knots) |
| cog | REAL | course over ground |
| heading | REAL | |
| status | SMALLINT | navigational status code |
| draft | REAL | |

Indexes: `(mmsi, base_date_time)` btree, GIST on `geom`, and TimescaleDB's automatic time partitioning.

### `vessels` (slowly-changing reference table)

| column | type | notes |
|---|---|---|
| mmsi | BIGINT PK | |
| vessel_name | TEXT | |
| imo | TEXT | |
| call_sign | TEXT | |
| vessel_type | SMALLINT | |
| length | REAL | |
| width | REAL | |
| cargo | SMALLINT | |
| transceiver | TEXT | |
| last_updated | TIMESTAMPTZ | |

Many AIS rows have blank `vessel_name`/`imo`/`call_sign` (only sent periodically as Type 5 messages). On ingest, do an `UPSERT ... ON CONFLICT (mmsi) DO UPDATE` only when the incoming row has non-null values, so `vessels` always holds the latest known identity info per MMSI.

### `ais_gaps` (precomputed, refreshed periodically)

| column | type | notes |
|---|---|---|
| mmsi | BIGINT | |
| gap_start | TIMESTAMPTZ | last position before signal loss |
| gap_end | TIMESTAMPTZ | first position after signal resumes |
| duration_minutes | REAL | |
| start_lat/lon | DOUBLE | last known position |
| end_lat/lon | DOUBLE | position when reappeared |
| jump_distance_km | REAL | distance between start/end positions |
| implied_speed_knots | REAL | jump_distance / duration — useful flag |

### `tracks_simplified` (one row per mmsi per day/voyage)

| column | type | notes |
|---|---|---|
| mmsi | BIGINT | |
| track_date | DATE | |
| geom | GEOGRAPHY(LINESTRING) | Douglas-Peucker simplified |
| point_count | INT | |

---

## 3. Ingestion Pipeline

**Historical CSV load:**
1. `COPY` raw CSV into a staging table matching your file's columns exactly.
2. Run a transform query: parse `base_date_time` (your format is `DD-MM-YYYY HH:MM`), build `geom` from lon/lat, cast types, and insert into `ais_positions`.
3. Upsert distinct `(mmsi, vessel_name, imo, call_sign, vessel_type, length, width, cargo, transceiver)` combos (where non-null) into `vessels`.
4. Deduplicate on `(mmsi, base_date_time)` if needed.

**Live feed:**
1. Connect to your AIS source (receiver NMEA stream, or a provider API/websocket like AISstream.io).
2. Decode messages (e.g., with `pyais`) into the same row shape as the CSV.
3. Buffer messages and batch-insert every few seconds (e.g., `executemany` or `COPY` from an in-memory buffer) — don't insert row-by-row at scale.
4. On each batch, also upsert `vessels` for any rows carrying identity info (Type 5 messages).

---

## 4. Background Jobs (run on schedule, e.g., every 15–60 min)

1. **Gap detection job** — recompute `ais_gaps` for vessels with new data (see Section 6 for the algorithm).
2. **Track simplification job** — for each `(mmsi, date)` with new points, rebuild the simplified LineString in `tracks_simplified` using PostGIS `ST_SimplifyPreserveTopology`.
3. **Vessel reference refresh** — already handled incrementally on ingest, but a periodic sweep catches stragglers.

---

## 5. Core Query Functions ("Tools")

These are plain Python functions (wrapping SQL) that get exposed to the OpenAI agent as function-calling tools.

### `get_vessel_track(identifier, start_time, end_time)`
- `identifier` = MMSI or vessel name (resolve name → MMSI via `vessels` table first; handle multiple matches by asking for disambiguation or returning all).
- Returns: ordered list of `{timestamp, lat, lon, sog, cog, heading}`.
- For long ranges, return the simplified track from `tracks_simplified` plus key waypoints (start, end, max-speed point, etc.) rather than every raw row.

### `get_vessel_position_at(identifier, timestamp)`
- Returns the nearest position record to a given timestamp (with the actual time delta, so the agent can say "as of 14:32, 3 minutes before your requested time...").

### `get_vessel_info(identifier)`
- Returns static info: name, MMSI, IMO, call sign, type, dimensions.

### `summarize_voyage(identifier, start_time, end_time)`
- Returns: total distance traveled, average/max SOG, bounding box, start/end positions and times, number of position reports.

### `find_vessels_near(lat, lon, radius_km, timestamp, tolerance_minutes=15)`
- Spatial+temporal query: which vessels were within `radius_km` of a point around a given time.

### `detect_dark_activity(identifier, start_time, end_time, gap_threshold_minutes=30)`
- The reasoning-layer tool. Returns a list of gap periods (from `ais_gaps`, filtered to the range and threshold) with full context — see Section 6.

### `visualize_path(identifier, start_time, end_time)`
- Generates a map (HTML file via Folium) of the track, marks any AIS gaps as dashed lines, and returns a file path/URL the agent can reference in its answer. See Section 8.

---

## 6. Dark Activity / AIS Gap Detection — Algorithm

**Goal:** given a vessel and a time window, find periods where it stopped transmitting AIS and flag them as potential "dark activity."

**Step 1 — Compute intervals.**
For a given `mmsi`, pull positions ordered by `base_date_time`, and compute `delta_t = next.base_date_time - this.base_date_time` for each consecutive pair.

**Step 2 — Determine the threshold.**
Two options, can combine:
- **Fixed threshold**: e.g., 30 minutes — anything longer than that with no AIS report is flagged. Simple, works well if your data's normal reporting interval is much smaller (minutes).
- **Adaptive threshold**: compute the vessel's median reporting interval over a trailing window (e.g., last 24h), and flag gaps > `max(fixed_minimum, k × median_interval)` where `k` ≈ 5–10. This avoids false positives for vessels that naturally report infrequently.

Start with the fixed threshold (configurable parameter, default 30 min) — it's easier to reason about and tune later.

**Step 3 — Flag and enrich each gap.**
For each `delta_t > threshold`:
- `gap_start` = timestamp + position of the last report before the gap
- `gap_end` = timestamp + position of the first report after the gap
- `duration_minutes` = delta_t in minutes
- `jump_distance_km` = great-circle distance between start and end positions (haversine or `ST_Distance`)
- `implied_speed_knots` = jump_distance / duration — if this is unrealistically high for the vessel type, it's a stronger signal of intentional AIS shutoff + relocation vs. just a dropped signal in place

**Step 4 — Store in `ais_gaps`**, refreshed incrementally as new data arrives (only recompute for the latest open interval per vessel + a small lookback window, not the whole history each time).

**Step 5 — Reasoning layer behavior.**
When asked "did vessel X go dark, and for how long?":
1. Agent calls `detect_dark_activity(mmsi, start, end, threshold)`.
2. If gaps exist, agent reports each: when AIS stopped, when it resumed, duration, and the jump distance/implied speed (useful for flagging "this is suspicious — it reappeared 80km away after 6 hours, implying ~13 knots, which is plausible/implausible for this vessel").
3. If no gaps exceed the threshold, the agent reports normal continuous transmission, and can optionally mention the largest interval found even if below threshold.

This same `ais_gaps` table also powers things like fleet-wide "show me all vessels that went dark in this region last week" queries via `find_vessels_near` + a join on gap location.

---

## 7. OpenAI Function-Calling Agent

### Tool schema (JSON, OpenAI tools format)

```json
[
  {
    "type": "function",
    "function": {
      "name": "get_vessel_track",
      "description": "Get the path/track of a vessel between two timestamps, as ordered lat/lon points.",
      "parameters": {
        "type": "object",
        "properties": {
          "identifier": {"type": "string", "description": "Vessel name or MMSI"},
          "start_time": {"type": "string", "format": "date-time"},
          "end_time": {"type": "string", "format": "date-time"}
        },
        "required": ["identifier", "start_time", "end_time"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "detect_dark_activity",
      "description": "Detect periods where a vessel stopped transmitting AIS (gaps) within a time range, with location context.",
      "parameters": {
        "type": "object",
        "properties": {
          "identifier": {"type": "string"},
          "start_time": {"type": "string", "format": "date-time"},
          "end_time": {"type": "string", "format": "date-time"},
          "gap_threshold_minutes": {"type": "integer", "default": 30}
        },
        "required": ["identifier", "start_time", "end_time"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "visualize_path",
      "description": "Generate an interactive map of a vessel's track, with AIS gaps highlighted, and return a link to it.",
      "parameters": {
        "type": "object",
        "properties": {
          "identifier": {"type": "string"},
          "start_time": {"type": "string", "format": "date-time"},
          "end_time": {"type": "string", "format": "date-time"}
        },
        "required": ["identifier", "start_time", "end_time"]
      }
    }
  }
]
```
(Define the remaining tools — `get_vessel_position_at`, `get_vessel_info`, `summarize_voyage`, `find_vessels_near` — the same way.)

### Agent loop (pseudocode)

```python
messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_question}]

while True:
    response = openai.chat.completions.create(
        model="gpt-5-nano",  # or gpt-4.1 / o-series
        messages=messages,
        tools=TOOLS,
        tool_choice="auto"
    )
    msg = response.choices[0].message
    messages.append(msg)

    if not msg.tool_calls:
        return msg.content  # final answer

    for call in msg.tool_calls:
        result = TOOL_DISPATCH[call.function.name](**json.loads(call.function.arguments))
        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(result)
        })
```

### System prompt guidance
- Tell the model the current date/time context, that all timestamps in tool results are UTC, and how to resolve vessel names vs MMSI (if ambiguous, ask the user or list candidates).
- Instruct it to keep numeric results in tool outputs concise (the functions should already pre-aggregate; the model shouldn't be handed thousands of points).
- Instruct it that when `visualize_path` is called, it should mention the map is available rather than trying to describe every point textually.

---

## 8. Visualization Module

Two complementary pieces, both built on **Folium** (interactive Leaflet maps in Python — easy to generate as standalone HTML).

### A. Standalone visualization tool
```python
def visualize_vessel(mmsi, start_time=None, end_time=None, out_path="map.html"):
    points = get_vessel_track(mmsi, start_time, end_time)
    gaps = detect_dark_activity(mmsi, start_time, end_time)

    m = folium.Map(location=[points[0]["lat"], points[0]["lon"]], zoom_start=8)
    coords = [(p["lat"], p["lon"]) for p in points]
    folium.PolyLine(coords, color="blue", weight=2.5).add_to(m)
    folium.Marker(coords[0], tooltip="Start", icon=folium.Icon(color="green")).add_to(m)
    folium.Marker(coords[-1], tooltip="End", icon=folium.Icon(color="red")).add_to(m)

    for gap in gaps:
        folium.PolyLine(
            [(gap["start_lat"], gap["start_lon"]), (gap["end_lat"], gap["end_lon"])],
            color="red", weight=2, dash_array="10"
        ).add_to(m).add_child(folium.Tooltip(f"AIS gap: {gap['duration_minutes']} min"))

    m.save(out_path)
    return out_path
```
Run this directly with just an MMSI (and optional date range) to get a shareable HTML map — no LLM involved, for quick manual inspection.

### B. Agent-triggered visualization
The `visualize_path` tool calls the same function, saves the HTML to a served directory (or generates a base64-embedded image via `selenium`/`folium`'s static export if you need an image instead of HTML), and returns a URL/path. The chat UI then renders it (e.g., an `<iframe>` for the HTML map) alongside the agent's text answer.

**Speed-colored tracks (optional enhancement):** instead of a single-color polyline, split the track into segments colored by SOG (e.g., green = normal transit speed, orange = slow/loitering, red = stopped) — useful for quickly spotting loitering behavior, which often precedes or follows dark periods.

---

## 9. Interface

For a fast first version: a **Streamlit** app — chat input on one side, map panel (via `streamlit-folium`) on the other. The agent loop runs server-side; when `visualize_path` is called, the returned HTML map renders directly in the panel.

For a more production setup: FastAPI backend exposing `/chat` (runs the agent loop) and serving generated map files, with a React frontend (chat + embedded map iframe).

---

## 10. Suggested Build Order (Phases)

1. **Data layer**: set up Postgres/PostGIS/TimescaleDB, load your historical CSVs, validate schema and indexes. (Get `vessels` table populated correctly first — this affects name→MMSI resolution everywhere else.)
2. **Core query functions**: implement and unit-test `get_vessel_track`, `get_vessel_position_at`, `get_vessel_info`, `summarize_voyage`, `find_vessels_near` against real data.
3. **Gap detection**: implement the algorithm in Section 6, build `ais_gaps`, test against vessels with known dark periods.
4. **Visualization**: build the standalone `visualize_vessel` function, confirm maps look right (gaps shown, markers correct).
5. **Agent integration**: define tool schemas, wire up the OpenAI agent loop, test with the example questions ("Where was X on date Y", "did vessel Z go dark", etc.).
6. **UI**: Streamlit chat + map app.
7. **Live feed**: once the above is solid on historical data, add the live ingestion path (this is largely independent and can be developed in parallel).

---

## 11. Tech Stack Summary

| Layer | Tool |
|---|---|
| Database | PostgreSQL + PostGIS + TimescaleDB |
| Ingestion | Python (`psycopg2`/`asyncpg`, `pyais` for live decoding) |
| Query/tool layer | Python functions + SQL |
| LLM | OpenAI API (function/tool calling, GPT-4o or similar) |
| Visualization | Folium (+ `streamlit-folium` for embedding) |
| Interface | Streamlit (v1) → FastAPI + React (v2) |
