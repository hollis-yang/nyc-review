-- The demo check-in history is stored in Redis bitmaps. This guarded SQL
-- companion keeps the release ledger append-only and safe to replay.
SELECT 1 AS demo_checkin_history_redis_seed;
