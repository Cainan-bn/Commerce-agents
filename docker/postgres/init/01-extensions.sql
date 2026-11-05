-- Extensões e bancos auxiliares da stack local.
-- Executado apenas na primeira inicialização do volume do Postgres.
CREATE EXTENSION IF NOT EXISTS vector;

-- Banco dedicado ao Langfuse (self-host v3).
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
