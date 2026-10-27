-- Existing PostgreSQL installations only; fresh databases already use VARCHAR(32).
BEGIN;
ALTER TABLE watchlist ALTER COLUMN ticker TYPE VARCHAR(32);
ALTER TABLE reports ALTER COLUMN ticker TYPE VARCHAR(32);
COMMIT;
