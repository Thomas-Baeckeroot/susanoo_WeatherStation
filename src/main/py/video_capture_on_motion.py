#!/usr/bin/env python
# -*- coding: utf-8 -*-

# import os
import picamera
import RPi.GPIO as GPIO    # Import Raspberry Pi GPIO library
# import subprocess
import sys
import time     # Import the sleep function from the time module

import sensors_functions as func
import utils


# todo Below variables should be stored in config file ~/.config/susanoo_WeatherStation.conf
METEO_FOLDER = "/home/pi/meteo/"
VIDEOS_FOLDER = METEO_FOLDER + "videos/"

GPIO_MVT_DETECTOR_IN = 18

# GPIO_YYY_LED = 23
# GPIO_ZZZ_LED = 24
GPIO_WATCHDOG_LED = 25

GPIO_XXX_BTN_IN = 12
GPIO_YYY_BTN_IN = 16
GPIO_ZZZ_BTN_IN = 20
# GPIO_SHUTDOWN_BTN_IN = 21

GPIO_XXX_RELAY_OUT = 6
GPIO_YYY_RELAY_OUT = 13
GPIO_CPU_FAN_RELAY_OUT = 19
GPIO_IR_LIGHTS_RELAY_OUT = 26

MIN_LUMINOSITY_WITHOUT_IR = 30


def start_video_capture():
    print(utils.iso_timestamp_now() + " - Movement detected, should start a thread for camera filming")
    
    try:
        luminosity = func.value_luminosity()
    except IOError:
        print("IOError occurred when reading luminosity!")
        luminosity = -1

    if luminosity < MIN_LUMINOSITY_WITHOUT_IR:
        low_light = True
        GPIO.output(GPIO_IR_LIGHTS_RELAY_OUT, GPIO.LOW)
    else:
        low_light = False
        GPIO.output(GPIO_IR_LIGHTS_RELAY_OUT, GPIO.HIGH)  # should not be necessary
    print(utils.iso_timestamp_now() + " - low_light = " + str(low_light))
    sys.stdout.flush()

    captured_success = False
    capture_tentatives = 0
    while not captured_success and capture_tentatives < 23:
        capture_tentatives = capture_tentatives + 1
        try:
            camera = picamera.PiCamera()
            # TODO This implementation is deprecated! Duplicated version sensors_functions.py:72 is preferable.
            camera.awb_mode = 'off'
            camera.awb_gains = (1.6, 1.0)
            camera.brightness = 46
            camera.resolution = (1296, 972)  # binned mode below 1296x972
            camera.start_preview()
            time.sleep(5)
            dt_now = utils.iso_timestamp4files()
            filename = VIDEOS_FOLDER + "camera1_" + dt_now + ".h264"  # fixme improve with os.path.join
            print(filename)
            camera.start_recording(filename)
            time.sleep(10)
            print("Stop recording")
            camera.stop_recording()
            camera.stop_preview()
            camera.close()
            time.sleep(1)
            captured_success = True
        except picamera.exc.PiCameraMMALError:
            sys.stdout.write(".")
            time.sleep(capture_tentatives)

    if not captured_success:
        print("failed " + str(capture_tentatives) + " times to take picture. Gave up!")
        sys.stdout.flush()

    GPIO.output(GPIO_IR_LIGHTS_RELAY_OUT, GPIO.HIGH)
    return
    

def main():  # Expected to be launched at startup
    print(utils.iso_timestamp_now() + " - Waiting for movement to trigger video capture...")
    sys.stdout.flush()
    # GPIO.setwarnings(False)    # Ignore warning for now
    GPIO.setmode(GPIO.BCM)   # Use GPIO numbering
    
    GPIO.setup(GPIO_MVT_DETECTOR_IN, GPIO.IN)  # movement detector
    GPIO.setup(GPIO_IR_LIGHTS_RELAY_OUT, GPIO.OUT, initial=GPIO.HIGH)
    # high/low (possibly because of the way the input button is read...)

    waiting_time = 0
    while True:  # Run forever
        
        if GPIO.input(GPIO_MVT_DETECTOR_IN):
            start_video_capture()
        
        time.sleep(0.1)  # length of cycle
        waiting_time = waiting_time + 1
        if waiting_time > (10*60*60):  # (10*60*60) -> 1 hour
            print(utils.iso_timestamp_now() + " - one hour and still waiting...")
            sys.stdout.flush()
            waiting_time = 0
            

if __name__ == "__main__":
    main()
