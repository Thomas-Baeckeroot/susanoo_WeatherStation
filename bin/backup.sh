#!/bin/bash
# Purpose = Backup of meteo DB and scripts
BACKUP_DIR="/volume1/homes/meteo"
DATE=$(date +"%Y-%m-%d")

. "$(dirname "$0")/db_config.sh"

# Option --show-progress-size not available yet on mysqldump v10.19
nice -n 19 mysqldump --defaults-extra-file="${DB_CREDENTIALS}" --databases "${DBNAME}" > "${BACKUP_DIR}/mysqldump_${DBNAME}_${DATE}.sql"
nice -n 19 gzip "${BACKUP_DIR}/mysqldump_${DBNAME}_${DATE}.sql"
