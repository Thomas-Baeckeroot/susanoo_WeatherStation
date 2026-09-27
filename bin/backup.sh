#!/bin/bash
# Purpose = Backup of meteo DB and scripts
# Dump goes to [DATABASE] BackupFolder of the config, by default the home folder (= /volume1/homes/meteo on the NAS)
DATE=$(date +"%Y-%m-%d")

. "$(dirname "$0")/db_config.sh"

BACKUP_DIR=$(db_setting backupfolder)
BACKUP_DIR="${BACKUP_DIR:-${HOME}}"
BACKUP_DIR="${BACKUP_DIR/#\~/${HOME}}"
if [ ! -d "${BACKUP_DIR}" ] || [ ! -w "${BACKUP_DIR}" ]; then
    echo "Backup folder '${BACKUP_DIR}' does not exist or is not writable" >&2
    exit 1
fi
DUMP_FILE="${BACKUP_DIR}/mysqldump_${DBNAME}_${DATE}.sql"

# Option --show-progress-size not available yet on mysqldump v10.19
nice -n 19 mysqldump --defaults-extra-file="${DB_CREDENTIALS}" --databases "${DBNAME}" > "${DUMP_FILE}" || exit 1
nice -n 19 gzip -f "${DUMP_FILE}" || exit 1
echo "Backup written to ${DUMP_FILE}.gz"
