"""
Database initialization script for deployment.
Runs schema.sql + analytics_schema.sql to set up all tables,
stored procedures, views, and seed data.
Called automatically on server startup.
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def init_database():
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        print("⚠️ No DATABASE_URL set, skipping DB init")
        return

    # Render uses postgres:// but psycopg2 needs postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        # Check if tables already exist
        cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')")
        tables_exist = cur.fetchone()[0]

        if not tables_exist:
            print("🔧 Creating database tables...")
            schema_path = os.path.join(os.path.dirname(__file__), "db", "schema.sql")
            with open(schema_path, "r") as f:
                cur.execute(f.read())
            conn.commit()
            print("✅ Schema loaded")

            # Load analytics stored procedures & views
            analytics_path = os.path.join(os.path.dirname(__file__), "db", "analytics_schema.sql")
            if os.path.exists(analytics_path):
                with open(analytics_path, "r") as f:
                    cur.execute(f.read())
                conn.commit()
                print("✅ Analytics schema loaded")
        else:
            print("✅ Database tables already exist")

            # Ensure analytics functions exist (they might be missing)
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_proc WHERE proname = 'generatefatiguescore'
                )
            """)
            if not cur.fetchone()[0]:
                print("🔧 Loading analytics schema...")
                analytics_path = os.path.join(os.path.dirname(__file__), "db", "analytics_schema.sql")
                if os.path.exists(analytics_path):
                    with open(analytics_path, "r") as f:
                        cur.execute(f.read())
                    conn.commit()
                    print("✅ Analytics schema loaded")

        # Ensure groups tables exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS Subscription_Groups (
                group_id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                invite_code VARCHAR(10) UNIQUE NOT NULL,
                sub_id INT REFERENCES Subscriptions(sub_id),
                creator_id INT REFERENCES Users(user_id),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS Group_Members (
                id SERIAL PRIMARY KEY,
                group_id INT REFERENCES Subscription_Groups(group_id) ON DELETE CASCADE,
                user_id INT REFERENCES Users(user_id),
                joined_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(group_id, user_id)
            )
        """)
        conn.commit()
        print("✅ Groups tables ready")

        cur.close()
        conn.close()
        print("🚀 Database initialization complete!")

    except Exception as e:
        print(f"❌ Database init error: {e}")


if __name__ == "__main__":
    init_database()
