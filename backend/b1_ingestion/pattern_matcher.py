from backend.db.connection import run_query

def run_pipeline(user_id: int) -> dict:
    """
    Runs the full B1 classification pipeline for a user.
    Why call a stored function instead of writing the SQL here?
    Because the classification logic involves two sequential UPDATE
    statements that must be atomic. If we ran them as separate
    Python calls, a crash between them leaves data half-processed.
    The PostgreSQL function wraps both in one transaction.
    Alternative: use Python's psycopg2 transaction management
    (conn.autocommit = False, then commit manually).
    Why not? The stored function keeps the logic in one place.
    If we need to call this from a cron job or another service,
    they all use the same function without duplicating logic.
    """

    # Step 1: run pattern matching + recurrence detection
    result = run_query(
        "SELECT * FROM run_classification_pipeline(%s)",
        params=(user_id,)
    )
    pass1 = result[0]['pass1_updated']
    pass2 = result[0]['pass2_updated']
    print(f"[pipeline] Pass 1 (pattern match): {pass1} rows classified")
    print(f"[pipeline] Pass 2 (recurrence):    {pass2} rows classified")

    # Step 2: promote classified transactions to Subscriptions table
    promoted = run_query(
        "SELECT upsert_detected_subscriptions(%s) AS count",
        params=(user_id,)
    )
    sub_count = promoted[0]['count']
    print(f"[pipeline] Subscriptions upserted: {sub_count}")

    return {
        "pass1_pattern_matches": pass1,
        "pass2_recurrence_detected": pass2,
        "subscriptions_updated": sub_count
    }