from langchain_postgres.vectorstores import PGVector
from sqlalchemy import text
import logging
import os
from dotenv import load_dotenv
load_dotenv()
logger = logging.getLogger(__name__)
# Database Configuration for PGVector
DB_NAME = os.getenv("DATABASE_NAME", "clipinsights")
DB_USER = os.getenv("DATABASE_USER", "postgres")
DB_PASSWORD = os.getenv("DATABASE_PASSWORD", "root")
DB_HOST = os.getenv("DATABASE_HOST", "localhost")
DB_PORT = os.getenv("DATABASE_PORT", "5432")
DB_CERT_PATH = os.getenv("DATABASE_CERT_PATH", "")

CONNECTION_STRING = f"cockroachdb+psycopg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode=verify-full&sslrootcert={DB_CERT_PATH}"

class CockroachVectorStore(PGVector):
    """
    Custom wrapper around PGVector to support CockroachDB Serverless.
    It bypasses the 'pg_advisory_xact_lock' and 'CREATE EXTENSION' calls
    which are forbidden on CockroachDB Serverless.
    """
    
    def create_vector_extension(self):
        """
        OVERRIDE: Do nothing.
        CockroachDB Serverless has the 'vector' extension pre-installed.
        The original method tries to run 'pg_advisory_xact_lock' which crashes.
        """
        logger.info("✓ Skipping extension creation (Native in CockroachDB)")
        pass

    def create_tables_if_not_exists(self):
         with self._make_sync_session() as session:
            session.execute(text("""CREATE TABLE IF NOT EXISTS langchain_pg_collection (
                                        name VARCHAR,
                                        cmetadata JSONB,
                                        uuid UUID PRIMARY KEY DEFAULT gen_random_uuid()
                                    );
                                """))
            session.execute(text("""CREATE TABLE IF NOT EXISTS langchain_pg_embedding (
                                        collection_id UUID REFERENCES langchain_pg_collection(uuid) ON DELETE CASCADE,
                                        embedding vector(384), -- Ensure this matches your model (MiniLM-L6-v2 is 384)
                                        document VARCHAR,
                                        cmetadata JSONB,
                                        custom_id VARCHAR,
                                        uuid UUID PRIMARY KEY DEFAULT gen_random_uuid()
                                    );"""))
            session.execute(text("""CREATE INDEX IF NOT EXISTS langchain_pg_embedding_collection_id_idx
                                    ON langchain_pg_embedding (collection_id);"""))
            session.commit()

    def drop_tables(self):
        """
        OVERRIDE: Use CASCADE for CockroachDB compliance if ever called.
        """
        with self._make_sync_session() as session:
            session.execute(text("DROP TABLE IF EXISTS langchain_pg_embedding CASCADE"))
            session.execute(text("DROP TABLE IF EXISTS langchain_pg_collection CASCADE"))
            session.commit()