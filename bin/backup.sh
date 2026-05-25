#!/bin/bash
#Purpose = Backup of meteo DB and scripts
DBNAME="meteo"
DBUSER="meteo"
DBPASSWORD="SetRandomPassword123"
DATE=$(date +"%Y-%m-%d")
# Option --show-progress-size not available yet on mysqldump v10.19
# Option --password="${DBPASSWORD}" not available on mysqldump v10.19
nice -n 19 mysqldump --user="${DBUSER}" --password="${DBPASSWORD}" --databases "${DBNAME}" > "/volume1/homes/meteo/mysqldump_${DBNAME}_${DATE}.sql"
nice -n 19 gzip "/volume1/homes/meteo/mysqldump_${DBNAME}_${DATE}.sql"
