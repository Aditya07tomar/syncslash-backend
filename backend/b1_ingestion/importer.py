import json
from backend.db.connection import run_query, get_connection
from backend.b1_ingestion.pattern_matcher import run_pipeline
from backend.b1_ingestion.plaid_client import (
    create_sandbox_token,
    exchange_for_access_token,
    fetch_transactions
)


def setup_sandbox_user(user_id: int):
    """
    Full flow for connecting a sandbox bank account to a user:
    1. Create fake public token
    2. Exchange for access token
    3. Store access token in Users table
    Returns the access token.
    """
    public_token  = create_sandbox_token()
    access_token  = exchange_for_access_token(public_token)

    run_query(
        "UPDATE Users SET plaid_token = %s WHERE user_id = %s",
        params=(access_token, user_id),
        fetch=False
    )
    print(f"[importer] Access token stored for user {user_id}")
    return access_token


def import_transactions(user_id: int, access_token: str):
    """
    Fetches transactions from Plaid sandbox and inserts
    them into Transaction_Logs. Uses ON CONFLICT DO NOTHING
    so re-running never creates duplicates (idempotent).
    Returns count of newly inserted rows.
    """
    transactions = fetch_transactions(access_token)
    print(f"[importer] Fetched {len(transactions)} transactions from Plaid")

    inserted = 0
    conn = get_connection()
    cur  = conn.cursor()

    for txn in transactions:
        try:
            cur.execute("""
                INSERT INTO Transaction_Logs
                    (user_id, plaid_txn_id, merchant_name,
                     description, amount, txn_date, raw_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (plaid_txn_id) DO NOTHING
            """, (
                user_id,
                txn.transaction_id,
                txn.merchant_name or txn.name,
                txn.name,
                abs(float(txn.amount)),   # Plaid uses negative for debits
                txn.date,
                json.dumps(txn.to_dict(), default=str)
            ))
            inserted += cur.rowcount
        except Exception as e:
            print(f"[importer] Skipped transaction {txn.transaction_id}: {e}")
            continue

    conn.commit()    
    cur.close()
    conn.close()
    print(f"[importer] Inserted {inserted} new transactions")
    # NEW: run classification pipeline immediately after import
    # Why here and not separately?
    # Because fresh data should be classified before the API
    # returns a response. The frontend expects subscriptions
    # to be ready as soon as sync completes.
    pipeline_result = run_pipeline(user_id)

    return {
        "transactions_imported": inserted,
        **pipeline_result  # merge pipeline results into response
    }