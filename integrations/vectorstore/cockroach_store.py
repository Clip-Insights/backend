from langchain_postgres.vectorstores import PGVector
from sqlalchemy import text
import logging
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DB_NAME = os.getenv("DATABASE_NAME", "clipinsights")
DB_USER = os.getenv("DATABASE_USER", "postgres")
DB_PASSWORD = os.getenv("DATABASE_PASSWORD", "root")
DB_HOST = os.getenv("DATABASE_HOST", "localhost")
DB_PORT = os.getenv("DATABASE_PORT", "5432")
DB_CERT_PATH = os.getenv("DATABASE_CERT_PATH", "")

CONNECTION_STRING = (
    f"cockroachdb+psycopg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    f"?sslmode=verify-full&sslrootcert={DB_CERT_PATH}"
)


class CockroachVectorStore(PGVector):
    def create_vector_extension(self):
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
            old_pk = self._column_exists(session, "langchain_pg_embedding", "uuid")
            new_pk = self._column_exists(session, "langchain_pg_embedding", "id")
            if old_pk and not new_pk:
                logger.warning("Detected old embedding table schema; recreating tables.")
                session.execute(text("DROP TABLE IF EXISTS langchain_pg_embedding CASCADE"))
                session.execute(text("DROP TABLE IF EXISTS langchain_pg_collection CASCADE"))

            session.execute(text("""
                CREATE TABLE IF NOT EXISTS langchain_pg_collection (
                    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR,
                    cmetadata JSONB
                )
            """))
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

        try:
            with self._make_sync_session() as session:
                session.execute(text("""
                    CREATE INDEX IF NOT EXISTS ix_cmetadata_gin
                    ON langchain_pg_embedding USING GIN (cmetadata jsonb_path_ops)
                """))
                session.commit()
        except Exception as e:
            logger.info("GIN index on cmetadata not created: %s", e)

    def drop_tables(self) -> None:
        with self._make_sync_session() as session:
            session.execute(text("DROP TABLE IF EXISTS langchain_pg_embedding CASCADE"))
            session.execute(text("DROP TABLE IF EXISTS langchain_pg_collection CASCADE"))
            session.commit()
