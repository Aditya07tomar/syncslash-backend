import psycopg2
import psycopg2.extras  # gives us dict cursor — returns rows as dicts
import os
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    """
    Opens and returns a raw psycopg2 database connection.
    Why not keep one connection open permanently?
    Database connections consume server memory.
    PostgreSQL has a connection limit (default 100).
    Opening per-request and closing after is called
    connection-per-request pattern.
    Alternative: connection pooling with pgBouncer or
    psycopg2's ThreadedConnectionPool — keeps a fixed
    pool of connections open and reuses them.
    For our scale (demo project), per-request is fine.
    """
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def run_query(sql: str, params=None, fetch=True):
    """
    Universal query runner.
    Why RealDictCursor?
    Default psycopg2 cursor returns tuples: (1, 'Netflix', 649)
    RealDictCursor returns dicts: {'user_id':1, 'name':'Netflix'}
    FastAPI serializes dicts to JSON automatically.
    Tuples need manual conversion. Dicts are safer and cleaner.
    fetch=True  → SELECT queries, returns list of dicts
    fetch=False → INSERT/UPDATE/DELETE, returns affected row count
    """
    conn = get_connection()
    # RealDictCursor makes every row a real Python dictionary
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(sql, params)
        if fetch:
            rows = cur.fetchall()
            conn.commit()
            # Convert from RealDictRow to plain dict for JSON serialization
            # Also handle Decimal and date types that FastAPI can't serialize
            from decimal import Decimal
            from datetime import date, datetime
            cleaned = []
            for row in rows:
                d = {}
                for k, v in dict(row).items():
                    if isinstance(v, Decimal):
                        d[k] = float(v)
                    elif isinstance(v, (date, datetime)):
                        d[k] = str(v)
                    else:
                        d[k] = v
                cleaned.append(d)
            return cleaned
        else:
            conn.commit()
            return cur.rowcount
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()