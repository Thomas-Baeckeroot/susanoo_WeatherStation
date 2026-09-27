#!/bin/bash
# Applies, in order, the bin/db_migrations/*.sql files not yet recorded in the schema_migrations table.
# Run as the data-collector user (DB settings from ~/.config/susanoo_WeatherStation.conf) after each 'git pull':
#   bin/db_migrate.sh            apply pending migrations
#   bin/db_migrate.sh --status   list applied / pending migrations
# Migrations must be idempotent (IF NOT EXISTS...): a failure halfway can then simply be re-run.
MIGRATIONS_DIR="$(cd "$(dirname "$0")" && pwd)/db_migrations"
MYSQL="${MYSQL:-mysql}"
# Synology's MariaDB package client is not always in PATH
if ! command -v "${MYSQL}" > /dev/null && [ -x /usr/local/mariadb10/bin/mysql ]; then
    MYSQL=/usr/local/mariadb10/bin/mysql
fi

. "$(dirname "$0")/db_config.sh"

sql() {
    "${MYSQL}" --defaults-extra-file="${DB_CREDENTIALS}" --batch --skip-column-names "${DBNAME}" "$@"
}

sql -e "CREATE TABLE IF NOT EXISTS schema_migrations (
            version    VARCHAR(255) NOT NULL PRIMARY KEY,
            applied_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
        )" || exit 1
applied=$(sql -e "SELECT version FROM schema_migrations") || exit 1

for file in "${MIGRATIONS_DIR}"/*.sql; do
    version=$(basename "${file}")
    if printf '%s\n' "${applied}" | grep -qxF "${version}"; then
        [ "$1" = "--status" ] && echo "applied  ${version}"
        continue
    fi
    if [ "$1" = "--status" ]; then
        echo "pending  ${version}"
        continue
    fi
    echo "$(date '+%F %T') applying ${version}..."
    started=$(date +%s)
    if ! sql < "${file}"; then
        echo "FAILED: ${version} (fix it and re-run; later migrations were not applied)" >&2
        exit 1
    fi
    sql -e "INSERT INTO schema_migrations (version) VALUES ('${version}')" || exit 1
    echo "$(date '+%F %T') applied ${version} in $(( $(date +%s) - started )) s"
done
