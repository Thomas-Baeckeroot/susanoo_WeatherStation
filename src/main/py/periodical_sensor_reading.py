#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import contextlib
import failed_request
import fcntl
import hc_sr04_lib_test
import public_html.db_module as db_module
import logging
import os
import pathlib
import pymysql
import sensors_functions as func
import subprocess
import utils

from time import sleep

logging.basicConfig(
    filename=utils.get_home() + "/susanoo-data.log",  # = /home/pi/susanoo-data.log
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8.8s%(name)-14s (%(process)5d) %(message)s')
log = logging.getLogger("periodical_sensor_read…")
CONSOLIDATE_VAL = False


def is_multiple(value, multiple):
    margin = 30  # 30 s is used as default (script should be launched once per minute)
    if (int(value / margin) % (multiple / margin)) == 0:
        return True
    else:
        return False


def consolidate_from_raw(curs, sensor, period):
    #    consolidate_from_raw(curs, "CPU_temp", 900)
    raw_table = "raw_measures_" + sensor
    consolidated_table = "consolidated" + str(period) + "_measures_" + sensor
    log.info("consolidate_from_raw:\n\traw_table = " + raw_table + "\n\tconsolidated_table = " + consolidated_table)

    sql_req = "SELECT MAX(epochtimestamp) FROM " + raw_table + ";"
    curs.execute(sql_req)
    max_epoch_from_raw = curs.fetchall()[0][0]

    sql_req = "SELECT MAX(maxepochtime) FROM " + consolidated_table + ";"
    curs.execute(sql_req)
    max_epoch_from_consolidated = curs.fetchall()[0][0]

    sql_req = "SELECT MIN(epochtimestamp) FROM " + raw_table + ";"
    curs.execute(sql_req)
    min_epoch_from_raw = curs.fetchall()[0][0]

    sql_req = "SELECT MIN(maxepochtime) FROM " + consolidated_table + ";"
    curs.execute(sql_req)
    min_epoch_from_consolidated = curs.fetchall()[0][0]

    # TODO Consolidation from raw values table must be done soon...


SYNC_LOCKS_FOLDER = utils.get_home() + "/.susanoo-sync-locks"
SYNC_BATCH_SIZE = 3000  # rows copied per remote sensor and per run: catches up a long outage in small steps
SENSOR_PARAMETERS = ("sensor_label", "decimals", "cumulative", "unit", "consolidated")
# scp / rsync run from cron: never prompt, and give up on a dead link (WiFi loss) within ~1 min instead of
# hanging until the TCP keepalive (2 h by default)
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
               "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3"]
# Copy of a single picture (a few MB): also covers a remote that stays connected but stops sending
SCP_TIMEOUT_SECONDS = 300


@contextlib.contextmanager
def remote_sync_lock(remote_server, sensor_name, unit):
    """Yields True when this run may synchronise this remote sensor, False while an earlier run is busy with it.

    Held only while the sensor is synchronised. One lock per camera: a long rsync (pictures catching up after
    weeks of outage) only makes the next runs skip that camera. One lock shared by all the value sensors of a
    remote: their queries never run at the same time on it (on a slow Pi, two concurrent ~90 s scans each went
    over the 2 min read timeout, so neither sensor was synchronised any more)."""
    lock_name = remote_server + ("_pictures_" + sensor_name if unit == "picture" else "_values")
    os.makedirs(SYNC_LOCKS_FOLDER, exist_ok=True)
    with open(os.path.join(SYNC_LOCKS_FOLDER, lock_name + ".lock"), "w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            acquired = False
        yield acquired  # released when the file is closed, or by the OS if the process dies


def copy_values_from_server(sensor_dest, remote_server_src, conn_local_dest):
    (sensor_name, sensor_label_dest, decimals_dest, cumulative_dest, unit_dest,
     consolidated_dest, sensor_type_dest, filepath_last, filepath_data) = sensor_dest
    sensor_name = sensor_name.decode('ascii')
    try:
        conn_remote_src = db_module.get_conn(host=remote_server_src)
        log.debug("\tSuccessfully connected to remote DB at '{0}'".format(remote_server_src))
    except Exception as err:
        log.exception("\tException '{0}' when getting DB connection to '{1}'".format(err, remote_server_src))
        return
    try:
        curs_src = conn_remote_src.cursor()
        # Never wait for a lock held on the remote (backup, migration...): next run will retry.
        # max_statement_time (MariaDB >= 10.1): the remote aborts a query itself before the 120 s read_timeout
        # of get_conn(). Otherwise, as MariaDB only notices a gone client when it sends rows, a long scan (e.g.
        # a Pi without the sync index of migration 002) would go on after the timeout, while the lock of
        # remote_sync_lock() is released and the next run starts the same scan alongside it.
        curs_src.execute("SET SESSION lock_wait_timeout = 10, innodb_lock_wait_timeout = 10,"
                         " max_statement_time = 100")

        # Sensor parameters: the local (dest) values win, as they are the ones displayed here and are curated on
        # the master (e.g. 'Température CPU (centrale)' on the NAS for a Pi's 'temp. CPU', telling the CPUs of
        # the two Pis apart). A remote value only fills a local one that is missing; never a NULL, nor the text
        # 'None' that a Pi has in 'consolidated'.
        curs_src.execute("SELECT " + ", ".join(SENSOR_PARAMETERS) + " FROM sensors WHERE name = %s",
                         (sensor_name,))
        params_src = curs_src.fetchone() or ()  # no row on the remote: its values are still copied below
        params_dest = (sensor_label_dest, decimals_dest, cumulative_dest, unit_dest, consolidated_dest)
        curs_dest = conn_local_dest.cursor()
        for column, value_src, value_dest in zip(SENSOR_PARAMETERS, params_src, params_dest):
            if value_dest in (None, "") and value_src not in (None, "", "None"):
                log.warning("\tSetting missing {0} of '{1}' from '{2}': '{3}'"
                            .format(column, sensor_name, remote_server_src, value_src))
                curs_dest.execute("UPDATE sensors SET " + column + " = %s WHERE name = %s", (value_src, sensor_name))
            elif value_src != value_dest:
                log.debug("\t{0} differs on '{1}': '{2}', kept '{3}'"
                          .format(column, remote_server_src, value_src, value_dest))

        curs_src.execute("SELECT  epochtimestamp, measure"
                         "  FROM  raw_measures"
                         " WHERE  sensor = %s AND synchronised = FALSE"
                         " ORDER BY epochtimestamp LIMIT %s",
                         (sensor_name, SYNC_BATCH_SIZE))
        rows = curs_src.fetchall()
        if rows:
            curs_dest.executemany("INSERT INTO raw_measures (epochtimestamp, measure, sensor) VALUES (%s, %s, %s)",
                                  [(epoch, measure, sensor_name) for (epoch, measure) in rows])
        # Local commit first: if marking them on the remote then fails, the rows are copied again
        # next run (duplicates) rather than lost
        conn_local_dest.commit()
        if rows:
            epochs = [epoch for (epoch, measure) in rows]
            curs_src.execute("UPDATE raw_measures SET synchronised = TRUE"
                             " WHERE sensor = %s AND epochtimestamp IN (" + ", ".join(["%s"] * len(epochs)) + ")",
                             [sensor_name] + epochs)
        conn_remote_src.commit()
        log.info("\t=> Imported '{0}' records from '{1}'.".format(len(rows), remote_server_src))
    except Exception as err:
        log.exception("\tError '{0}' while copying '{1}' from '{2}'".format(err, sensor_name, remote_server_src))
        for conn in (conn_remote_src, conn_local_dest):
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        conn_remote_src.close()  # releases any remote lock even after an error


def create_folders_if_required(destination_file):
    pathlib.Path(os.path.dirname(destination_file)).mkdir(mode=0o755, parents=True, exist_ok=True)
    return


def rsync_pictures_from_server(local_sensor, remote_server_src, conn_local_dest):
    (sensor_name, sensor_label_dest, decimals_dest, cumulative_dest, unit_dest,
     consolidated_dest, sensor_type_dest, filepath_last_local, filepath_data_local) = local_sensor
    sensor_name = sensor_name.decode('ascii')
    log.info("\tpicture sensor '" + sensor_name + "'")
    try:
        conn_remote_src = db_module.get_conn(host=remote_server_src)  # Connect to REMOTE PostgreSQL DB
    except Exception as err:
        log.error("\tException '{0}' when connecting to DB.".format(err))
        return
    try:
        curs_src = conn_remote_src.cursor()
        curs_src.execute("SELECT filepath_last, filepath_data FROM captures WHERE sensor_name = %s", (sensor_name,))
        row = curs_src.fetchone()
    finally:
        conn_remote_src.close()  # not kept open during the copies below, which may take long
    if row is None:
        log.warning("\tNo picture recorded for '{0}' on '{1}': nothing to copy".format(sensor_name, remote_server_src))
        return
    (filepath_last_src, filepath_data_src) = row
    log.debug("\t(..._last_src  , ..._data_src  ) = (\t'" + filepath_last_src + "',\t'" + filepath_data_src + "')")
    log.debug("\t(..._last_local, ..._data_local) = (\t'" + filepath_last_local + "',\t'" + filepath_data_local + "')")

    if filepath_last_src == filepath_last_local:
        log.info(f"\t=> No new picture detected for '{sensor_name}'. rsync not required.")
        return
    # else:  # filepath_last_src != filepath_last_local:
    log.info(f"\tNew picture has been detected. Starting copying from '{remote_server_src}' to local...")
    config = utils.get_config()
    rsync_user = config.get('remote:' + remote_server_src, 'rsync_user', fallback="web")
    ssh_port = config.getint('remote:' + remote_server_src, 'ssh_port', fallback=22)
    # rsync connection relies on ssh connection. No password authentication is implemented here.
    # Authentication is done by keys:
    # Public key ~/.ssh/id_rsa.pub from local user should be added into ~/.ssh/authorized_keys of remote source.

    # remote_server_src_regex = "\"[r]sync(.*)" + remote_server_src.replace(".", "\.") + "\""
    # rsync_already_running = subprocess.call(["ps", "-ef", "|", "grep", "-E", remote_server_src_regex], shell=True)  # fixme Always return 0. To be fixed...
    # log.debug("\t" + str(rsync_already_running) + " <-- 'ps -ef | grep -E " + remote_server_src_regex + "'")
    # if rsync_already_running == 0:
    #     log.info("\tAnother rsync process is detected still running for regex " + remote_server_src_regex
    #           + " ('ps|grep' returned code " + str(rsync_already_running) + ").")
    #     return

    log.info("\tStarting file copy process (scp)...")
    destination_file = utils.get_home() + "/meteo/captures/" + filepath_last_src
    create_folders_if_required(destination_file)
    command = ["scp",
               "-P", str(ssh_port)] + SSH_OPTIONS + [
               rsync_user + "@" + remote_server_src + ":/home/pi/meteo/captures/" + filepath_last_src,
               destination_file]
    try:
        cp_return_code = subprocess.call(command, timeout=SCP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:  # scp has been killed: next run will retry
        log.error("\tscp did not complete within {0} s, command was: {1}".format(SCP_TIMEOUT_SECONDS, command))
        return
    log.info("\tscp terminated with return code " + str(cp_return_code))
    if cp_return_code == 0:
        log.info("\tUpdating local db with values from remote...")
        curs_dest = conn_local_dest.cursor()
        # Parameters: the paths come from the remote's DB
        curs_dest.execute("UPDATE captures SET filepath_last = %s, filepath_data = %s WHERE sensor_name = %s",
                          (filepath_last_src, filepath_data_src, sensor_name))
        conn_local_dest.commit()
        log.info("\tLocal db updated with ('" + filepath_last_src + "', '" + filepath_data_src + "').")
    else:
        log.info("\tAn error occured, command was: " + str(command))
        # For more details, add verbosity to command with option '-v'
        # Return codes can be seen there: https://support.microfocus.com/kb/doc.php?id=7021696

    log.info("\tStarting rsync process...")  # if remote remained offline, previous pictures may miss...
    rsync_return_code = subprocess.call(
        ["rsync",
         "--recursive",  # -[r]avz
         "--archive",  # -r[a]vz
         "--verbose",  # -ra[v]z
         "--compress",  # -rav[z]
         "--size-only",
         "--perms",  # preserve permissions
         "--rsh", " ".join(["ssh", "-p", str(ssh_port)] + SSH_OPTIONS),
         # "--time-limit", "1",  # not working on some distros (exemple: Synology NAS)
         # No overall time limit: catching up after a long outage may legitimately take hours
         # (the values of the remotes are still synchronised meanwhile, see remote_sync_lock())
         "--timeout", "60",  # if network is not good, we prefer exit quickly and let next execution finishing.
         rsync_user + "@" + remote_server_src + ":/home/pi/meteo/captures/" + sensor_name + "/",
         utils.get_home() + "/meteo/captures/" + sensor_name + "/"])
    if rsync_return_code != 0:
        log.error("\trsync returned code '" + str(rsync_return_code) + "' different from success '0'...")
    else:
        log.info("\tLocal and remote folder are successfully synchronised.")
        # TODO set new values 'folder_synchronised' in table 'captures'
    return


def main():  # Expected to be called once per minute
    main_call_epoch = utils.epoch_now()
    log.info("Starting ‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾")
    temp = 15  # default value for later calculation of speed of sound
    first_remote = True
    local_camera_name = None

    conn = None
    db_available = False
    try:
        conn = db_module.get_conn()
        db_available = True
        log.info("✓ Database connection successful")
    except Exception as e:
        log.warning(f"✗ Database connection failed: {str(e)}")
        log.info("→ Continuing in fallback mode")
        db_available = False
        # TODO Add a notification sending on critical errors!

    # name   | priority |        sensor_label         | decimals | cumulative | unit | consolidated | sensor_type
    read_sensors_query = \
        "SELECT  name, sensor_label, decimals, cumulative, unit," \
        "        consolidated, sensor_type, filepath_last, filepath_data " \
        "FROM    sensors " \
        "    LEFT JOIN captures ON sensors.name = captures.sensor_name; "

    sensors = []
    curs = None
    if db_available and conn:
        try:
            curs = conn.cursor()
            curs.execute(read_sensors_query)
            log.info("DB query successfully executed.")
            sensors = curs.fetchall()
        except (pymysql.err.OperationalError, pymysql.err.DatabaseError) as e:
            log.error(f"✗ Database Query FAILED: {str(e)}")
        except Exception as e:
            log.error(f"✗ Unexpected error during DB query: {str(e)}")

    else:
        log.warning("Unable to connect to DB to get list of sensors! (no DB)")

    values = []
    for sensor in sensors:
        (sensor_name, sensor_label, decimals, cumulative, unit,
         consolidated, sensor_type, filepath_last, filepath_data) = sensor
        sensor_name = sensor_name.decode('ascii')

        measure = None
        # Below ifs to be replaced by function blocks and dictionary as described
        # at https://stackoverflow.com/questions/11479816/what-is-the-python-equivalent-for-a-case-switch-statement
        if sensor_type == "ignored":
            log.info("Sensor '" + sensor_name + "' -> -ignoring-")
            # measure = None  # kept as None

        elif sensor_type == "CPU_temp":
            measure = func.value_cpu_temp()
            # start_cpu_fan = __import__("start_cpu_fan")
            # if measure > 40:
            #     start_cpu_fan.start_cpu_fan()
            # if measure < 20:
            #     start_cpu_fan.stop_cpu_fan()

        elif sensor_type == "temperature":
            temp = func.value_ext_temperature()
            measure = temp

        elif sensor_type == "pressure":
            measure = func.value_sealevelpressure()

        elif sensor_type == "luminosity":
            measure = func.value_luminosity()

        elif sensor_type == "distance":
            # Calculate speed (celerity) of sound:
            measure = hc_sr04_lib_test.measure_distance(temp)

        elif sensor_type == "camera":
            local_camera_name = sensor_name

        elif sensor_type.startswith("remote:"):
            # Value of current sensor is hosted by another remote DB.
            # Values that are not "synchronised" here will be copied now.
            if first_remote:
                first_remote = False
                sleep(5)  # give time for very last value of remote sensors to be updated
            remote_server = sensor_type[7:]
            with remote_sync_lock(remote_server, sensor_name, unit) as acquired:
                if not acquired:
                    log.warning("Remote sensor '{0}': another run is synchronising {1} from '{2}', skipped this time"
                                .format(sensor_name, "it" if unit == "picture" else "values", remote_server))
                    continue
                log.info("Remote sensor '{0}' -> reading values from '{1}'...".format(sensor_name, remote_server))
                try:
                    if unit == "picture":
                        rsync_pictures_from_server(sensor, remote_server, conn)
                    else:
                        copy_values_from_server(sensor, remote_server, conn)
                except Exception as err:
                    # An unreachable or failing remote must not abort the run: the other sensors, the local
                    # values and the replay of failed requests below must still be done
                    log.exception("Remote sensor '{0}': error '{1}' while synchronising from '{2}'"
                                  .format(sensor_name, err, remote_server))
                    try:
                        conn.rollback()
                    except Exception:
                        pass

        else:
            log.info("Sensor '" + sensor_name + "' -> ERROR! Unable to interpret '" + str(sensor_type)
                     + "' as a sensor type! Skipped...")
            # measure = None  # kept as None

        if measure is not None:
            log.info(f"\t=> Sensor '{sensor_name}' -> {measure}")
            values.append("(" \
                          + str(utils.epoch_now()) + "," \
                          + str(func.round_value_decimals(measure, decimals)) + ", '" \
                          + sensor_name + "')")
        elif not sensor_type.startswith("remote:"):
            log.info(f"\t=> Sensor '{sensor_name}' -> No value")

    # end of for-loop on each sensor

    # The remote syncs may have lasted hours (rsync of pictures catching up after an outage): past the server's
    # wait_timeout (8 h by default), the local connection is closed and the inserts, the picture update and the
    # replay below would fail: open a new one (pymysql's ping(reconnect=True) is deprecated).
    if conn is not None:
        try:
            conn.ping(reconnect=False)
        except Exception as err:
            log.warning("Local database connection lost during the remote syncs ({0}): reconnecting".format(err))
            try:
                conn = db_module.get_conn()
                curs = conn.cursor()
            except Exception as err:
                log.warning("Local database connection not restored: {0}".format(err))

    # Add values to database
    if values:
        sql_insert = "INSERT INTO raw_measures(epochtimestamp, measure, sensor) VALUES " \
                     + ",".join(values) + ";"
        log.info(str(sql_insert))
        try:
            curs.execute(sql_insert)
        except Exception as err:
            log.exception("Error '{0}' occurred when trying to execute the upper request!".format(err))
            failed_request.append(sql_insert)
        finally:
            conn.commit()
    else:
        log.debug("values = {0}".format(values))
        log.warning("No values to insert into DB!")

    if local_camera_name is not None:
        is_camera_mult = is_multiple(main_call_epoch, 900)  # is True every 900 s / 15 min
        if is_camera_mult:
            log.info("Once every 15 minutes: Capture picture")
            picture_name = func.take_picture(local_camera_name)
            sql_update = \
                "UPDATE captures         " + \
                "SET    filepath_last = '" + picture_name + "' "
            data_limit = 512000  # 500 kiB. Below this value, image is considered without data (mostly black)
            destination_file = utils.get_home() + "/meteo/captures/" + picture_name
            if pathlib.Path(destination_file).stat().st_size > data_limit:
                sql_update = sql_update + " , filepath_data = '" + picture_name + "' "
            sql_update = sql_update + \
                         "WHERE  sensor_name = '" + local_camera_name + "';"
            # try:
            # log.info(sql_update)  # for debugging...
            result = curs.execute(sql_update)
            # except Exception as err:
            if result == 0:
                sql_insert = \
                    "INSERT INTO captures (sensor_name, filepath_last, filepath_data) " + \
                    "VALUES ('" + local_camera_name + "', '" + picture_name + "', '" + picture_name + "')"
                # log.info(sql_insert)  # for debugging...
                curs.execute(sql_insert)

            log.info("\tUpdated value for camera " + local_camera_name + "; committing...")
            conn.commit()

    failed_request.fix_previously_failed_requests(conn)

    if CONSOLIDATE_VAL:
        for sensor in sensors:
            (sensor_name, decimals, consolidated, sensor_type) = sensor
            period = int(consolidated)
            sql_req = "SELECT MAX(epochtimestamp) FROM raw_measures WHERE sensor = '" + sensor_name + "';"
            curs.execute(sql_req)
            max_epoch_from_raw = curs.fetchall()[0][0]

            sql_req = "SELECT MAX(maxepochtime) FROM consolidated_measures WHERE sensor = '" + sensor_name + "';"
            curs.execute(sql_req)
            max_epoch_from_consolidated = curs.fetchall()[0][0]

            if (max_epoch_from_consolidated is None) or (max_epoch_from_consolidated + period) < max_epoch_from_raw:
                consolidate_from_raw(curs, sensor, period)

    if curs:
        log.debug("Closing DB cursor...")
        curs.close()
    else:
        log.error("No DB cursor to close!")

    if conn:
        log.debug("closing db...")
        conn.close()
    else:
        log.error("No DB connection to close!")

    is_daily_run = is_multiple(main_call_epoch, 86400)  # 60x60x24 s = 1 day
    if is_daily_run:
        log.info("Midnight run: trigger the pictures sorting...")
        # launch_daily_jobs(main_call_epoch)
    else:
        log.debug("(not midnight run)")

    log.info("Terminates ______________________________________________\n")


if __name__ == "__main__":
    main()
