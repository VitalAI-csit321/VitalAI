-- Enable pgvector extension on database initialisation.
-- This script runs once when the postgres data directory is first created.
CREATE EXTENSION IF NOT EXISTS vector;
