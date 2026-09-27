-- Queries filter raw_measures on a sensor and a time range (graphs, last values, consolidation),
-- but only (epochtimestamp) and the foreign key's (sensor) are indexed.
-- INPLACE / LOCK=NONE: built without blocking the per-minute inserts (can take minutes on a big table).
ALTER TABLE raw_measures
    ADD INDEX IF NOT EXISTS sensor_epoch (sensor, epochtimestamp),
    ALGORITHM=INPLACE, LOCK=NONE;
