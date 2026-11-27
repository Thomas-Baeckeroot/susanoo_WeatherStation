#!/bin/bash
# Applies, in order, the bin/db_migrations/*.sql files not yet recorded in the schema_migrations table.
# Run as the data-collector user (DB settings from ~/.config/susanoo_WeatherStation.conf) after each 'git pull':
#   bin/db_migrate.sh            apply pending migrations
#   bin/db_migrate.sh --status   list applied / pending migrations (read-only)
# Migrations must be idempotent (IF NOT EXISTS...): a failure halfway can then simply be re-run.
usage() {
    echo "Usage: $0 [--status]"
    echo "  (no option)  apply the pending migrations"
    echo "  --status     list applied / pending migrations, without changing anything"
}
# Checked first: a mistyped option (e.g. '--stat') must not apply the migrations
case "$*" in
    "") status_only=false ;;
    --status) status_only=true ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

MIGRATIONS_DIR="$(cd "$(dirname "$0")" && pwd)/db_migrations"
MYSQL="${MYSQL:-mysql}"
# Longest wait (s) for a table lock held by another session (e.g. the transaction of a running backup).
# Even with ALGORITHM=INPLACE, LOCK=NONE, an ALTER TABLE needs an exclusive metadata lock at its start and
# end, and while it waits for it every new query on the table queues behind it (collector inserts, web
# pages): give up quickly instead (server default: 1 day), the migration can simply be re-run later.
# On a remote Pi, the master's sync queries (each a scan of up to ~90 s, one sensor after the other) hold the
# table nearly all the time: a long ALTER then builds its index and fails at the end. Pause that sync first by
# holding, on the master as its collector user, ~/.susanoo-sync-locks/<remote>_values.lock (flock) until done.
LOCK_WAIT_TIMEOUT="${LOCK_WAIT_TIMEOUT:-10}"
# Synology's MariaDB package client is not always in PATH
if ! command -v "${MYSQL}" > /dev/null && [ -x /usr/local/mariadb10/bin/mysql ]; then
    MYSQL=/usr/local/mariadb10/bin/mysql
fi

. "$(dirname "$0")/db_config.sh"

sql() {
    "${MYSQL}" --defaults-extra-file="${DB_CREDENTIALS}" --batch --skip-column-names "${DBNAME}" "$@"
}

if [ "${status_only}" = false ]; then
    sql -e "CREATE TABLE IF NOT EXISTS schema_migrations (
                version    VARCHAR(255) NOT NULL PRIMARY KEY,
                applied_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
            )" || exit 1
fi
# With --status, a missing table (never created) just means that no migration was applied yet
table=$(sql -e "SELECT table_name FROM information_schema.tables
                 WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'") || exit 1
applied=""
if [ -n "${table}" ]; then
    applied=$(sql -e "SELECT version FROM schema_migrations") || exit 1
fi

for file in "${MIGRATIONS_DIR}"/*.sql; do
    version=$(basename "${file}")
    if printf '%s\n' "${applied}" | grep -qxF "${version}"; then
        [ "${status_only}" = true ] && echo "applied  ${version}"
        continue
    fi
    if [ "${status_only}" = true ]; then
        echo "pending  ${version}"
        continue
    fi
    echo "$(date '+%F %T') applying ${version}..."
    started=$(date +%s)
    if ! { echo "SET SESSION lock_wait_timeout = ${LOCK_WAIT_TIMEOUT};"; cat "${file}"; } | sql; then
        echo "FAILED: ${version} (fix it and re-run; later migrations were not applied)." >&2
        echo "'Lock wait timeout exceeded' means another session was using the table (backup? on a remote Pi," \
             "the master's sync: pause it, see LOCK_WAIT_TIMEOUT in this script): re-run later." >&2
        exit 1
    fi
    sql -e "INSERT INTO schema_migrations (version) VALUES ('${version}')" || exit 1
    echo "$(date '+%F %T') applied ${version} in $(( $(date +%s) - started )) s"
done
