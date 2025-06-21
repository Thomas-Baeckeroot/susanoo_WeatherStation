CREATE TABLE IF NOT EXISTS sensors
    (   name            VARBINARY(10),  -- (MariaDB)
    --  name  CHAR(8),  -- PRIMARY KEY" -- (PostgreSQL)
        priority        INTEGER,        -- priority value: from 0 to 100; ie: 20 for main values (temp.) TODO Can be optimised as TINYINT
        sensor_label    TEXT,
        decimals        INTEGER,        -- decimal places: 0 = rounded at unit, 1 = 1/10th of unit, ... TODO Can be optimised as TINYINT
        cumulative      BOOLEAN,        -- ie: True for mm of water, false for temperature
        unit            TEXT,
        consolidated    TEXT,           -- time-range (in s.) for consolidation; ie: 900 -> data consolidated per 15 minutes
        sensor_type     TEXT
        -- sensor_config  TEXT          -- ie 'GPIO23'
    );

ALTER TABLE sensors ADD PRIMARY KEY (name);

CREATE TABLE raw_measures
    (   epochtimestamp  INTEGER,        -- seconds since 1970/01/01, https://www.sqlite.org/draft/lang_datefunc.html
        measure         REAL,
        sensor          VARBINARY(8),   -- (MariaDB) ( PostgreSQL: "sensor  CHAR(8),  -- REFERENCES sensors (name)" )
        synchronised    BOOLEAN DEFAULT false NOT NULL
        -- PRIMARY KEY (epochtimestamp, sensor)
    );

# CREATE INDEX epoch_bindex
#     BTREE ON raw_measures (epochtimestamp);
CREATE INDEX epoch_bindex USING BTREE ON raw_measures (epochtimestamp);

ALTER TABLE raw_measures ADD FOREIGN KEY (sensor) REFERENCES sensors (name);

CREATE TABLE consolidated_measures
    (   minepochtime    INTEGER,
        maxepochtime    INTEGER,
        num_values      INTEGER,
        min_value       REAL,
        max_value       REAL,
        mean_value      REAL,
        total_values    REAL,
        sensor          VARBINARY(10),  -- REFERENCES sensors (name) (MariaDB)
    --  sensor          CHAR(8),        -- REFERENCES sensors (name) (PostgreSQL)
        period          INTEGER         -- period in seconds: =900 for 15 minutes periods
    );

CREATE TABLE IF NOT EXISTS captures
    (   sensor_name     VARBINARY(10),  -- REFERENCES sensors (name) (MariaDB)
        filepath_last   TINYTEXT,       -- 255 chars should be enough, extend to TEXT possible
        filepath_data   TINYTEXT        -- last image with visible data
    );

COMMIT;
