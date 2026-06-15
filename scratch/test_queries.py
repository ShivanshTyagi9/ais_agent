import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, r"c:\Users\shive\Desktop\AIS_Agent")
from tools.db_connection import get_cursor

def detect_interaction_events(mmsi, start_time, end_time, radius_m=500, tolerance_sec=300):
    with get_cursor() as cur:
        # Get all proximity contacts sorted by other vessel and time
        query = """
            WITH v1 AS (
                SELECT base_date_time, geom, mmsi
                FROM ais_positions
                WHERE mmsi = %s AND base_date_time BETWEEN %s AND %s
            )
            SELECT
                v2.mmsi AS other_mmsi,
                v.vessel_name AS other_name,
                v.vessel_type AS other_type,
                v1.base_date_time AS time_self,
                v2.base_date_time AS time_other,
                ST_Distance(v1.geom, v2.geom) AS dist_m,
                v2.latitude,
                v2.longitude
            FROM v1
            JOIN ais_positions v2 ON 
                v2.base_date_time BETWEEN v1.base_date_time - INTERVAL '1 second' * %s
                                     AND v1.base_date_time + INTERVAL '1 second' * %s
                AND v2.mmsi != v1.mmsi
                AND ST_DWithin(v1.geom, v2.geom, %s)
            LEFT JOIN vessels v ON v2.mmsi = v.mmsi
            ORDER BY other_mmsi, time_self ASC
        """
        cur.execute(query, (mmsi, start_time, end_time, tolerance_sec, tolerance_sec, radius_m))
        rows = cur.fetchall()
        
    if not rows:
        return []
        
    # Group into events per other vessel
    events_by_vessel = {}
    for r in rows:
        other_mmsi = r[0]
        if other_mmsi not in events_by_vessel:
            events_by_vessel[other_mmsi] = []
        events_by_vessel[other_mmsi].append(r)
        
    interaction_events = []
    
    for other_mmsi, contacts in events_by_vessel.items():
        other_name = contacts[0][1] or f"MMSI: {other_mmsi}"
        other_type = contacts[0][2]
        
        # Segment contacts into distinct encounters (break if gap > 30 minutes)
        current_event = [contacts[0]]
        for c in contacts[1:]:
            last_time = current_event[-1][3]
            curr_time = c[3]
            if (curr_time - last_time).total_seconds() > 1800: # 30 mins
                # Save current event and start a new one
                interaction_events.append(summarize_event(current_event, other_mmsi, other_name, other_type))
                current_event = [c]
            else:
                current_event.append(c)
        if current_event:
            interaction_events.append(summarize_event(current_event, other_mmsi, other_name, other_type))
            
    # Sort interaction events by start time
    interaction_events.sort(key=lambda x: x['start_time'])
    return interaction_events

def summarize_event(contacts, other_mmsi, other_name, other_type):
    start_time = contacts[0][3]
    end_time = contacts[-1][3]
    duration_mins = (end_time - start_time).total_seconds() / 60.0
    min_dist = min(c[5] for c in contacts)
    avg_lat = sum(c[6] for c in contacts) / len(contacts)
    avg_lon = sum(c[7] for c in contacts) / len(contacts)
    
    return {
        "other_mmsi": other_mmsi,
        "vessel_name": other_name,
        "vessel_type": other_type,
        "start_time": start_time,
        "end_time": end_time,
        "duration_minutes": round(duration_mins, 1),
        "min_distance_meters": round(min_dist, 1),
        "latitude": round(avg_lat, 5),
        "longitude": round(avg_lon, 5)
    }

if __name__ == '__main__':
    mmsi = 316004661
    start = '2025-12-24T00:00:00'
    end = '2025-12-24T23:59:59'
    
    print("\nDetecting interaction events...")
    events = detect_interaction_events(mmsi, start, end, radius_m=500, tolerance_sec=300)
    print(f"Found {len(events)} distinct interaction events:")
    for ev in events[:10]:
        print(f"  Event with {ev['vessel_name']} (MMSI: {ev['other_mmsi']}): min dist {ev['min_distance_meters']}m, duration {ev['duration_minutes']} mins, from {ev['start_time']} to {ev['end_time']} at ({ev['latitude']:.5f}, {ev['longitude']:.5f})")
