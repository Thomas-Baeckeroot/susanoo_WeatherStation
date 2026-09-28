-- The master (NAS) reads each remote's "SELECT ... WHERE sensor = ? AND synchronised = FALSE ORDER BY epochtimestamp
-- LIMIT n" every minute: without this index the remote scans the whole sensor history (seconds of CPU on a Pi).
ALTER TABLE raw_measures
    ADD INDEX IF NOT EXISTS sensor_sync_epoch (sensor, synchronised, epochtimestamp),
    ALGORITHM=INPLACE, LOCK=NONE;
