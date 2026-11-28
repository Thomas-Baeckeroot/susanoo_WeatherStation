"""Tests of the CGI script captures.json.py (list of the pictures of a camera and a day), run in-process in a
temporary web root. Run from the repository root with any python3 >= 3.7:
    python3 -m unittest discover -s src/test/py -p test_captures.py -v
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

PUBLIC_HTML = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "..", "..", "main", "py", "public_html"))


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as picture:
        picture.write(b"jpg")


class CapturesJsonTest(unittest.TestCase):

    def setUp(self):
        self.saved_cwd = os.getcwd()
        self.root = tempfile.mkdtemp(prefix="captures-test-")
        web_root = os.path.join(self.root, "public_html")
        # Synology index folders sort before the camera, year and day folders: never picked
        for folder in ("captures/@eaDir/x.jpg", "captures/cam1/@eaDir", "captures/cam1/2026/@eaDir"):
            os.makedirs(os.path.join(web_root, folder))
        touch(os.path.join(web_root, "captures/cam1/2026/11-28/cam1_2026-11-28Z12-34-56.jpg"))
        touch(os.path.join(web_root, "captures/cam2/2025/07-01/cam2_2025-07-01Z08-00-00.jpg"))
        # Elsewhere on the server, laid out like a camera folder
        touch(os.path.join(self.root, "private/2024/01-02/secret_2024-01-02Z10-20-30.jpg"))
        os.chdir(web_root)
        fake_db = types.ModuleType("db_module")
        fake_db.get_home = lambda: self.root  # log file
        self.saved_db_module = sys.modules.get("db_module")
        sys.modules["db_module"] = fake_db

    def tearDown(self):
        os.chdir(self.saved_cwd)
        if self.saved_db_module is None:
            sys.modules.pop("db_module", None)
        else:
            sys.modules["db_module"] = self.saved_db_module
        os.environ.pop("QUERY_STRING", None)
        shutil.rmtree(self.root, ignore_errors=True)

    def run_script(self, query):
        spec = importlib.util.spec_from_file_location("captures_json", os.path.join(PUBLIC_HTML, "captures.json.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        os.environ["QUERY_STRING"] = query
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            module.main()
        return json.loads(output.getvalue().partition("\n\n")[2])

    def test_pictures_of_a_camera_and_day(self):
        data = self.run_script("s=cam1&y=2026&m=11&d=28")
        self.assertEqual({"12h34": {"fSize": 3, "img": "cam1_2026-11-28Z12-34-56.jpg"}}, data["pictures"])
        properties = data["picturesProperties"]
        self.assertEqual(("cam1", "2026", "11-28"),
                         (properties["sensor"], str(properties["year"]), properties["month_day"]))

    def test_defaults_skip_synology_index_folders(self):
        data = self.run_script("")
        self.assertEqual("cam1", data["picturesProperties"]["sensor"])
        self.assertEqual("2026", str(data["picturesProperties"]["year"]))
        self.assertEqual(1, len(data["pictures"]))

    def test_path_instead_of_camera_name_is_refused(self):
        for sensor in ("../../private", "..", "cam1/../../../private", "@eaDir", "/etc"):
            data = self.run_script("s=" + sensor + "&y=2024&m=1&d=2")
            self.assertEqual("cam1", data["picturesProperties"]["sensor"], sensor)
            self.assertNotIn("secret", json.dumps(data), sensor)
            self.assertIn("was not valid", data["picturesProperties"]["error_message"], sensor)


if __name__ == "__main__":
    unittest.main()
