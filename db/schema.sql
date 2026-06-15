-- =============================================================
-- AIS Vessel Intelligence System — Database Schema
-- =============================================================

-- Enable PostGIS for spatial queries
CREATE EXTENSION IF NOT EXISTS postgis;

-- =============================================================
-- 1. ais_positions — Core AIS position reports
-- =============================================================
CREATE TABLE IF NOT EXISTS ais_positions (
    mmsi            BIGINT          NOT NULL,
    base_date_time  TIMESTAMPTZ     NOT NULL,
    geom            GEOGRAPHY(POINT, 4326),
    longitude       DOUBLE PRECISION,
    latitude        DOUBLE PRECISION,
    sog             REAL,           -- speed over ground (knots)
    cog             REAL,           -- course over ground
    heading         REAL,
    status          SMALLINT,       -- navigational status code
    draft           REAL
);

-- Primary lookup: vessel track over time
CREATE INDEX IF NOT EXISTS idx_ais_pos_mmsi_time
    ON ais_positions (mmsi, base_date_time);

-- Spatial index for proximity queries
CREATE INDEX IF NOT EXISTS idx_ais_pos_geom
    ON ais_positions USING GIST (geom);

-- BRIN index for efficient time-range scans on naturally ordered data
CREATE INDEX IF NOT EXISTS idx_ais_pos_time_brin
    ON ais_positions USING BRIN (base_date_time)
    WITH (pages_per_range = 32);

-- =============================================================
-- 2. vessels — Slowly-changing vessel reference table
-- =============================================================
CREATE TABLE IF NOT EXISTS vessels (
    mmsi            BIGINT      PRIMARY KEY,
    vessel_name     TEXT,
    imo             TEXT,
    call_sign       TEXT,
    vessel_type     SMALLINT,
    length          REAL,
    width           REAL,
    cargo           SMALLINT,
    transceiver     TEXT,
    last_updated    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vessels_name
    ON vessels (vessel_name);

-- =============================================================
-- 3. ais_gaps — Precomputed signal gaps / dark activity periods
-- =============================================================
CREATE TABLE IF NOT EXISTS ais_gaps (
    id                  SERIAL PRIMARY KEY,
    mmsi                BIGINT      NOT NULL,
    gap_start           TIMESTAMPTZ NOT NULL,
    gap_end             TIMESTAMPTZ NOT NULL,
    duration_minutes    REAL        NOT NULL,
    start_lat           DOUBLE PRECISION,
    start_lon           DOUBLE PRECISION,
    end_lat             DOUBLE PRECISION,
    end_lon             DOUBLE PRECISION,
    jump_distance_km    REAL,
    implied_speed_knots REAL
);

CREATE INDEX IF NOT EXISTS idx_gaps_mmsi
    ON ais_gaps (mmsi);

CREATE INDEX IF NOT EXISTS idx_gaps_time
    ON ais_gaps (gap_start, gap_end);

-- =============================================================
-- 4. tracks_simplified — Simplified daily tracks per vessel
-- =============================================================
CREATE TABLE IF NOT EXISTS tracks_simplified (
    mmsi            BIGINT      NOT NULL,
    track_date      DATE        NOT NULL,
    geom            GEOGRAPHY(LINESTRING, 4326),
    point_count     INT,
    PRIMARY KEY (mmsi, track_date)
);
