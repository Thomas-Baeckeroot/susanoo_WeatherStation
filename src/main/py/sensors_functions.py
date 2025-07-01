#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import pathlib
import time
import utils

from gpiozero import CPUTemperature  # If failing: "pip install gpiozero"

logging.basicConfig(
    filename=utils.get_home() + "/susanoo-data.log",  # = /home/pi/susanoo-data.log
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8.8s%(name)-14s (%(process)5d) %(message)s')
log = logging.getLogger("sensors_functions.py")

# todo Below variable should be stored in a config file ~/.config/susanoo_WeatherStation.conf
# (GPIO numbers also could be informed there)
METEO_FOLDER = "/home/pi/meteo"


def round_value_decimals(value, decimals):
    # round() added to truncate insignificant values to save db space
    if decimals > 0:
        return round(value, decimals)
    else:
        return int(round(value, decimals))


def value_cpu_temp():
    cpu_temp = CPUTemperature().temperature
    return cpu_temp


def value_luminosity():
    tsl2561 = __import__("tsl2561")  # If failing, run: "sudo pip3 install Adafruit_GPIO tsl2561" (and also RPi.GPIO ?)
    tsl = tsl2561.TSL2561(debug=True)
    return tsl.lux()


def value_ext_temperature():
    bmp_mod = __import__("Adafruit_BMP.BMP085")
    sensor = bmp_mod.BMP085.BMP085()
    temp = sensor.read_temperature()
    return temp


def value_sealevelpressure():
    config = utils.get_config()
    sensor_known_altitude = config.getfloat('DEFAULT', 'SensorKnownAltitude', fallback=50.0)
    bmp_mod = __import__("Adafruit_BMP.BMP085")
    sensor = bmp_mod.BMP085.BMP085()
    sealevelpressure_hpa = sensor.read_sealevel_pressure(sensor_known_altitude) / 100  # Pa -> hPa
    return sealevelpressure_hpa


def log_camera_settings(l_camera):
    log.debug("╭────────┤ camera settings ├────────┄┄┄┄┄┄┄")
    log.debug(f"│ resolution = '{l_camera.resolution}'")
    log.debug(f"│ awb_mode = '{l_camera.awb_mode}'")
    log.debug(f"│ awb_gains = '{l_camera.awb_gains}'")
    log.debug(f"│ brightness = '{l_camera.brightness}'")
    log.debug(f"│ contrast = '{l_camera.contrast}'")
    log.debug(f"│ saturation = '{l_camera.saturation}'")
    log.debug(f"│ analog_gain = '{l_camera.analog_gain}'")
    log.debug(f"│ digital_gain = '{l_camera.digital_gain}'")
    log.debug(f"│ iso = '{l_camera.iso}'")
    log.debug(f"│ image_denoise = '{l_camera.image_denoise}'")
    log.debug("╰────────┄┄┄┄┄┄┄")


def take_picture(camera_name):
    log.debug(f"Taking picture for camera name '{camera_name}'...")
    picamera = __import__("picamera")
    config = utils.get_config()
    # see https://picamera.readthedocs.io/en/release-1.13/api_camera.html#picamera
    awb_mode = config.get("CAMERA:" + camera_name, "awb_mode", fallback=None)
    awb_gains_red = config.getfloat("CAMERA:" + camera_name, "awb_gains_red", fallback=None)
    awb_gains_blue = config.getfloat("CAMERA:" + camera_name, "awb_gains_blue", fallback=None)
    brightness = config.getint("CAMERA:" + camera_name, "brightness", fallback=None)
    contrast = config.getint("CAMERA:" + camera_name, "contrast", fallback=None)
    resolution = config.get("CAMERA:" + camera_name, "resolution", fallback=None)
    capture_tentatives = 0
    while capture_tentatives < 23:
        capture_tentatives = capture_tentatives + 1
        try:
            camera = picamera.PiCamera()

            if awb_mode:
                camera.awb_mode = awb_mode

            if awb_gains_red or awb_gains_blue:
                if not awb_gains_red:
                    (awb_gains_red, ignored) = camera.awb_gains
                if not awb_gains_blue:
                    (ignored, awb_gains_blue) = camera.awb_gains
                camera.awb_gains = (awb_gains_red, awb_gains_blue)

            if brightness:
                camera.brightness = brightness

            if contrast:
                camera.contrast = contrast

            if resolution:
                camera.resolution = resolution

            log.debug(f"Given camera params: awb_mode={awb_mode} awb_gains=({awb_gains_red},{awb_gains_blue}) "
                      f"brightness={brightness} resolution={resolution}")
            camera.start_preview()
            time.sleep(5)
            dt_now = utils.iso_timestamp4files()
            filename = camera_name + "_" + dt_now + ".jpg"
            capture_folder = camera_name + "/" + dt_now[0:4] + "/" + dt_now[5:10]
            base_captures_folder = "captures"  # todo get value from config file
            pathlib.Path(METEO_FOLDER + "/" + base_captures_folder + "/" + capture_folder) \
                .mkdir(mode=0o755, parents=True, exist_ok=True)
            full_path_filename = capture_folder + "/" + filename
            log.debug(f"🖼  Capturing picture '{full_path_filename}'...")
            camera.capture(METEO_FOLDER + "/" + base_captures_folder + "/" + full_path_filename)
            log_camera_settings(camera)
            camera.stop_preview()
            camera.close()
            return full_path_filename
        except picamera.exc.PiCameraMMALError:
            log.warning(f"PiCameraMMALError - retrying ({capture_tentatives})")
            time.sleep(capture_tentatives)

        # End of 'while not captured_success and capture_tentatives < 23:'
    log.error("Failed " + str(capture_tentatives) + " times to take picture. Gave up!")
    return None
