-- Run this if you see 'no such column: like_count'
-- Windows:
--   sqlite3.exe bowling.sqlite3 < tools/sql_fix_like_count.sql
-- Linux/macOS:
--   sqlite3 bowling.sqlite3 < tools/sql_fix_like_count.sql

ALTER TABLE games ADD COLUMN like_count INTEGER NOT NULL DEFAULT 0;
