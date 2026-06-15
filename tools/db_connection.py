"""
Database connection pool manager.
Uses psycopg2's ThreadedConnectionPool for concurrent access from the agent.
"""

import os
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

_pool = None


def _get_pool():
    global _pool
    if _pool is None or _pool.closed:
        _pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=os.getenv('DB_HOST', 'localhost'),
            port=os.getenv('DB_PORT', '5432'),
            dbname=os.getenv('DB_NAME', 'ais_vessel_intel'),
            user=os.getenv('DB_USER', 'postgres'),
            password=os.getenv('DB_PASSWORD', ''),
        )
    return _pool


@contextmanager
def get_cursor():
    """Context manager that yields a cursor from the connection pool."""
    p = _get_pool()
    conn = p.getconn()
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SET TIME ZONE 'UTC';")
        yield cur
        cur.close()
    finally:
        p.putconn(conn)


def get_connection():
    """Get a raw connection (caller must return it)."""
    conn = _get_pool().getconn()
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC';")
    return conn


def return_connection(conn):
    """Return a connection to the pool."""
    _get_pool().putconn(conn)
