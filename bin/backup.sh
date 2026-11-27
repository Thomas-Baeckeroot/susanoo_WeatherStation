#!/bin/bash
# Purpose = Backup of meteo DB and scripts
# Run it as the data-collector user (meteo on the NAS; in a Synology scheduled task, set User = meteo, not the
# default root): it reads that user's config (~/.config/susanoo_WeatherStation.conf, or SUSANOO_CONFIG).
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
MYSQLDUMP="${MYSQLDUMP:-mysqldump}"
# Synology's MariaDB package client is not always in PATH (as in db_migrate.sh)
if ! command -v "${MYSQLDUMP}" > /dev/null && [ -x /usr/local/mariadb10/bin/mysqldump ]; then
    MYSQLDUMP=/usr/local/mariadb10/bin/mysqldump
fi

# Option --show-progress-size not available yet on mysqldump v10.19
# --single-transaction: consistent snapshot of the (InnoDB) tables without locking them. By default, mysqldump
# holds LOCK TABLES ... READ during the whole dump (minutes on the NAS), blocking the collector's inserts and
# the remote sync meanwhile. Rows are streamed (--quick, part of the default --opt).
# A dump that failed halfway is removed: it would look like a backup, without the tables after the failure
nice -n 19 "${MYSQLDUMP}" --defaults-extra-file="${DB_CREDENTIALS}" --single-transaction --databases "${DBNAME}" \
    > "${DUMP_FILE}" || { rm -f "${DUMP_FILE}"; exit 1; }
nice -n 19 gzip -f "${DUMP_FILE}" || exit 1
echo "Backup written to ${DUMP_FILE}.gz"
