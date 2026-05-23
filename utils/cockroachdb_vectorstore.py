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
    Bypasses pg_advisory_xact_lock and CREATE EXTENSION which are
    forbidden on CockroachDB Serverless.

    Schema follows langchain_postgres exactly:
      langchain_pg_collection: uuid (PK), name, cmetadata
      langchain_pg_embedding:  id VARCHAR (PK), collection_id, embedding, document, cmetadata
    """

    def create_vector_extension(self):
        # CockroachDB has the vector extension built-in; the parent's
        # implementation calls pg_advisory_xact_lock which is not allowed.
        logger.info("Skipping vector extension creation (built-in to CockroachDB)")

    def _column_exists(self, session, table_name: str, column_name: str) -> bool:
        result = session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :tbl AND column_name = :col"
            ),
            {"tbl": table_name, "col": column_name},
        )
        return result.fetchone() is not None

    def create_tables_if_not_exists(self) -> None:
        with self._make_sync_session() as session:
            # Detect old schema where the embedding table used 'uuid' as PK
            # instead of 'id'. Drop and recreate so langchain_postgres ORM works.
            old_pk = self._column_exists(session, "langchain_pg_embedding", "uuid")
            new_pk = self._column_exists(session, "langchain_pg_embedding", "id")
            if old_pk and not new_pk:
                logger.warning(
                    "Detected old embedding table schema (uuid PK). "
                    "Dropping and recreating with correct schema (id PK). "
                    "Existing embeddings will be lost."
                )
                session.execute(text("DROP TABLE IF EXISTS langchain_pg_embedding CASCADE"))
                session.execute(text("DROP TABLE IF EXISTS langchain_pg_collection CASCADE"))

            # langchain_pg_collection — PK is 'uuid' (langchain_postgres FK target)
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS langchain_pg_collection (
                    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR,
                    cmetadata JSONB
                )
            """))

            # langchain_pg_embedding — PK must be 'id' VARCHAR so that
            # langchain_postgres's INSERT ... ON CONFLICT (id) DO UPDATE works.
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS langchain_pg_embedding (
                    id VARCHAR PRIMARY KEY,
                    collection_id UUID REFERENCES langchain_pg_collection(uuid) ON DELETE CASCADE,
                    embedding vector(384),
                    document VARCHAR,
                    cmetadata JSONB
                )
            """))

            session.execute(text("""
                CREATE INDEX IF NOT EXISTS langchain_pg_embedding_collection_id_idx
                ON langchain_pg_embedding (collection_id)
            """))

            session.commit()

        # GIN/inverted index on cmetadata for metadata filtering.
        # Attempted in a separate transaction so a failure doesn't roll back
        # the table creation above.
        try:
            with self._make_sync_session() as session:
                session.execute(text("""
                    CREATE INDEX IF NOT EXISTS ix_cmetadata_gin
                    ON langchain_pg_embedding USING GIN (cmetadata jsonb_path_ops)
                """))
                session.commit()
        except Exception as e:
            logger.info(
                "GIN index on cmetadata not created (CockroachDB may not support "
                f"jsonb_path_ops operator class): {e}. "
                "Metadata filtering will still work via sequential scan."
            )

    def drop_tables(self) -> None:
        with self._make_sync_session() as session:
            session.execute(text("DROP TABLE IF EXISTS langchain_pg_embedding CASCADE"))
            session.execute(text("DROP TABLE IF EXISTS langchain_pg_collection CASCADE"))
            session.commit()
