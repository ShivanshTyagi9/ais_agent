"""
Folium map generator for vessel tracks and AIS gaps.
Generates standalone interactive HTML maps.
"""

import os
import folium
from folium import plugins


def _speed_color(sog):
    """Color-code by speed over ground (knots)."""
    if sog is None:
        return '#888888'  # grey for unknown
    if sog < 0.5:
        return '#e74c3c'  # red — stopped
    if sog < 3:
        return '#f39c12'  # orange — slow/loitering
    if sog < 10:
        return '#2ecc71'  # green — normal
    return '#3498db'       # blue — fast transit


def generate_vessel_map(track: list, gaps: list, vessel_name: str,
                        mmsi: int, out_path: str) -> str:
    """
    Generate a Folium map with vessel track and AIS gaps.

    Args:
        track: list of dicts with {timestamp, lat, lon, sog, cog, heading}
        gaps: list of dicts with gap info (from detect_dark_activity)
        vessel_name: display name for the vessel
        mmsi: vessel MMSI
        out_path: path to save the HTML file

    Returns:
        Absolute path to the saved HTML file.
    """
    if not track:
        raise ValueError("No track points to plot")

    # Filter out points with None coords
    valid_points = [p for p in track if p.get('lat') is not None and p.get('lon') is not None]
    if not valid_points:
        raise ValueError("No valid coordinates in track data")

    # Center map on midpoint of track
    mid_idx = len(valid_points) // 2
    center = [valid_points[mid_idx]['lat'], valid_points[mid_idx]['lon']]

    m = folium.Map(
        location=center,
        zoom_start=8,
        tiles='CartoDB dark_matter',
        control_scale=True
    )

    # Add multiple tile layers
    folium.TileLayer('CartoDB positron', name='Light').add_to(m)
    folium.TileLayer('OpenStreetMap', name='OpenStreetMap').add_to(m)

    # ── Speed-colored track segments ──
    track_group = folium.FeatureGroup(name='Vessel Track', show=True)

    for i in range(len(valid_points) - 1):
        p1 = valid_points[i]
        p2 = valid_points[i + 1]
        color = _speed_color(p1.get('sog'))

        segment = folium.PolyLine(
            [(p1['lat'], p1['lon']), (p2['lat'], p2['lon'])],
            color=color,
            weight=3,
            opacity=0.8
        )
        tooltip = (
            f"Time: {p1.get('timestamp', 'N/A')}<br>"
            f"SOG: {p1.get('sog', 'N/A')} kn<br>"
            f"COG: {p1.get('cog', 'N/A')}°<br>"
            f"Heading: {p1.get('heading', 'N/A')}°"
        )
        segment.add_child(folium.Tooltip(tooltip))
        segment.add_to(track_group)

    track_group.add_to(m)

    # ── Start marker ──
    start = valid_points[0]
    folium.Marker(
        [start['lat'], start['lon']],
        popup=folium.Popup(
            f"<b>START</b><br>"
            f"Time: {start.get('timestamp', 'N/A')}<br>"
            f"Lat: {start['lat']:.4f}<br>"
            f"Lon: {start['lon']:.4f}<br>"
            f"SOG: {start.get('sog', 'N/A')} kn",
            max_width=250
        ),
        tooltip='Track Start',
        icon=folium.Icon(color='green', icon='play', prefix='fa')
    ).add_to(m)

    # ── End marker ──
    end = valid_points[-1]
    folium.Marker(
        [end['lat'], end['lon']],
        popup=folium.Popup(
            f"<b>END</b><br>"
            f"Time: {end.get('timestamp', 'N/A')}<br>"
            f"Lat: {end['lat']:.4f}<br>"
            f"Lon: {end['lon']:.4f}<br>"
            f"SOG: {end.get('sog', 'N/A')} kn",
            max_width=250
        ),
        tooltip='Track End',
        icon=folium.Icon(color='red', icon='stop', prefix='fa')
    ).add_to(m)

    # ── AIS Gaps (dark activity) — red dashed lines ──
    if gaps:
        gap_group = folium.FeatureGroup(name='AIS Gaps (Dark Activity)', show=True)

        for gap in gaps:
            start_pos = gap.get('start_position', {})
            end_pos = gap.get('end_position', {})

            if (start_pos.get('lat') is not None and end_pos.get('lat') is not None):
                # Dashed red line between last-seen and reappeared positions
                gap_line = folium.PolyLine(
                    [
                        (start_pos['lat'], start_pos['lon']),
                        (end_pos['lat'], end_pos['lon'])
                    ],
                    color='#e74c3c',
                    weight=3,
                    dash_array='10 6',
                    opacity=0.9
                )

                duration = gap.get('duration_minutes', 'N/A')
                jump = gap.get('jump_distance_km', 'N/A')
                speed = gap.get('implied_speed_knots', 'N/A')

                tooltip_text = (
                    f"<b>⚠️ AIS GAP</b><br>"
                    f"Duration: {duration} min<br>"
                    f"Jump: {jump} km<br>"
                    f"Implied speed: {speed} kn<br>"
                    f"Start: {gap.get('gap_start', 'N/A')}<br>"
                    f"End: {gap.get('gap_end', 'N/A')}"
                )
                gap_line.add_child(folium.Tooltip(tooltip_text))
                gap_line.add_to(gap_group)

                # Markers at gap endpoints
                folium.CircleMarker(
                    [start_pos['lat'], start_pos['lon']],
                    radius=6, color='#e74c3c', fill=True,
                    fill_opacity=0.8,
                    tooltip=f"Signal lost: {gap.get('gap_start', 'N/A')}"
                ).add_to(gap_group)

                folium.CircleMarker(
                    [end_pos['lat'], end_pos['lon']],
                    radius=6, color='#f39c12', fill=True,
                    fill_opacity=0.8,
                    tooltip=f"Signal resumed: {gap.get('gap_end', 'N/A')}"
                ).add_to(gap_group)

        gap_group.add_to(m)

    # ── Legend ──
    legend_html = f"""
    <div style="
        position: fixed;
        bottom: 30px; left: 30px;
        background: rgba(0,0,0,0.85);
        border-radius: 8px;
        padding: 14px 18px;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 13px;
        color: white;
        z-index: 9999;
        box-shadow: 0 2px 12px rgba(0,0,0,0.4);
        line-height: 1.7;
    ">
        <div style="font-size: 15px; font-weight: 600; margin-bottom: 6px;">
            🚢 {vessel_name}
        </div>
        <div style="font-size: 11px; color: #aaa; margin-bottom: 8px;">
            MMSI: {mmsi} &nbsp;|&nbsp; {len(valid_points)} points
        </div>
        <div><span style="color: #e74c3c;">━━</span> Stopped (&lt;0.5 kn)</div>
        <div><span style="color: #f39c12;">━━</span> Slow / Loitering (&lt;3 kn)</div>
        <div><span style="color: #2ecc71;">━━</span> Normal Transit (3–10 kn)</div>
        <div><span style="color: #3498db;">━━</span> Fast Transit (&gt;10 kn)</div>
        <div><span style="color: #e74c3c;">┅┅</span> AIS Gap (Dark Period)</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    # ── Title bar ──
    title_html = f"""
    <div style="
        position: fixed;
        top: 10px; left: 50%; transform: translateX(-50%);
        background: rgba(0,0,0,0.85);
        border-radius: 8px;
        padding: 10px 24px;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 16px;
        font-weight: 600;
        color: white;
        z-index: 9999;
        box-shadow: 0 2px 12px rgba(0,0,0,0.4);
    ">
        {vessel_name} — Track Visualization
        <span style="font-size: 12px; color: #aaa; margin-left: 12px;">
            {valid_points[0].get('timestamp', '')[:10]} → {valid_points[-1].get('timestamp', '')[:10]}
        </span>
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    # ── Layer control + fullscreen ──
    folium.LayerControl(collapsed=False).add_to(m)
    plugins.Fullscreen().add_to(m)

    # Fit bounds to track
    lats = [p['lat'] for p in valid_points]
    lons = [p['lon'] for p in valid_points]
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])

    # Save
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    m.save(out_path)

    return os.path.abspath(out_path)
