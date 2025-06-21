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



-- INSERT INTO sensors VALUES('SensShortName' , p0_100, 'Sensor verbose texte'    , num_dec_0_2, false, 'Unit_cm', '900'); -- later, consolidated should be like '900 86400'
INSERT INTO sensors VALUES('CPU_temp', 10, 'Température CPU (centrale)' , 1, false, '°C' , '900', 'ignored');
INSERT INTO sensors VALUES('CPU_tmp1',  9, 'Température CPU (R0 grange)', 1, false, '°C' , '900', 'CPU_temp');
INSERT INTO sensors VALUES('WaterRes', 50, 'Réserve eau de pluie'       , 1, false, 'cm' , '900', 'water_height');
INSERT INTO sensors VALUES('lum_ext' , 70, 'Luminosité'                 , 0, false, 'lux', '900', 'ignored');
INSERT INTO sensors VALUES('temp_ext', 90, 'Température'                , 1, false, '°C' , '900', 'ignored');
INSERT INTO sensors VALUES('pressure', 80, 'Pression atmosphérique'     , 1, false, 'hPa', '900', 'ignored');

-- name     | priority | sensor_label                 | decimals | cumulative | unit | consolidated | sensor_type
INSERT INTO sensors VALUES('granget',  0, 'grangette (camera)'          , 0, false, 'N/A', '0', 'camera');
-- INSERT INTO sensors VALUES('tilleul',  0, 'tilleul'                  , 0, false, 'N/A', '900', 'remote:192.168.1.170:camera');
INSERT INTO sensors VALUES('tilleul',  0, 'tilleul'                     , 0, false, 'picture', '900', 'camera');


COMMIT;
