/* ═══════════════════════════════════════════════════════════
   AIS Vessel Intelligence — Frontend Application
   ═══════════════════════════════════════════════════════════ */

// ── State ──
const state = {
    selectedVessel: null,   // { mmsi, vessel_name }
    sessionId: 'session_' + Date.now(),
    trackLayers: [],        // Leaflet layers for tracks
    gapLayers: [],          // Leaflet layers for gaps
    markerLayers: [],       // Leaflet layers for markers
    isProcessing: false,
};

// ── Map Initialization ──
const map = L.map('map', {
    center: [30, -40],
    zoom: 3,
    zoomControl: true,
    attributionControl: true,
});

// Initialize Leaflet Geoman controls
map.pm.addControls({
    position: 'topleft',
    drawMarker: false,
    drawCircleMarker: false,
    drawPolyline: false,
    drawRectangle: true,
    drawPolygon: true,
    drawCircle: false,
    drawText: false,
    editMode: false,
    dragMode: false,
    cutPolygon: false,
    removalMode: true,
});

// Set global options for drawing
map.pm.setGlobalOptions({
    templineStyle: { color: '#3b82f6' },
    hintlineStyle: { color: '#3b82f6', dashArray: [5, 5] }
});

// Dark tile layer
const darkTiles = L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19,
    }
).addTo(map);

// AOI variables and helper functions
let currentAOILayer = null;
let aoiTrackLayers = [];

// Listen for shape creation (Area of Interest drawn by user)
map.on('pm:create', (e) => {
    const layer = e.layer;
    let latlngs = layer.getLatLngs();
    
    // For polygons and rectangles, Leaflet returns nested arrays
    if (Array.isArray(latlngs[0])) {
        latlngs = latlngs[0];
    }
    
    const coordinates = latlngs.map(latlng => [latlng.lat, latlng.lng]);
    
    // Fetch and visualize vessels inside this AOI
    queryAOI(coordinates, layer);
});

async function queryAOI(coordinates, layer) {
    // Clear previous AOI tracks/markers
    clearAOITracks();
    
    if (currentAOILayer && currentAOILayer !== layer) {
        map.removeLayer(currentAOILayer);
    }
    currentAOILayer = layer;
    
    const startTime = document.getElementById('time-start').value;
    const endTime = document.getElementById('time-end').value;
    
    showLoading('Querying vessels inside Area of Interest...');
    
    try {
        const result = await apiFetch('/api/vessels/aoi', {
            method: 'POST',
            body: JSON.stringify({
                coordinates: coordinates,
                start_time: startTime,
                end_time: endTime
            })
        });
        
        if (result.length === 0) {
            alert('No vessel positions found in this area of interest during the selected time range.');
            return;
        }
        
        renderAOIVessels(result);
        
    } catch (e) {
        alert('Error querying AOI: ' + e.message);
        if (layer) map.removeLayer(layer);
    } finally {
        hideLoading();
    }
}

function clearAOITracks() {
    aoiTrackLayers.forEach(l => map.removeLayer(l));
    aoiTrackLayers = [];
}

// Generate colors for unique vessel paths
function getRandomColor(index) {
    const colors = [
        '#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6',
        '#06b6d4', '#14b8a6', '#f43f5e', '#a855f7', '#6366f1'
    ];
    return colors[index % colors.length];
}

function renderAOIVessels(vesselGroups) {
    const bounds = [];
    
    vesselGroups.forEach((group, index) => {
        const color = getRandomColor(index);
        const coords = group.points.map(p => [p.lat, p.lon]);
        
        // If there are multiple points, draw a chronological path
        if (coords.length > 1) {
            const polyline = L.polyline(coords, {
                color: color,
                weight: 3,
                opacity: 0.85,
                dashArray: '5, 5' // Dashed line to distinguish from full track
            }).addTo(map);
            
            polyline.bindTooltip(`
                <b>Vessel:</b> ${group.vessel_name || 'Unknown'}<br>
                <b>MMSI:</b> ${group.mmsi}<br>
                <b>Points in AOI:</b> ${coords.length}
            `, { sticky: true });
            
            aoiTrackLayers.push(polyline);
        }
        
        // Render markers for each point in the AOI
        group.points.forEach((point, pIndex) => {
            const marker = L.circleMarker([point.lat, point.lon], {
                radius: 5,
                fillColor: color,
                fillOpacity: 0.9,
                color: '#ffffff',
                weight: 1.5
            }).addTo(map);
            
            marker.bindPopup(`
                <b>Vessel:</b> ${group.vessel_name || 'Unknown'}<br>
                <b>MMSI:</b> ${group.mmsi}<br>
                <b>Time:</b> ${point.timestamp}<br>
                <b>SOG:</b> ${point.sog !== null ? point.sog + ' kn' : 'N/A'}<br>
                <b>COG:</b> ${point.cog !== null ? point.cog + '°' : 'N/A'}<br>
                <b>Point:</b> ${pIndex + 1} of ${coords.length}
            `);
            
            aoiTrackLayers.push(marker);
            bounds.push([point.lat, point.lon]);
        });
    });
    
    // Fit map to show all found points
    if (bounds.length > 0) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
    }
}

// Alternative layers
const lightTiles = L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 19,
    }
);

const osmTiles = L.tileLayer(
    'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap',
        maxZoom: 19,
    }
);

L.control.layers({
    'Dark': darkTiles,
    'Light': lightTiles,
    'OpenStreetMap': osmTiles,
}, {}, { position: 'topright' }).addTo(map);


// ── Utility Functions ──

function speedColor(sog) {
    if (sog === null || sog === undefined) return '#6b7280';
    if (sog < 0.5) return '#ef4444';
    if (sog < 3) return '#f59e0b';
    if (sog < 10) return '#10b981';
    return '#3b82f6';
}

function formatNumber(n) {
    if (n === null || n === undefined) return '—';
    return n.toLocaleString();
}

function showLoading(text = 'Processing...') {
    document.getElementById('loading-overlay').classList.remove('hidden');
    document.querySelector('.loading-text').textContent = text;
}

function hideLoading() {
    document.getElementById('loading-overlay').classList.add('hidden');
}

async function apiFetch(url, options = {}) {
    const defaults = {
        headers: { 'Content-Type': 'application/json' },
    };
    const res = await fetch(url, { ...defaults, ...options });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'API error');
    }
    return res.json();
}


// ── Load Stats ──

async function loadStats() {
    try {
        const stats = await apiFetch('/api/stats');
        document.getElementById('stat-positions').textContent = formatNumber(stats.positions);
        document.getElementById('stat-vessels').textContent = formatNumber(stats.vessels);
        document.getElementById('stat-gaps').textContent = formatNumber(stats.gaps);
    } catch (e) {
        console.warn('Could not load stats:', e);
    }
}


// ── Vessel Search ──

let searchTimeout = null;
const searchInput = document.getElementById('vessel-search');
const searchResults = document.getElementById('search-results');

searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    const q = searchInput.value.trim();
    if (q.length < 2) {
        searchResults.classList.add('hidden');
        return;
    }
    searchTimeout = setTimeout(() => searchVessels(q), 300);
});

searchInput.addEventListener('focus', () => {
    if (searchResults.children.length > 0) {
        searchResults.classList.remove('hidden');
    }
});

document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-container')) {
        searchResults.classList.add('hidden');
    }
});

async function searchVessels(query) {
    try {
        const results = await apiFetch(`/api/vessels/search?q=${encodeURIComponent(query)}`);
        searchResults.innerHTML = '';
        if (results.length === 0) {
            searchResults.innerHTML = '<div class="search-result-item"><span class="search-result-name" style="color:var(--text-muted)">No vessels found</span></div>';
        } else {
            results.forEach(v => {
                const div = document.createElement('div');
                div.className = 'search-result-item';
                div.innerHTML = `
                    <div class="search-result-name">${v.vessel_name || 'Unknown'}</div>
                    <div class="search-result-mmsi">MMSI: ${v.mmsi} · Type: ${v.vessel_type || '—'}</div>
                `;
                div.addEventListener('click', () => selectVessel(v));
                searchResults.appendChild(div);
            });
        }
        searchResults.classList.remove('hidden');
    } catch (e) {
        console.error('Search error:', e);
    }
}

function selectVessel(vessel) {
    state.selectedVessel = vessel;
    searchInput.value = `${vessel.vessel_name || 'Unknown'} (${vessel.mmsi})`;
    searchResults.classList.add('hidden');
    document.getElementById('btn-load-track').disabled = false;
    document.getElementById('btn-detect-gaps').disabled = false;
}


// ── Map: Load Track ──

document.getElementById('btn-load-track').addEventListener('click', loadTrackOnMap);

async function loadTrackOnMap() {
    if (!state.selectedVessel) return;

    const startTime = document.getElementById('time-start').value;
    const endTime = document.getElementById('time-end').value;

    showLoading('Loading vessel track...');
    try {
        const geojson = await apiFetch('/api/vessels/track', {
            method: 'POST',
            body: JSON.stringify({
                identifier: String(state.selectedVessel.mmsi),
                start_time: startTime,
                end_time: endTime,
            }),
        });

        renderTrackOnMap(geojson);

        // Show info panel
        showTrackInfo(geojson.metadata);

    } catch (e) {
        alert('Error loading track: ' + e.message);
    } finally {
        hideLoading();
    }
}

function renderTrackOnMap(geojson) {
    // Clear existing track layers
    clearTrackLayers();

    const bounds = [];

    geojson.features.forEach(feature => {
        const props = feature.properties;
        const geom = feature.geometry;

        if (props.type === 'track_segment') {
            const coords = geom.coordinates.map(c => [c[1], c[0]]);
            const color = speedColor(props.sog);
            const line = L.polyline(coords, {
                color: color,
                weight: 3.5,
                opacity: 0.85,
            }).addTo(map);

            line.bindTooltip(`
                <b>Time:</b> ${props.timestamp || 'N/A'}<br>
                <b>SOG:</b> ${props.sog !== null ? props.sog + ' kn' : 'N/A'}<br>
                <b>COG:</b> ${props.cog !== null ? props.cog + '°' : 'N/A'}
            `, { sticky: true });

            state.trackLayers.push(line);
            coords.forEach(c => bounds.push(c));

        } else if (props.type === 'start') {
            const latlng = [geom.coordinates[1], geom.coordinates[0]];
            const marker = L.circleMarker(latlng, {
                radius: 8,
                fillColor: '#10b981',
                fillOpacity: 1,
                color: '#064e3b',
                weight: 2,
            }).addTo(map);
            marker.bindPopup(`<b>▶ START</b><br>Time: ${props.timestamp}<br>SOG: ${props.sog} kn`);
            state.markerLayers.push(marker);
            bounds.push(latlng);

        } else if (props.type === 'end') {
            const latlng = [geom.coordinates[1], geom.coordinates[0]];
            const marker = L.circleMarker(latlng, {
                radius: 8,
                fillColor: '#ef4444',
                fillOpacity: 1,
                color: '#7f1d1d',
                weight: 2,
            }).addTo(map);
            marker.bindPopup(`<b>⏹ END</b><br>Time: ${props.timestamp}<br>SOG: ${props.sog} kn`);
            state.markerLayers.push(marker);
            bounds.push(latlng);
        }
    });

    // Fit map to track bounds
    if (bounds.length > 0) {
        map.fitBounds(bounds, { padding: [50, 50], maxZoom: 14 });
    }
}


// ── Map: Detect Gaps ──

document.getElementById('btn-detect-gaps').addEventListener('click', loadGapsOnMap);

async function loadGapsOnMap() {
    if (!state.selectedVessel) return;

    const startTime = document.getElementById('time-start').value;
    const endTime = document.getElementById('time-end').value;

    showLoading('Detecting dark activity...');
    try {
        const geojson = await apiFetch('/api/vessels/gaps', {
            method: 'POST',
            body: JSON.stringify({
                identifier: String(state.selectedVessel.mmsi),
                start_time: startTime,
                end_time: endTime,
            }),
        });

        renderGapsOnMap(geojson);

        // Show gap info
        showGapInfo(geojson.metadata);

    } catch (e) {
        alert('Error detecting gaps: ' + e.message);
    } finally {
        hideLoading();
    }
}

function renderGapsOnMap(geojson) {
    // Clear existing gap layers
    state.gapLayers.forEach(l => map.removeLayer(l));
    state.gapLayers = [];

    geojson.features.forEach(feature => {
        const props = feature.properties;
        const geom = feature.geometry;

        if (props.type === 'gap') {
            const coords = geom.coordinates.map(c => [c[1], c[0]]);
            const line = L.polyline(coords, {
                color: '#ef4444',
                weight: 3,
                opacity: 0.9,
                dashArray: '10, 8',
            }).addTo(map);

            line.bindTooltip(`
                <b>⚠️ AIS GAP</b><br>
                Duration: ${props.duration_minutes} min<br>
                Jump: ${props.jump_distance_km} km<br>
                Implied speed: ${props.implied_speed_knots} kn<br>
                Start: ${props.gap_start}<br>
                End: ${props.gap_end}
            `, { sticky: true });

            state.gapLayers.push(line);

        } else if (props.type === 'gap_start') {
            const latlng = [geom.coordinates[1], geom.coordinates[0]];
            const marker = L.circleMarker(latlng, {
                radius: 6,
                fillColor: '#ef4444',
                fillOpacity: 0.9,
                color: '#991b1b',
                weight: 2,
            }).addTo(map);
            marker.bindTooltip(`Signal lost: ${props.time}`);
            state.gapLayers.push(marker);

        } else if (props.type === 'gap_end') {
            const latlng = [geom.coordinates[1], geom.coordinates[0]];
            const marker = L.circleMarker(latlng, {
                radius: 6,
                fillColor: '#f59e0b',
                fillOpacity: 0.9,
                color: '#92400e',
                weight: 2,
            }).addTo(map);
            marker.bindTooltip(`Signal resumed: ${props.time}`);
            state.gapLayers.push(marker);
        }
    });
}


// ── Map: Clear ──

document.getElementById('btn-clear-map').addEventListener('click', () => {
    clearTrackLayers();
    clearGapLayers();
    clearAOITracks();
    if (currentAOILayer) {
        map.removeLayer(currentAOILayer);
        currentAOILayer = null;
    }
    document.getElementById('map-info-panel').classList.add('hidden');
});

function clearTrackLayers() {
    state.trackLayers.forEach(l => map.removeLayer(l));
    state.trackLayers = [];
    state.markerLayers.forEach(l => map.removeLayer(l));
    state.markerLayers = [];
}

function clearGapLayers() {
    state.gapLayers.forEach(l => map.removeLayer(l));
    state.gapLayers = [];
}


// ── Map Info Panel ──

function showTrackInfo(metadata) {
    const panel = document.getElementById('map-info-panel');
    const content = document.getElementById('map-info-content');
    content.innerHTML = `
        <h4>🚢 ${metadata.vessel_name || 'Unknown Vessel'}</h4>
        <div class="info-row">
            <span class="info-label">MMSI</span>
            <span class="info-value">${metadata.mmsi}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Points</span>
            <span class="info-value">${formatNumber(metadata.points_returned)} / ${formatNumber(metadata.total_points)}</span>
        </div>
    `;
    panel.classList.remove('hidden');
}

function showGapInfo(metadata) {
    const panel = document.getElementById('map-info-panel');
    const content = document.getElementById('map-info-content');
    const existing = content.innerHTML;
    content.innerHTML = existing + `
        <div style="margin-top:12px; padding-top:12px; border-top: 1px solid rgba(255,255,255,0.06)">
            <h4>⚠️ Dark Activity</h4>
            <div class="info-row">
                <span class="info-label">Gaps Found</span>
                <span class="info-value" style="color: ${metadata.gaps_found > 0 ? '#ef4444' : '#10b981'}">${metadata.gaps_found}</span>
            </div>
            <div style="font-size:11px; color:var(--text-muted); margin-top:6px; line-height:1.5;">
                ${metadata.assessment}
            </div>
        </div>
    `;
    panel.classList.remove('hidden');
}

document.getElementById('btn-close-info').addEventListener('click', () => {
    document.getElementById('map-info-panel').classList.add('hidden');
});


// ── Chat System ──

const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const btnSend = document.getElementById('btn-send');

// Auto-resize textarea
chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
});

// Send on Enter (Shift+Enter for newline)
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

btnSend.addEventListener('click', sendMessage);

// Suggestion chips
document.querySelectorAll('.suggestion-chip').forEach(chip => {
    chip.addEventListener('click', () => {
        const query = chip.dataset.query;
        chatInput.value = query;
        sendMessage();
    });
});

// Clear chat
document.getElementById('btn-clear-chat').addEventListener('click', async () => {
    chatMessages.innerHTML = '';
    try {
        await apiFetch(`/api/chat/reset?session_id=${state.sessionId}`, { method: 'POST' });
    } catch (e) { /* ignore */ }
    // Re-add welcome
    addWelcomeMessage();
});


function addWelcomeMessage() {
    chatMessages.innerHTML = `
        <div class="welcome-card">
            <div class="welcome-icon">🤖</div>
            <h3>AIS Intelligence Analyst</h3>
            <p>Ask me about vessel movements, dark activity, positions, or generate visualizations on the map.</p>
            <div class="suggestions">
                <button class="suggestion-chip" data-query="Where was OCEAN WARLOCK on Dec 24, 2025?">📍 Where was OCEAN WARLOCK?</button>
                <button class="suggestion-chip" data-query="Show me the track of MMSI 316004661 on Dec 24, 2025">🗺️ Track MMSI 316004661</button>
                <button class="suggestion-chip" data-query="Find vessels near latitude 47.56, longitude -122.34 at midnight Dec 24, 2025">🔍 Vessels near Seattle</button>
                <button class="suggestion-chip" data-query="Get info about vessel JACK BINION">ℹ️ Vessel info</button>
            </div>
        </div>
    `;
    // Re-bind suggestion chips
    document.querySelectorAll('.suggestion-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            chatInput.value = chip.dataset.query;
            sendMessage();
        });
    });
}


async function sendMessage() {
    const message = chatInput.value.trim();
    if (!message || state.isProcessing) return;

    state.isProcessing = true;
    btnSend.disabled = true;

    // Remove welcome card
    const welcome = chatMessages.querySelector('.welcome-card');
    if (welcome) welcome.remove();

    // Add user message
    appendMessage('user', message);
    chatInput.value = '';
    chatInput.style.height = 'auto';

    // Add typing indicator
    const typingEl = appendTypingIndicator();

    try {
        const result = await apiFetch('/api/chat', {
            method: 'POST',
            body: JSON.stringify({
                message: message,
                session_id: state.sessionId,
            }),
        });

        // Remove typing indicator
        typingEl.remove();

        // Add assistant response
        appendMessage('assistant', result.response);

        // If agent generated a map, try to parse track data from the response
        // and offer to visualize on map
        if (result.map_data) {
            // The agent already generated a Folium map, but we can also
            // try to load the track data onto our Leaflet map
            tryAutoLoadTrack(result.response);
        }

    } catch (e) {
        typingEl.remove();
        appendMessage('assistant', `⚠️ Error: ${e.message}`);
    } finally {
        state.isProcessing = false;
        btnSend.disabled = false;
    }
}

function appendMessage(role, content) {
    const div = document.createElement('div');
    div.className = `message ${role}`;

    const roleLabel = role === 'user' ? 'You' : '🤖 AIS Analyst';

    // Basic markdown-like formatting for assistant messages
    let formattedContent = content;
    if (role === 'assistant') {
        formattedContent = formatMarkdown(content);
    }

    div.innerHTML = `
        <div class="message-role">${roleLabel}</div>
        <div class="message-bubble">${formattedContent}</div>
    `;

    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

function appendTypingIndicator() {
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.innerHTML = `
        <div class="message-role">🤖 AIS Analyst</div>
        <div class="typing-indicator">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

function formatMarkdown(text) {
    // Simple markdown formatting
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code style="background:rgba(59,130,246,0.1);padding:1px 4px;border-radius:3px;font-family:JetBrains Mono,monospace;font-size:11px;">$1</code>')
        .replace(/\n/g, '<br>');
}

function tryAutoLoadTrack(responseText) {
    // Try to extract MMSI from response and auto-load on map
    const mmsiMatch = responseText.match(/MMSI[:\s]*(\d{9})/i);
    if (mmsiMatch) {
        const mmsi = parseInt(mmsiMatch[1]);
        // Update the state and select the vessel
        state.selectedVessel = { mmsi: mmsi, vessel_name: '' };
        
        // Update input field text
        const searchInput = document.getElementById('vessel-search');
        if (searchInput) {
            searchInput.value = `MMSI: ${mmsi}`;
        }
        
        // Enable actions
        const btnLoad = document.getElementById('btn-load-track');
        const btnGaps = document.getElementById('btn-detect-gaps');
        if (btnLoad) btnLoad.disabled = false;
        if (btnGaps) btnGaps.disabled = false;
        
        // Auto-load track
        loadTrackOnMap();
    }
}


// ── Map Click: Find Vessels Near ──

map.on('contextmenu', async (e) => {
    const { lat, lng } = e.latlng;
    const timestamp = document.getElementById('time-start').value;

    showLoading('Finding vessels nearby...');
    try {
        const result = await apiFetch('/api/vessels/nearby', {
            method: 'POST',
            body: JSON.stringify({
                lat: lat,
                lon: lng,
                radius_km: 20,
                timestamp: timestamp,
                tolerance_minutes: 30,
            }),
        });

        // Show popup with results
        let popupContent = `<b>Vessels within 20km</b><br>`;
        popupContent += `<span style="font-size:11px;color:#94a3b8;">at ${lat.toFixed(4)}, ${lng.toFixed(4)}</span><br><br>`;

        if (result.vessels.length === 0) {
            popupContent += '<em style="color:#64748b;">No vessels found</em>';
        } else {
            result.vessels.slice(0, 10).forEach(v => {
                popupContent += `
                    <div style="padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:12px;">
                        <b>${v.vessel_name || 'Unknown'}</b>
                        <span style="color:#94a3b8;font-family:monospace;"> ${v.mmsi}</span>
                        <span style="color:#64748b;float:right;">${v.distance_km} km</span>
                    </div>
                `;
            });
            if (result.vessels.length > 10) {
                popupContent += `<br><em style="color:#64748b;">+${result.vessels.length - 10} more...</em>`;
            }
        }

        L.popup({ maxWidth: 320 })
            .setLatLng(e.latlng)
            .setContent(popupContent)
            .openOn(map);

    } catch (e) {
        console.error('Nearby search error:', e);
    } finally {
        hideLoading();
    }
});


// ── Initialize ──

loadStats();
