#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Sample based from https://python-django.dev/page-python-serveur-web-creer-rapidement

import http.server
import cgitb
import faulthandler
import importlib.util
import logging
import os
import re
import signal
import socket
import sys
import threading
import time

HOME = os.path.expanduser("~")
LOG_FILE = HOME + "/susanoo-web.log"
# faulthandler writes raw stack dumps, kept apart from the regular log
FAULT_LOG_FILE = HOME + "/susanoo-web.faults.log"
SLOW_REQUEST_SECONDS = 30
HEARTBEAT_SECONDS = 3600
# Idle time after which a silent client connection is dropped, freeing its thread
CLIENT_TIMEOUT_SECONDS = 120

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8.8s%(name)-14s (%(process)5d) %(threadName)s %(message)s')
log = logging.getLogger("server3.py")

try:
    from utils import get_config
except Exception:
    # Typically "No module named 'pymysql'" when not started with the venv's python3
    log.critical("Failed to import project modules with %s", sys.executable, exc_info=True)
    raise


def sigterm_handler(signum, frame):
    log.info("Received SIGTERM signal. Exiting gracefully...")
    close_server()


def close_server():
    # Close the server socket to stop accepting new connections
    try:
        httpd.socket.close()
    except Exception as e:
        log.error(f"Error while closing the server socket: {e}")
    log.info("Terminating _____________________________________________\n")
    sys.exit(0)


def file_exists(filename):
    if os.path.exists(filename):
        # log.debug(f"File '{filename}' exists in the current folder.")
        return True
    else:
        log.debug(f"File '{filename}' not found in the current folder.")
        return False


def check_symlinks():
    for filename in ["capture.html", "captures.json", "graph.svg", "index.html"]:  # finishing with "index.html"
        if file_exists(filename):
            log.debug(f"File '{filename}' found in working directory.")
        else:
            if file_exists(filename + ".py"):
                os.symlink(filename + ".py", filename)
                log.warning(f"Symbolic link '{filename}' -> '{filename}.py' created in working directory.")
            else:
                log.error(f"Failed to find '{filename}.py' in working directory!")
    return


def current_dir_is_valid_working_dir():
    if file_exists("index.html") or file_exists("index.html.py"):
        log.debug(f"Current folder looks good as working directory for server.")
        return True
    else:
        log.info("Working directory does not contain expected files for web server.")
        log.warning("Please review the way the server is launched: "
                    "it should be launched from the folder that contains 'index.html', etc...")
        return False


def check_working_dir():
    # Path of Python 3 binary (Virtual Env.):
    log.info("Path to Python binary (expected starting with venv): {0}".format(sys.executable))

    # Working path: server should be started from the folder containing index.html(.py)
    if not current_dir_is_valid_working_dir():
        if file_exists("public_html"):
            os.chdir("public_html")
            if not current_dir_is_valid_working_dir():
                os.chdir(HOME)
                if not current_dir_is_valid_working_dir():
                    log.critical("Unable to find pages to serve!")
        else:
            os.chdir(HOME)
            # TODO Server should start by default in "~/public_html/" ('captures' folder has to be moved there also)
            if not current_dir_is_valid_working_dir():
                log.critical("Unable to find pages to serve!")

    check_symlinks()

    return


def put_own_python_first_in_path():
    # Unsuffixed CGI scripts (captures.json, graph.svg...) run through '#!/usr/bin/env python3',
    # so they only get the venv's modules if its bin/ comes first in PATH
    python_dir = os.path.dirname(sys.executable)
    os.environ["PATH"] = python_dir + os.pathsep + os.environ.get("PATH", "")
    log.info("PATH for CGI scripts starts with '%s'", python_dir)


def check_python_modules():
    # CGI scripts are run with sys.executable, so its environment must provide these
    missing = []
    for module_name in ["pymysql", "svg.charts"]:
        try:
            found = importlib.util.find_spec(module_name) is not None
        except ImportError:
            found = False
        if not found:
            missing.append(module_name)
    if missing:
        log.critical("Modules %s not available for %s (was the venv's python3 used?)", missing, sys.executable)
        sys.exit(1)
    log.info("All required modules are present.")


CLIENT_DISCONNECTIONS = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError, socket.timeout)

# Single "bytes=first-last" range only; other forms fall back to a full 200 response
RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)$")

# thread name -> (request line, start time), to spot requests that hang
in_flight = {}
in_flight_lock = threading.Lock()


class LoggingCGIHandler(http.server.CGIHTTPRequestHandler):
    # handler.cgi_directories = ["~/public_html/"]  # Should be better if other than '/' but never worked...
    cgi_directories = ["/"]
    timeout = CLIENT_TIMEOUT_SECONDS

    def log_message(self, format, *args):
        log.info("%s %s", self.address_string(), format % args)

    def parse_request(self):
        ok = super().parse_request()
        with in_flight_lock:
            in_flight[threading.current_thread().name] = (self.requestline, time.monotonic())
        return ok

    def handle_one_request(self):
        try:
            super().handle_one_request()
        finally:
            with in_flight_lock:
                entry = in_flight.pop(threading.current_thread().name, None)
            if entry:
                request_line, started = entry
                elapsed = time.monotonic() - started
                level = logging.WARNING if elapsed >= SLOW_REQUEST_SECONDS else logging.DEBUG
                log.log(level, "%s %r done in %.2f s", self.address_string(), request_line, elapsed)


    def send_head(self):
        self.range_remaining = None
        range_header = self.headers.get("Range")
        match = RANGE_PATTERN.match(range_header.strip()) if range_header else None
        if not match or match.groups() == ("", "") or self.is_cgi():
            return super().send_head()
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try:
            source = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None
        size = os.fstat(source.fileno()).st_size
        first, last = match.groups()
        if first == "":
            start, end = max(size - int(last), 0), size - 1
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        if start >= size or start > end:
            source.close()
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Last-Modified", self.date_time_string(os.fstat(source.fileno()).st_mtime))
        self.end_headers()
        source.seek(start)
        self.range_remaining = end - start + 1
        return source

    def copyfile(self, source, outputfile):
        if self.range_remaining is None:
            return super().copyfile(source, outputfile)
        while self.range_remaining > 0:
            chunk = source.read(min(64 * 1024, self.range_remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            self.range_remaining -= len(chunk)


class LoggingHTTPServer(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, CLIENT_DISCONNECTIONS):
            log.info("%s disconnected: %r", client_address[0], error)
        else:
            log.exception("Error while handling request from %s", client_address[0])


def heartbeat():
    while True:
        time.sleep(HEARTBEAT_SECONDS)
        now = time.monotonic()
        with in_flight_lock:
            running = [(name, line, now - started) for name, (line, started) in in_flight.items()]
        log.info("Heartbeat: %d thread(s), %d request(s) in progress", threading.active_count(), len(running))
        for name, line, elapsed in running:
            if elapsed >= SLOW_REQUEST_SECONDS:
                log.warning("Request %r in %s running for %.0f s", line, name, elapsed)


def log_uncaught(exc_type, exc_value, exc_traceback):
    log.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = log_uncaught
threading.excepthook = lambda hook_args: log.critical(
    "Uncaught exception in thread %s", hook_args.thread.name if hook_args.thread else "?",
    exc_info=(hook_args.exc_type, hook_args.exc_value, hook_args.exc_traceback))

signal.signal(signal.SIGTERM, sigterm_handler)

# Stacks of all threads on fatal errors, and on demand with: kill -USR1 <pid>
fault_log = open(FAULT_LOG_FILE, "a")
faulthandler.enable(file=fault_log, all_threads=True)
faulthandler.register(signal.SIGUSR1, file=fault_log, all_threads=True)

print(f"HTTP server log is sent to '{LOG_FILE}'.")
log.info("Starting ‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾")
log.info("PID %d, Python %s; 'kill -USR1 %d' dumps all thread stacks to '%s'",
         os.getpid(), sys.version.split()[0], os.getpid(), FAULT_LOG_FILE)

check_working_dir()

check_python_modules()

put_own_python_first_in_path()

cgitb.enable()

config = get_config()
port = config.getint('DEFAULT', 'WebServerPort', fallback=8080)
server_address = ("", port)

log.debug("Launching server from path '{0}' on port {1}...".format(os.getcwd(), port))
log.debug(f"Handler.cgi_directories = {LoggingCGIHandler.cgi_directories}")

threading.Thread(target=heartbeat, name="heartbeat", daemon=True).start()

httpd = LoggingHTTPServer(server_address, LoggingCGIHandler)
try:
    httpd.serve_forever()
except KeyboardInterrupt:
    log.info("Keyboard interruption intercepted. Exiting gracefully...")
    close_server()
