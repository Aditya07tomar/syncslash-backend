"""
One-time script to execute analytics_schema.sql against the PostgreSQL database
using psycopg2 (no psql binary needed).
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def run_schema():
    sql_path = os.path.join(os.path.dirname(__file__), "backend", "db", "analytics_schema.sql")
    
    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()
    
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()
    
    try:
        cur.execute(sql)
        conn.commit()
        print("✅ analytics_schema.sql executed successfully!")
        
        # Verify: query ghost view
        cur.execute("SELECT * FROM ghost_subscriptions_view WHERE user_id = 1")
        ghosts = cur.fetchall()
        print(f"   Ghost subscriptions for user 1: {len(ghosts)} found")
        
        # Verify: call fatigue score function
        cur.execute("SELECT * FROM GenerateFatigueScore(1)")
        scores = cur.fetchall()
        print(f"   Fatigue scores for user 1: {len(scores)} subscriptions scored")
        for row in scores:
            print(f"     → {row}")
        
        # Verify: call monthly report
        cur.execute("SELECT * FROM GenerateMonthlyReport(1)")
        report = cur.fetchall()
        print(f"   Monthly report categories: {len(report)}")
        for row in report:
            print(f"     → {row}")
            
    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_schema()