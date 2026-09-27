"""Integration tests for the web server (server3.py).

Each test class starts the real server in a temporary HOME with fake CGI scripts.
Run with the venv's python (server3.py requires pymysql and svg.charts), from the repository root:
    /usr/local/share/susanoo-py-venv/bin/python3 -m unittest discover -s src/test/py -v
Set SERVER3 to test another copy of server3.py.
"""
import http.client
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SERVER3 = os.environ.get("SERVER3") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "main", "py", "server3.py")
STATIC_SIZE = 3 * 1024 * 1024
CGI_OUTPUT_SIZE = 3 * 1024 * 1024

CGI_SCRIPTS = {
    # Unsuffixed, like captures.json or graph.svg: run through its shebang, i.e. the python3 found in PATH
    "which_python.json": "import sys\nprint('Content-Type: text/plain\\n')\nprint(sys.executable)\n",
    "slow.json": "import time\ntime.sleep(3)\nprint('Content-Type: text/plain\\n')\nprint('slow')\n",
    "big.json": "import sys\nsys.stdout.write('Content-Type: text/plain\\n\\n')\n"
                "sys.stdout.write('x' * %d)\n" % CGI_OUTPUT_SIZE,
}


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_home():
    home = tempfile.mkdtemp(prefix="server3-test-")
    public_html = os.path.join(home, "public_html")
    os.makedirs(os.path.join(public_html, "html"))
    os.makedirs(os.path.join(home, ".config"))
    for name in ["index.html", "capture.html", "captures.json", "graph.svg"]:
        with open(os.path.join(public_html, name), "w") as page:
            page.write("placeholder\n")
    for name, body in CGI_SCRIPTS.items():
        path = os.path.join(public_html, name)
        with open(path, "w") as script:
            script.write("#!/usr/bin/env python3\n" + body)
        os.chmod(path, 0o755)
    with open(os.path.join(public_html, "html", "video.mp4"), "wb") as video:
        video.write(bytes(i % 251 for i in range(STATIC_SIZE)))
    return home


def start_server(home, python=sys.executable, python_args=(), path=None):
    port = free_port()
    with open(os.path.join(home, ".config", "susanoo_WeatherStation.conf"), "w") as config:
        config.write("[DEFAULT]\nWebServerPort = %d\n" % port)
    env = dict(os.environ, HOME=home)
    if path is not None:
        env["PATH"] = path
    process = subprocess.Popen([python, *python_args, os.path.abspath(SERVER3)],
                               cwd=os.path.join(home, "public_html"), env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return process, port


def wait_until_listening(process, port, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("server exited with code %d" % process.returncode)
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("server not listening after %d s" % timeout)


def stop_server(process):
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def read_log(home):
    with open(os.path.join(home, "susanoo-web.log"), encoding="utf-8", errors="replace") as log:
        return log.read()


class RunningServerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.home = make_home()
        # PATH without the server's python dir: CGI scripts must still get the server's interpreter
        cls.process, cls.port = start_server(cls.home, path="/usr/bin:/bin")
        wait_until_listening(cls.process, cls.port)

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.process)
        shutil.rmtree(cls.home, ignore_errors=True)

    def request(self, path, headers=None, timeout=30):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def test_cgi_scripts_use_server_python(self):
        response, body = self.request("/which_python.json")
        self.assertEqual(200, response.status)
        cgi_python_dir = os.path.dirname(body.decode().strip())
        self.assertEqual(os.path.realpath(os.path.dirname(sys.executable)), os.path.realpath(cgi_python_dir))

    def test_requests_are_served_in_parallel(self):
        slow = threading.Thread(target=self.request, args=("/slow.json",))
        slow.start()
        time.sleep(0.5)
        started = time.monotonic()
        response, _ = self.request("/html/video.mp4", headers={"Range": "bytes=0-9"})
        elapsed = time.monotonic() - started
        slow.join()
        self.assertEqual(206, response.status)
        self.assertLess(elapsed, 1.5, "request waited for the slow CGI script")

    def test_large_cgi_output_is_complete_for_slow_reader(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        connection.request("GET", "/big.json")
        response = connection.getresponse()
        received = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            received += len(chunk)
            time.sleep(0.01)
        connection.close()
        self.assertEqual(CGI_OUTPUT_SIZE, received)

    def test_range_request(self):
        response, body = self.request("/html/video.mp4", headers={"Range": "bytes=1000-1999"})
        self.assertEqual(206, response.status)
        self.assertEqual("bytes 1000-1999/%d" % STATIC_SIZE, response.getheader("Content-Range"))
        self.assertEqual(bytes(i % 251 for i in range(1000, 2000)), body)

    def test_suffix_range_request(self):
        response, body = self.request("/html/video.mp4", headers={"Range": "bytes=-10"})
        self.assertEqual(206, response.status)
        self.assertEqual(bytes(i % 251 for i in range(STATIC_SIZE - 10, STATIC_SIZE)), body)

    def test_unsatisfiable_range(self):
        response, _ = self.request("/html/video.mp4", headers={"Range": "bytes=%d-" % STATIC_SIZE})
        self.assertEqual(416, response.status)
        self.assertEqual("bytes */%d" % STATIC_SIZE, response.getheader("Content-Range"))

    def test_without_range_whole_file(self):
        response, body = self.request("/html/video.mp4")
        self.assertEqual(200, response.status)
        self.assertEqual(STATIC_SIZE, len(body))

    def test_client_disconnection_logged_without_traceback(self):
        with socket.create_connection(("127.0.0.1", self.port)) as sock:
            sock.sendall(b"GET /html/video.mp4 HTTP/1.0\r\n\r\n")
            sock.recv(1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
        time.sleep(1)
        log = read_log(self.home)
        self.assertIn("disconnected", log)
        self.assertNotIn("Traceback", log)

    def test_request_duration_logged(self):
        self.request("/html/video.mp4", headers={"Range": "bytes=0-0"})
        time.sleep(0.2)
        self.assertRegex(read_log(self.home), r"'GET /html/video.mp4 HTTP/1.1' done in \d+\.\d\d s")


class StartupTest(unittest.TestCase):

    def setUp(self):
        self.home = make_home()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_exits_when_required_modules_missing(self):
        # -S: no site-packages, as with the system python3 instead of the venv's one
        process, _ = start_server(self.home, python_args=("-S",))
        try:
            exit_code = process.wait(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
        self.assertEqual(1, exit_code)
        self.assertIn("CRITICAL", read_log(self.home))

    def test_sigterm_exits_cleanly(self):
        process, port = start_server(self.home)
        wait_until_listening(process, port)
        process.terminate()
        self.assertEqual(0, process.wait(timeout=10))
        self.assertIn("Terminating", read_log(self.home))


if __name__ == "__main__":
    unittest.main()
