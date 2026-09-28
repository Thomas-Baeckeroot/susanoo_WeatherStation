#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import configparser
import os

# import psycopg2 as db_module  # PostgreSQL library
# import mariadb as db_module  # MariaDB library
# import mysql.connector as db_module  # MySQL library
import pymysql as db_module  # PyMySQL - If failing here, try: `sudo python3 -m pip install PyMySQL` or check/rerun /home/meteo/meteo/install.sh
import time


# from .. import utils  # FIXME Not working because files here are linked (ln) in home of 'web' user!


def epoch_now():
    # Function copied from utils.py
    # return calendar.timegm(time.gmtime())
    return int(time.time())


def get_home():
    # Function copied from utils.py
    # if failing here, test "from pathlib import Path / home = str(Path.home())"
    return os.path.expanduser("~")


def get_config():
    # Function copied from utils.py
    config = configparser.ConfigParser()
    config.read(get_home() + '/.config/susanoo_WeatherStation.conf')
    return config


def get_conn(host=None):
    config = get_config()

    if host is None:
        database = config.get('DATABASE', 'Name', fallback='weather_station')
        user = config.get('DATABASE', 'User')  # Could have default fallback to os.getusername()
        password = config.get('DATABASE', 'Password')
        port = config.getint('DATABASE', 'Port', fallback=3306)
        conn = db_module.Connect(
            database=database,
            user=user,
            password=password,
            port=port)
    else:
        database = config.get('remote:' + host, 'Name', fallback='weather_station')
        user = config.get('remote:' + host, 'User')  # Could have default fallback to os.getusername()
        password = config.get('remote:' + host, 'Password')
        port = config.getint('remote:' + host, 'Port', fallback=3306)
        # Remote Pis may be unreachable (WiFi loss) or busy: fail instead of hanging the collector
        conn = db_module.Connect(
            host=host,
            database=database,
            user=user,
            password=password,
            port=port,
            connect_timeout=10,
            read_timeout=120,
            write_timeout=120)

    return conn
