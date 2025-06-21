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
