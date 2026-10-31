# SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
# SPDX-License-Identifier: GPL-3.0-or-later
"""Behaviour tests for the build updater. Run from the plugin folder:
python -B -m unittest discover -s tests

The digests are literal values from sha256sum. The release data has the form of the GitHub API.
"""
import io
import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

import eglantine_ini as ini  # noqa: E402
import eglantine_update as update  # noqa: E402

PAYLOAD = b"new build"
PAYLOAD_SHA = "9893f46b04f2b89047dac4860978f401114b41f20aedf9abac1a7bb218496321"
OTHER_SHA = "a3ead5eedad5df82318c51685dbc1c147a36d1ff8584fc82de6b08d0bf63a795"
BASE = "https://github.com/alarok/Eglantine/releases/download"
SCRIPT = (
    '#!/bin/bash\n'
    '# Start a game.\n'
    'exec "$HOME/Applications/eglantine-build{}-steamdeck-pgo.AppImage" -f -g "$HOME/game/main"\n'
)


def release(build, sha=PAYLOAD_SHA, name="eglantine-6fd92472-linux-x86_64-steamdeck-pgo.AppImage",
            url=None, **fields):
    return {
        "tag_name": f"build-{build}",
        "draft": False,
        "prerelease": True,
        "assets": [
            {
                "name": "eglantine-6fd92472-linux-x86_64-pgo.AppImage",
                "digest": "sha256:" + OTHER_SHA,
                "browser_download_url": f"{BASE}/build-{build}/wrong.AppImage",
            },
            {
                "name": name,
                "digest": "sha256:" + sha,
                "browser_download_url": url or f"{BASE}/build-{build}/{name}",
            },
        ],
        **fields,
    }


class FakeNet:
    """Answer the release list and the download, and record each request."""

    def __init__(self, releases, payload=PAYLOAD, fail_list=False, during_download=None):
        self.releases = releases
        self.payload = payload
        self.fail_list = fail_list
        self.during_download = during_download
        self.downloads = []

    def __call__(self, url):
        if url == update.RELEASES_URL:
            if self.fail_list:
                raise OSError("no network")
            return io.BytesIO(json.dumps(self.releases).encode())
        self.downloads.append(url)
        if self.during_download:
            self.during_download()
        if isinstance(self.payload, Exception):
            return _Broken(self.payload)
        return io.BytesIO(self.payload)


class _Broken(io.BytesIO):
    def __init__(self, error):
        super().__init__(b"part")
        self.error = error

    def read(self, size=-1):
        data = super().read(size)
        if not data:
            raise self.error
        return data


def stopped():
    return False


def playing():
    return True


class Folder(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = temp.name

    def appimage(self, build, data=b"old"):
        path = os.path.join(self.dir, f"eglantine-build{build}-steamdeck-pgo.AppImage")
        with open(path, "wb") as f:
            f.write(data)
        return path

    def script(self, name, build):
        path = os.path.join(self.dir, name)
        with open(path, "w", newline="") as f:
            f.write(SCRIPT.format(build))
        os.chmod(path, 0o755)
        return path

    def text(self, path):
        with open(path, newline="") as f:
            return f.read()

    def names(self):
        return sorted(os.listdir(self.dir))


class LatestRelease(unittest.TestCase):
    def test_takes_the_highest_number_and_not_the_highest_text(self):
        found = update.latest_release([release(9), release(28), release(100)])
        self.assertEqual(found["build"], 100)

    def test_a_prerelease_counts(self):
        self.assertEqual(update.latest_release([release(28, prerelease=True)])["build"], 28)

    def test_takes_the_steamdeck_asset_with_its_own_digest(self):
        found = update.latest_release([release(28)])
        self.assertEqual(found["sha256"], PAYLOAD_SHA)
        self.assertIn("steamdeck-pgo", found["url"])

    def test_a_build_with_no_steamdeck_asset_yet_is_not_used(self):
        partial = release(29, name="eglantine-6fd92472-linux-x86_64.AppImage")
        self.assertEqual(update.latest_release([partial, release(28)])["build"], 28)

    def test_a_draft_and_another_tag_are_not_used(self):
        other = release(29)
        other["tag_name"] = "v29"
        found = update.latest_release([release(30, draft=True), other, release(28)])
        self.assertEqual(found["build"], 28)

    def test_an_asset_with_no_digest_is_not_used(self):
        no_digest = release(29)
        no_digest["assets"][1]["digest"] = None
        self.assertEqual(update.latest_release([no_digest, release(28)])["build"], 28)

    def test_an_asset_from_another_host_is_not_used(self):
        foreign = release(29, url="https://example.com/build-29/x.AppImage")
        self.assertEqual(update.latest_release([foreign, release(28)])["build"], 28)

    def test_no_usable_release(self):
        self.assertIsNone(update.latest_release([]))


class Update(Folder):
    def test_downloads_and_changes_only_the_name_in_each_script(self):
        self.appimage(28)
        a = self.script("bananza.sh", 28)
        b = self.script("pokopia.sh", 28)
        net = FakeNet([release(29)])
        update.update(self.dir, stopped, net)
        self.assertEqual(self.text(a), SCRIPT.format(29))
        self.assertEqual(self.text(b), SCRIPT.format(29))
        with open(os.path.join(self.dir, "eglantine-build29-steamdeck-pgo.AppImage"), "rb") as f:
            self.assertEqual(f.read(), PAYLOAD)

    def test_keeps_the_old_build_and_leaves_no_temporary_file(self):
        self.appimage(28)
        self.script("game.sh", 28)
        update.update(self.dir, stopped, FakeNet([release(29)]))
        self.assertEqual(
            self.names(),
            [
                "eglantine-build28-steamdeck-pgo.AppImage",
                "eglantine-build29-steamdeck-pgo.AppImage",
                "game.sh",
            ],
        )

    @unittest.skipIf(os.name == "nt", "Windows has no execute bit")
    def test_the_build_and_the_script_can_run(self):
        self.appimage(28)
        script = self.script("game.sh", 28)
        update.update(self.dir, stopped, FakeNet([release(29)]))
        build = os.path.join(self.dir, "eglantine-build29-steamdeck-pgo.AppImage")
        self.assertEqual(stat.S_IMODE(os.stat(build).st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(os.stat(script).st_mode), 0o755)

    def test_a_wrong_digest_changes_nothing(self):
        self.appimage(28)
        script = self.script("game.sh", 28)
        before = self.names()
        with self.assertRaises(ini.Refused):
            update.update(self.dir, stopped, FakeNet([release(29)], payload=b"bad bytes"))
        self.assertEqual(self.names(), before)
        self.assertEqual(self.text(script), SCRIPT.format(28))

    def test_a_broken_download_changes_nothing(self):
        self.appimage(28)
        script = self.script("game.sh", 28)
        before = self.names()
        with self.assertRaises(OSError):
            update.update(self.dir, stopped, FakeNet([release(29)], payload=OSError("cut")))
        self.assertEqual(self.names(), before)
        self.assertEqual(self.text(script), SCRIPT.format(28))

    def test_no_download_while_the_emulator_runs(self):
        self.appimage(28)
        script = self.script("game.sh", 28)
        net = FakeNet([release(29)])
        with self.assertRaises(ini.Refused):
            update.update(self.dir, playing, net)
        self.assertEqual(net.downloads, [])
        self.assertEqual(self.text(script), SCRIPT.format(28))

    def test_a_game_that_starts_during_the_download_stops_the_change(self):
        self.appimage(28)
        script = self.script("game.sh", 28)
        state = {"running": False}
        net = FakeNet([release(29)], during_download=lambda: state.update(running=True))
        with self.assertRaises(ini.Refused):
            update.update(self.dir, lambda: state["running"], net)
        self.assertEqual(self.text(script), SCRIPT.format(28))
        # The finished download stays, so that the next press does not download it again.
        state["running"] = False
        again = FakeNet([release(29)])
        update.update(self.dir, stopped, again)
        self.assertEqual(again.downloads, [])
        self.assertEqual(self.text(script), SCRIPT.format(29))

    def test_a_local_file_with_the_right_digest_is_not_downloaded(self):
        self.appimage(28)
        self.appimage(29, PAYLOAD)
        script = self.script("game.sh", 28)
        net = FakeNet([release(29)])
        update.update(self.dir, stopped, net)
        self.assertEqual(net.downloads, [])
        self.assertEqual(self.text(script), SCRIPT.format(29))

    def test_a_local_file_with_another_digest_is_replaced(self):
        self.appimage(28)
        path = self.appimage(29, b"damaged")
        self.script("game.sh", 28)
        update.update(self.dir, stopped, FakeNet([release(29)]))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), PAYLOAD)

    def test_never_goes_to_a_lower_or_equal_build(self):
        self.appimage(30)
        script = self.script("game.sh", 30)
        with self.assertRaises(ini.Refused):
            update.update(self.dir, stopped, FakeNet([release(29)]))
        self.assertEqual(self.text(script), SCRIPT.format(30))

    def test_a_script_with_no_build_name_stays(self):
        self.appimage(28)
        self.script("game.sh", 28)
        other = os.path.join(self.dir, "other.sh")
        with open(other, "w", newline="") as f:
            f.write("#!/bin/bash\nexec other-program\n")
        update.update(self.dir, stopped, FakeNet([release(29)]))
        self.assertEqual(self.text(other), "#!/bin/bash\nexec other-program\n")

    def test_a_second_press_during_a_download_is_refused(self):
        self.appimage(28)
        self.script("game.sh", 28)
        results = []

        def press_again():
            try:
                update.update(self.dir, stopped, FakeNet([release(29)]))
            except ini.Refused as e:
                results.append(str(e))

        update.update(self.dir, stopped, FakeNet([release(29)], during_download=press_again))
        self.assertEqual(len(results), 1)


class Rollback(Folder):
    def test_goes_to_the_highest_lower_build_on_the_disk(self):
        for build in (25, 27, 28):
            self.appimage(build)
        script = self.script("game.sh", 28)
        update.rollback(self.dir, stopped)
        self.assertEqual(self.text(script), SCRIPT.format(27))

    def test_all_scripts_go_to_the_same_build(self):
        for build in (26, 27, 28):
            self.appimage(build)
        a = self.script("a.sh", 28)
        b = self.script("b.sh", 27)
        update.rollback(self.dir, stopped)
        self.assertEqual(self.text(a), SCRIPT.format(27))
        self.assertEqual(self.text(b), SCRIPT.format(27))

    def test_refused_while_the_emulator_runs(self):
        self.appimage(27)
        self.appimage(28)
        script = self.script("game.sh", 28)
        with self.assertRaises(ini.Refused):
            update.rollback(self.dir, playing)
        self.assertEqual(self.text(script), SCRIPT.format(28))

    def test_refused_with_no_older_build(self):
        self.appimage(28)
        script = self.script("game.sh", 28)
        with self.assertRaises(ini.Refused):
            update.rollback(self.dir, stopped)
        self.assertEqual(self.text(script), SCRIPT.format(28))

    def test_a_temporary_file_is_not_a_build(self):
        self.appimage(28)
        with open(os.path.join(self.dir, "eglantine-build27-steamdeck-pgo.AppImage.decky-tmp"), "wb"):
            pass
        self.script("game.sh", 28)
        with self.assertRaises(ini.Refused):
            update.rollback(self.dir, stopped)


class Check(Folder):
    def test_a_higher_build_is_an_update(self):
        self.appimage(27)
        self.appimage(28)
        self.script("game.sh", 28)
        state = update.check(self.dir, FakeNet([release(29)]))
        self.assertTrue(state["available"])
        self.assertEqual(state["current"], [28])
        self.assertEqual(state["latest"], 29)
        self.assertTrue(state["update"])
        self.assertEqual(state["previous"], 27)

    def test_the_same_or_a_lower_build_is_no_update(self):
        self.appimage(28)
        self.script("game.sh", 28)
        self.assertFalse(update.check(self.dir, FakeNet([release(28)]))["update"])
        self.assertFalse(update.check(self.dir, FakeNet([release(27)]))["update"])
        self.assertIsNone(update.check(self.dir, FakeNet([release(28)]))["previous"])

    def test_scripts_on_two_builds_show_both(self):
        self.appimage(27)
        self.appimage(28)
        self.script("a.sh", 28)
        self.script("b.sh", 27)
        state = update.check(self.dir, FakeNet([release(28)]))
        self.assertEqual(state["current"], [27, 28])
        self.assertFalse(state["update"])

    def test_no_network_still_shows_the_local_state(self):
        self.appimage(27)
        self.appimage(28)
        self.script("game.sh", 28)
        state = update.check(self.dir, FakeNet([], fail_list=True))
        self.assertEqual(state["current"], [28])
        self.assertEqual(state["previous"], 27)
        self.assertFalse(state["update"])
        self.assertIn("no network", state["error"])

    def test_bad_data_from_the_network_is_an_error_and_not_a_crash(self):
        self.script("game.sh", 28)

        def opener(url):
            return io.BytesIO(b"not json")

        self.assertIsNotNone(update.check(self.dir, opener)["error"])

    def test_a_console_with_no_scripts_has_no_updater(self):
        self.assertFalse(update.check(self.dir, FakeNet([release(29)]))["available"])
        missing = os.path.join(self.dir, "missing")
        self.assertFalse(update.check(missing, FakeNet([release(29)]))["available"])

    def test_during_a_download_the_check_shows_busy_and_uses_no_network(self):
        self.appimage(28)
        self.script("game.sh", 28)
        seen = []

        def look():
            quiet = FakeNet([], fail_list=True)
            seen.append(update.check(self.dir, quiet))

        update.update(self.dir, stopped, FakeNet([release(29)], during_download=look))
        self.assertTrue(seen[0]["busy"])
        self.assertIsNone(seen[0]["error"])
        self.assertFalse(update.check(self.dir, FakeNet([release(29)]))["busy"])


if __name__ == "__main__":
    unittest.main()
