import os
from dotenv import load_dotenv

load_dotenv()

try:
    from neo4j import GraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    print("⚠️ neo4j package not installed — graph features disabled")

class Neo4jConnection:
    def __init__(self):
        self.__driver = None
        if not NEO4J_AVAILABLE:
            return
        self.__uri = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
        self.__user = os.getenv("NEO4J_USER", "neo4j")
        self.__password = os.getenv("NEO4J_PASSWORD", "password")
        try:
            self.__driver = GraphDatabase.driver(self.__uri, auth=(self.__user, self.__password))
        except Exception as e:
            print("Failed to create the driver:", e)

    def close(self):
        if self.__driver is not None:
            self.__driver.close()

    def query(self, query, parameters=None, db=None):
        if self.__driver is None:
            return []
        session = None
        response = None
        try: 
            session = self.__driver.session(database=db) if db is not None else self.__driver.session() 
            response = list(session.run(query, parameters))
        except Exception as e:
            print("Query failed:", e)
        finally: 
            if session is not None:
                session.close()
        return response

db_neo4j = Neo4jConnection()