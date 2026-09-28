# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Self-hosted weather station for Raspberry Pi. Sensor reading runs every minute via cron; a Python web server serves SVG graphs and webcam captures. Data is stored in MariaDB. The codebase is designed to also run a "master" web server on a separate host (e.g. a Synology NAS) that aggregates data from one or more remote Pis.

## Install / run

This project is intended to be deployed on a Raspberry Pi (or compatible Linux); there is no linter configured; only the web server has tests (see "Tests" below).

- Full install (run on the Pi after cloning to `~/meteo`):
  - `sudo ./install.sh` — interactive; prompts for the web-server user (default `web`), the data-collector user (default current user), and the Python venv path (default `/usr/local/share/susanoo-py-venv`). Calls `install_python.sh` and `install_python_venv_and_libs.sh`, installs `mariadb-server`, `libmariadb-dev`, `gpac`, and creates `~/meteo/captures/`.
- Database schema / seed:
  - `mysql -u root weather_station < bin/db_initialization1_tables.sql`
  - `mysql -u root weather_station < bin/db_initialization2_data.sql`
- Database migrations (schema changes after the initial setup): `bin/db_migrate.sh` as the data-collector user, after each `git pull`, on the NAS and on each Pi; `--status` lists applied / pending ones. It applies `bin/db_migrations/NNN_description.sql` in order and records them in the `schema_migrations` table. Migrations must be idempotent (`IF NOT EXISTS`) and, on big tables, non-blocking (`ALGORITHM=INPLACE, LOCK=NONE`). DB credentials for shell scripts come from `bin/db_config.sh` (reads `[DATABASE]` of the config, like the Python code). Test with disposable `mariadb:10.11` (NAS) and `mariadb:10.3` (Raspberry Pis, e.g. grangette: 10.3.39) Docker containers: migrations must work on both.
- Public-html symlink layout (must be re-run after pulling if links change):
  - `./bin/create_server_pages.sh "${HOME}" "${WEB_USER}"` — creates `~${WEB_USER}/public_html/` with symlinks pointing at `src/main/py/public_html/*.py` (the `.py` files are CGI scripts; the symlinks drop the `.py` so the server serves them as `index.html`, `graph.svg`, `captures.json`, etc.).
- Run the sensor loop (cron, once per minute): `src/main/py/periodical_sensor_reading.py`.
- Run the web server: `bin/susanoo_WeatherStation_startWebServer.sh {start|stop|restart|status}` — installed as the Synology rc.d script `/usr/local/etc/rc.d/weatherStationWeb.sh`; runs the venv's `python3 src/main/py/server3.py` as the `web` user from `~web/public_html/`, restarts it if it dies. A `git pull` is enough for CGI scripts (re-run per request), but changes to `server3.py` need a `restart`.
- Config files (per user): `~/.config/susanoo_WeatherStation.conf` — separate copies exist for the data-collector user and the web-server user. Templates live at `bin/susanoo_WeatherStation_template.conf` and `bin/susanoo_WeatherStation_Web_template.conf`.

## Tests

- `src/test/py/test_server3.py`: stdlib `unittest` integration tests of `server3.py` (Python 3.8 compatible, no extra dependency). Each test starts the real server in a temporary HOME with fake CGI scripts: parallel requests, HTTP `Range`, complete large CGI output, CGI scripts using the server's venv python, disconnection logging, exit on missing modules, SIGTERM.
- Run with the venv's python, from the repository root: `/usr/local/share/susanoo-py-venv/bin/python3 -m unittest discover -s src/test/py -v` (~7 s). `SERVER3=<path>` tests another copy of `server3.py`.

## TODO

- Tests for the CGI scripts (`index.html.py`, `graph.svg.py`, `captures.json.py`, `capture.html.py`) against a disposable MariaDB test database seeded from `bin/db_initialization*.sql` (e.g. a Docker `mariadb` container).
- Tests for `bin/backup.sh` (reads `[DATABASE]` from the config; fake `mysqldump` in PATH) and `bin/susanoo_WeatherStation_startWebServer.sh` (start / auto-restart / stop with temporary paths).
- Tests for the data collector (`periodical_sensor_reading.py`, `consolidate_from_raw()`, `copy_values_from_server()`) with the test database; sensors mocked.
- GitHub Action running the tests on each push (Python 3.8 to match the Synology).
- `bin/db_check.sh` (read-only report, later an optional `--fix`) to find inconsistencies in the big tables: duplicate `(sensor, epochtimestamp)` rows in `raw_measures` (the remote sync prefers duplicates to losses), measures for unknown sensors, timestamps in the future or before the station existed, physically implausible values per sensor type, long gaps per sensor, remote rows still `synchronised = false` long after, `captures` pointing to missing files. Once cleaned, a migration adding a UNIQUE key on `(sensor, epochtimestamp)` (+ `INSERT IGNORE` in the sync) would prevent new duplicates.
- Study how to never insert duplicates (the original design intent): today the remote sync accepts a duplicate when marking rows `synchronised` on the remote fails after the local commit, and `failed_request.py` may replay an INSERT that actually succeeded. Options: a UNIQUE key on `(sensor, epochtimestamp)` with `INSERT IGNORE` / `ON DUPLICATE KEY UPDATE` everywhere measures are inserted (local reading, remote sync, failed-request replay) — needs `db_check.sh` cleanup first and a check of the index cost on the NAS; or a sync that skips rows already present locally (e.g. only copying epochs above the local max per sensor).

## Architecture

Two cooperating Python processes share a MariaDB database; the web layer is a CGI tree of executable `.py` files, exposed through symlinks.

### Data-collector process (`periodical_sensor_reading.py`)
- Triggered every minute by cron. Reads each enabled row of the `sensors` table, dispatches by `sensor_type` to a function in `sensors_functions.py` (e.g. `value_cpu_temp`, `value_ext_temperature`, `value_sealevelpressure`, `take_picture`), and inserts into `raw_measures` (and `captures` for camera rows).
- Consolidation tables (`consolidated_measures`, per-sensor `consolidated{period}_measures_*`) are produced by `consolidate_from_raw()` for downsampled history. The `period` column is in seconds (e.g. 900 = 15 min).
- Master/slave aggregation: `copy_values_from_server()` pulls rows from a remote Pi defined under a `[remote:<host>]` section in the config file into the local DB, so a single web UI can display several stations.
- Sensor configuration is split between two places: the `sensors` table (label, decimals, unit, type, consolidation period) and `~/.config/susanoo_WeatherStation.conf` (GPIO pin numbers, camera params, DB credentials, `SensorKnownAltitude`). Pin assignments for the maintainer's hardware are documented in `README.md`.

### Web server (`server3.py` + `src/main/py/public_html/`)
- `http.server.ThreadingHTTPServer` with a `CGIHTTPRequestHandler` subclass (HTTP `Range` support for static files, request/duration logging, 120 s client idle timeout, socket made blocking before running a CGI script); `kill -USR1 <pid>` dumps all thread stacks to `~/susanoo-web.faults.log`; `cgi_directories = ["/"]` so every `.py` under `public_html/` is treated as a CGI script. Default port `8080`, overridable via `[DEFAULT] WebServerPort` in the config file.
- The server expects to be started from the working directory containing `index.html`. `check_working_dir()` will `chdir` and recreate missing `*.py` → unsuffixed symlinks (`graph.svg.py` → `graph.svg`, etc.) if needed; the canonical setup is via `bin/create_server_pages.sh`.
- `public_html/db_module.py` is the DB access layer for the CGI scripts. **It deliberately copies `epoch_now`, `get_home`, `get_config` from `utils.py` rather than importing them** because the web user's `public_html/` is populated by symlinks to individual files, not the package — see the `# FIXME Not working because files here are linked (ln)` comment. Keep the two implementations in sync if you change `utils.py`.
- DB driver is `pymysql` (selected at `db_module.py` top via the `db_module = pymysql` alias; alternatives like `mariadb`, `psycopg2`, `mysql.connector` are commented in place).

### Auxiliary processes
- `video_capture_on_motion.py` — separate daemon listening on the GPIO motion sensor; records video via `MP4Box`.
- `watchdog_gpio.py` — blinks the watchdog LED and handles the shutdown button (GPIO pins from `[GPIO]` section of the config).
- `start_cpu_fan.py` — relay control for the CPU fan.
- `bin/weather_station_notifier.sh` — email alerts via `msmtp`; needs `~/.msmtprc` (template at `bin/.msmtprc-template`).
- `bin/remove-oldest-captures.sh` — disk-pressure cleanup of `captures/`.

### Important shape constraints
- Sensor names are `VARBINARY(8)` in MariaDB. Code that reads the `sensors` table (e.g. `copy_values_from_server`) must `.decode('ascii')` before string use.
- The `raw_measures.synchronised` flag exists for master/slave replication: the slave inserts rows with `synchronised = false`, the master reads and flips them after import.
- Logs are written to `~/susanoo-data.log` (collector) and `~/susanoo-web.log` (web server). Both processes call `logging.basicConfig(filename=...)` at import time, so changing the log destination requires editing each entrypoint.

### Submodule
- `src/lib/Adafruit_Python_BMP` is a git submodule (BMP085 sensor library). Initialize with `git submodule update --init --recursive` after cloning.
