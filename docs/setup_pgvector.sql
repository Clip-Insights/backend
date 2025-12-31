-- PGVector Setup Script for ClipInsights
-- Run this script after connecting to your PostgreSQL database

-- Connect to the clipinsights database
-- docker exec -it postgres psql -U postgres -d clipinsights

-- 1. Enable the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Verify the extension is installed
SELECT * FROM pg_extension WHERE extname = 'vector';

-- 3. Check existing LangChain tables (they will be created automatically by the app)
-- But you can verify they exist after running the app once:
-- \d langchain_pg_collection
-- \d langchain_pg_embedding

-- 4. Optional: View statistics
-- SELECT 
--     collection_name,
--     COUNT(*) as embedding_count
-- FROM langchain_pg_embedding e
-- JOIN langchain_pg_collection c ON e.collection_id = c.uuid
-- GROUP BY collection_name;

-- 5. Optional: Clean up old embeddings for a specific video
-- DELETE FROM langchain_pg_embedding 
-- WHERE collection_id IN (
--     SELECT uuid FROM langchain_pg_collection 
--     WHERE name = 'video_transcripts'
-- )
-- AND cmetadata->>'youtube_url' = 'YOUR_YOUTUBE_URL_HERE';

-- 6. Check database size
SELECT 
    pg_size_pretty(pg_database_size('clipinsights')) as database_size;

-- Notes:
-- - The pgvector extension must be installed in PostgreSQL
-- - Tables will be auto-created by LangChain on first use
-- - Default collection name is 'video_transcripts'
-- - Embedding dimension is 384 (from all-MiniLM-L6-v2 model)

-- Troubleshooting:
-- If you get "extension does not exist":
-- 1. Install pgvector: apt-get install postgresql-14-pgvector (on Ubuntu)
-- 2. Or follow: https://github.com/pgvector/pgvector#installation

NOTIFY pgvector_setup_complete, 'PGVector is ready for ClipInsights!';
