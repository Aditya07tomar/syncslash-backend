"""
One-time database setup: run base schema + analytics schema + verify.
Database and user already created in previous run.
"""
import psycopg2

DB_URL = "postgresql://postgres:engr@localhost:5432/suboptimizer"
DB_USER = "subuser"

def setup():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # Step 2: Run base schema
    print("Step 2: Running base schema (schema.sql)...")
    with open("backend/db/schema.sql", "r", encoding="utf-8") as f:
        sql = f.read()
    cur.execute(sql)
    conn.commit()
    print("   [OK] schema.sql executed successfully!")

    # Grant schema permissions to subuser
    cur.execute(f"GRANT ALL ON SCHEMA public TO {DB_USER}")
    cur.execute(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {DB_USER}")
    cur.execute(f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {DB_USER}")
    cur.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {DB_USER}")
    conn.commit()
    print(f"   Granted schema permissions to '{DB_USER}'")

    # Step 3: Run analytics schema
    print("\nStep 3: Running analytics schema (analytics_schema.sql)...")
    with open("backend/db/analytics_schema.sql", "r", encoding="utf-8") as f:
        sql = f.read()
    cur.execute(sql)
    conn.commit()
    print("   [OK] analytics_schema.sql executed successfully!")

    # Grant again for new objects
    cur.execute(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {DB_USER}")
    cur.execute(f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {DB_USER}")
    cur.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {DB_USER}")
    conn.commit()

    # Step 4: Verify
    print("\nStep 4: Verifying...")
    cur.execute("SELECT * FROM ghost_subscriptions_view WHERE user_id = 1")
    ghosts = cur.fetchall()
    print(f"   Ghost subscriptions for user 1: {len(ghosts)} found")

    cur.execute("SELECT * FROM GenerateFatigueScore(1)")
    scores = cur.fetchall()
    print(f"   Fatigue scores for user 1: {len(scores)} subscriptions scored")
    for row in scores:
        print(f"     -> {row[1]}: score={row[6]}, verdict={row[7]}")

    cur.execute("SELECT * FROM GenerateMonthlyReport(1)")
    report = cur.fetchall()
    print(f"   Monthly report: {len(report)} categories")
    for row in report:
        print(f"     -> {row[0]}: {row[1]} subs, Rs.{row[2]}/mo, {row[3]} ghosts, Rs.{row[4]} savings")

    cur.close()
    conn.close()
    print("\n[DONE] Database setup complete!")

if __name__ == "__main__":
    setup()