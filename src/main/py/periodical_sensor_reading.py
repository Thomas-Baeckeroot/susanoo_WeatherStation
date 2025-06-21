#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import failed_request
import hc_sr04_lib_test
import public_html.db_module as db_module
import logging
import os
import pathlib
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


def copy_values_from_server(sensor_dest, remote_server_src, conn_local_dest):
    (sensor_name, sensor_label_dest, decimals_dest, cumulative_dest, unit_dest,
     consolidated_dest, sensor_type_dest, filepath_last, filepath_data) = sensor_dest
    sensor_name = sensor_name.decode('ascii')
    try:
        conn_remote_src = db_module.get_conn(host=remote_server_src)  # Connect to REMOTE PostgreSQL DB
        log.debug("\tSuccessfully connected to remote DB at '{0}'".format(remote_server_src))
    except Exception as err:
        log.exception("\tException '{0}' when getting DB connection to '{1}'".format(err, remote_server_src))
        return
    curs_src = conn_remote_src.cursor()
    read_sensors_query = "SELECT sensor_label, decimals, cumulative, unit, consolidated" \
                         "  FROM sensors" \
                         " WHERE name='" + sensor_name + "';"
    curs_src.execute(read_sensors_query)
    (sensor_label_src, decimals_src, cumulative_src, unit_src, consolidated_src) = curs_src.fetchall()[0]

    # TODO Should be moved to dedicated function "Update_sensors_param_from_src_to_dest
    # only happens on configuration changes
    # FIXME Below UPDATEs have no effect...
    log.debug("\tSensor parameters: Checking consistency...")
    if sensor_label_src != sensor_label_dest:
        log.warning("\tUPDATING sensor_label: \tsrc='" + sensor_label_src + "'\t>>> dest='" + sensor_label_dest + "'")
        log.info("UPDATE sensors   SET sensor_label='" + sensor_label_src + "' WHERE name='" + sensor_name + "';")
        log.critical("NOT IMPLEMENTED!")  # FIXME NOT IMPLEMENTED!
        # curs_src.execute("UPDATE sensors"
        #                  "   SET sensor_label='" + sensor_label_src +
        #                  "' WHERE name='" + sensor_name + "';")
    if decimals_src != decimals_dest:
        log.warning("\tUPDATING Decimals:     \tsrc='" + str(decimals_src) + "'\t>>> dest='" + str(decimals_dest) + "'")
        curs_src.execute("UPDATE sensors"
                         "   SET decimals=" + str(decimals_src) +
                         " WHERE name='" + sensor_name + "';")
    if cumulative_src != cumulative_dest:
        log.warning(
            "\tUPDATING cumulative: \tsrc='" + str(cumulative_src) + "'\t>>> dest='" + str(cumulative_dest) + "'")
        curs_src.execute("UPDATE sensors"
                         "   SET cumulative=" + str(cumulative_src) +
                         " WHERE name='" + sensor_name + "';")
    if unit_src != unit_dest:
        log.warning("\tUPDATING unit: \tsrc='" + unit_src + "'\t>>> dest='" + unit_dest + "'")
        curs_src.execute("UPDATE sensors"
                         "   SET unit='" + unit_src +
                         "' WHERE name='" + sensor_name + "';")
    if consolidated_src != consolidated_dest:
        log.warning(
            "\tUPDATING consolidated: \tsrc='" + str(consolidated_src) + "'\t>>> dest='" + str(consolidated_dest) + "'")
        curs_src.execute("UPDATE sensors"
                         "   SET consolidated='" + str(consolidated_src) +
                         "' WHERE name='" + str(sensor_name) + "';")
    log.debug("\tSensor parameters: Checked.")

    read_sensors_query = "SELECT epochtimestamp, measure" \
                         "  FROM raw_measures" \
                         " WHERE sensor='" + sensor_name + \
                         "'  AND synchronised='false' " \
                         "ORDER BY epochtimestamp asc LIMIT 3000;"  # PostgreSQL: "FETCH FIRST 10 ROWS ONLY;"
    curs_src.execute(read_sensors_query)  # Requires ~5 seconds to execute (on remote Raspberry Pi)
    # log.debug("\tDB src (remote): read_sensors_query executed.")
    epochs_and_measures_from_src = curs_src.fetchall()
    # log.debug("\tDB src (remote): .fetchall() executed.")
    n_updates = len(epochs_and_measures_from_src)
    if n_updates > 0:
        insert_measures_to_dest_query = "INSERT INTO raw_measures(epochtimestamp, measure, sensor) VALUES "
        not_first_value = False
        for (epoch_src, measure_src) in epochs_and_measures_from_src:
            # = epoch_and_measure  # todo once working, should be included within for declaration
            if not_first_value:
                insert_measures_to_dest_query = insert_measures_to_dest_query + ","
            insert_measures_to_dest_query = insert_measures_to_dest_query \
                                            + "(" + str(epoch_src) + ", " + str(measure_src) + ", '" \
                                            + sensor_name + "')"
            not_first_value = True
        insert_measures_to_dest_query = insert_measures_to_dest_query + ";"
        # log.debug("\tDB dest (locale): getting cursor...")
        curs_dest = conn_local_dest.cursor()
        # log.debug("\tDB dest (locale): query = " + str(len(insert_measures_to_dest_query)) + " bytes/chars")
        # log.debug(insert_measures_to_dest_query)
        curs_dest.execute(insert_measures_to_dest_query)
        # log.debug("\tDB dest (locale): query executed.")

        update_synchronised_query = "UPDATE raw_measures" \
                                    "   SET synchronised=true" \
                                    " WHERE epochtimestamp IN ("
        # PostgreSQL was "UPDATE raw_measures(synchronised) SET true"
        not_first_value = False
        for (epoch_src, measure_src) in epochs_and_measures_from_src:
            if not_first_value:
                update_synchronised_query = update_synchronised_query + ", "
            update_synchronised_query = update_synchronised_query + str(epoch_src)
            not_first_value = True
        update_synchronised_query = update_synchronised_query + ") AND sensor='" + sensor_name + "'"
        # log.debug("\tDB src (remote): query = " + str(len(update_synchronised_query)) + " bytes/chars.")
        curs_src.execute(update_synchronised_query)
        # log.debug("\tDB src (remote): query executed.")

        conn_remote_src.commit()
        # log.debug("\tDB src (remote): commited.")

    conn_local_dest.commit()  # Can be an update of label name or unit, etc... without value
    log.debug("\tDB dest (locale): commited.")

    log.info("\t=> Imported '{0}' records from '{1}'.".format(n_updates, remote_server_src))

    return


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
    curs_src = conn_remote_src.cursor()
    read_filepath_query = "SELECT filepath_last, filepath_data" \
                          "  FROM captures" \
                          " WHERE sensor_name='" + sensor_name + "';"
    # log.debug("\tread_filepath_query = '" + read_filepath_query + "'")  # for debugging purpose
    curs_src.execute(read_filepath_query)
    (filepath_last_src, filepath_data_src) = curs_src.fetchall()[0]
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
               "-P", str(ssh_port),
               rsync_user + "@" + remote_server_src + ":/home/pi/meteo/captures/" + filepath_last_src,
               destination_file]
    cp_return_code = subprocess.call(command)
    log.info("\tscp terminated with return code " + str(cp_return_code))
    if cp_return_code == 0:
        log.info("\tUpdating local db with values from remote...")
        curs_dest = conn_local_dest.cursor()
        update_last_pictures_values = "UPDATE captures" + \
                                      "   SET filepath_last = '" + filepath_last_src + "'," + \
                                      "       filepath_data = '" + filepath_data_src + "'" + \
                                      " WHERE sensor_name='" + sensor_name + "';"
        curs_dest.execute(update_last_pictures_values)
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
         "--rsh", "ssh -p " + str(ssh_port),
         # "--time-limit", "1",  # not working on some distros (exemple: Synology NAS)
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
                sleep(5)  # give time for very last value of remote sensors to be updated
                first_remote = False
            remote_server = sensor_type[7:]
            log.info("Remote sensor '{0}' -> reading values from '{1}'...".format(sensor_name, remote_server))
            if unit == "picture":
                rsync_pictures_from_server(sensor, remote_server, conn)
            else:
                copy_values_from_server(sensor, remote_server, conn)

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
