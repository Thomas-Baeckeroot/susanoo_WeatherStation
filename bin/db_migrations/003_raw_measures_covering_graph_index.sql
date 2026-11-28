-- Graph queries (chart.fetch_buckets) read the (epochtimestamp, measure) of one sensor over a time range. With
-- measure in the index they read the index alone, instead of one lookup in the table per measure: a year of a
-- sensor (52k lookups, scattered over the whole year of the table) took ~20 s on the NAS.
-- Replaces sensor_epoch (001), of which it is an extension: same uses, one index less to maintain.
-- INPLACE / LOCK=NONE: built without blocking the per-minute inserts (can take long on a big table, see the
-- remarks on LOCK_WAIT_TIMEOUT in db_migrate.sh for a remote Pi).
ALTER TABLE raw_measures
    ADD INDEX IF NOT EXISTS sensor_epoch_measure (sensor, epochtimestamp, measure),
    DROP INDEX IF EXISTS sensor_epoch,
    ALGORITHM=INPLACE, LOCK=NONE;
