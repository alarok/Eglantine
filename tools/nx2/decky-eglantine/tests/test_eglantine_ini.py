# SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
# SPDX-License-Identifier: GPL-3.0-or-later
"""Behaviour tests for the ini logic. Run from the plugin folder:
python -B -m unittest discover -s tests

Expected text is written by hand from what src/frontend_common/config.cpp reads and writes.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

import eglantine_ini as ini  # noqa: E402

GLOBAL_TEXT = (
    "[Core]\n"
    "use_multi_core\\default=true\n"
    "use_multi_core=true\n"
    "\n"
    "[Renderer]\n"
    "resolution_setup\\default=true\n"
    "resolution_setup=3\n"
    "frame_gen\\default=true\n"
    "frame_gen=false\n"
    "frame_gen_multiplier\\default=true\n"
    "frame_gen_multiplier=2\n"
    "gpu_accuracy\\default=true\n"
    "gpu_accuracy=1\n"
    "dma_accuracy\\default=false\n"
    "dma_accuracy=2\n"
    "\n"
    "[System]\n"
    "use_docked_mode\\default=true\n"
    "use_docked_mode=1\n"
)

GAME_TEXT = (
    "[Renderer]\n"
    "resolution_setup\\use_global=true\n"
    "frame_gen\\use_global=false\n"
    "frame_gen\\default=false\n"
    "frame_gen=true\n"
    "\n"
    "[System]\n"
    "use_docked_mode\\use_global=true\n"
)


class SetValue(unittest.TestCase):
    def test_global_value_changes_two_lines_and_keeps_all_other_bytes(self):
        result = ini.set_value(GLOBAL_TEXT, "Renderer", "resolution_setup", "2", per_game=False)
        expected = GLOBAL_TEXT.replace(
            "resolution_setup\\default=true\nresolution_setup=3\n",
            "resolution_setup\\default=false\nresolution_setup=2\n",
        )
        self.assertEqual(result, expected)

    def test_a_key_with_a_longer_name_stays(self):
        result = ini.set_value(GLOBAL_TEXT, "Renderer", "frame_gen", "true", per_game=False)
        self.assertIn("frame_gen=true\n", result)
        self.assertIn("frame_gen_multiplier\\default=true\nframe_gen_multiplier=2\n", result)

    def test_the_same_key_in_another_section_stays(self):
        text = "[Renderer]\nuse_docked_mode=9\n\n[System]\nuse_docked_mode\\default=true\nuse_docked_mode=1\n"
        result = ini.set_value(text, "System", "use_docked_mode", "0", per_game=False)
        self.assertEqual(
            result,
            "[Renderer]\nuse_docked_mode=9\n\n[System]\nuse_docked_mode\\default=false\nuse_docked_mode=0\n",
        )

    def test_a_missing_key_goes_in_its_section_before_the_blank_line(self):
        text = "[Renderer]\nbackend=1\n\n[System]\nregion_index=2\n"
        result = ini.set_value(text, "Renderer", "frame_gen_type", "1", per_game=False)
        self.assertEqual(
            result,
            "[Renderer]\nbackend=1\nframe_gen_type\\default=false\nframe_gen_type=1\n\n[System]\nregion_index=2\n",
        )

    def test_a_missing_section_goes_at_the_end(self):
        result = ini.set_value("[Core]\na=1\n", "Renderer", "frame_gen", "true", per_game=False)
        self.assertEqual(result, "[Core]\na=1\n\n[Renderer]\nframe_gen\\default=false\nframe_gen=true\n")

    def test_per_game_value_clears_use_global(self):
        result = ini.set_value(GAME_TEXT, "Renderer", "resolution_setup", "1", per_game=True)
        expected = GAME_TEXT.replace(
            "resolution_setup\\use_global=true\n",
            "resolution_setup\\use_global=false\nresolution_setup\\default=false\nresolution_setup=1\n",
        )
        self.assertEqual(result, expected)

    def test_crlf_and_no_final_newline_stay(self):
        text = "[Renderer]\r\nframe_gen\\default=true\r\nframe_gen=false"
        result = ini.set_value(text, "Renderer", "frame_gen", "true", per_game=False)
        self.assertEqual(result, "[Renderer]\r\nframe_gen\\default=false\r\nframe_gen=true")

    def test_duplicate_lines_become_one(self):
        text = "[Renderer]\nframe_gen=false\nother=1\nframe_gen=true\n"
        result = ini.set_value(text, "Renderer", "frame_gen", "false", per_game=False)
        self.assertEqual(result, "[Renderer]\nframe_gen\\default=false\nframe_gen=false\nother=1\n")


class SetInherit(unittest.TestCase):
    def test_per_game_inherit_leaves_only_use_global(self):
        result = ini.set_inherit(GAME_TEXT, "Renderer", "frame_gen", per_game=True)
        expected = GAME_TEXT.replace(
            "frame_gen\\use_global=false\nframe_gen\\default=false\nframe_gen=true\n",
            "frame_gen\\use_global=true\n",
        )
        self.assertEqual(result, expected)

    def test_global_inherit_sets_default_and_keeps_the_value_line(self):
        result = ini.set_inherit(GLOBAL_TEXT, "Renderer", "dma_accuracy", per_game=False)
        expected = GLOBAL_TEXT.replace("dma_accuracy\\default=false\n", "dma_accuracy\\default=true\n")
        self.assertEqual(result, expected)


class ReadState(unittest.TestCase):
    def setUp(self):
        self.global_values = ini.read_section(GLOBAL_TEXT, "Renderer")
        self.game_values = ini.read_section(GAME_TEXT, "Renderer")

    def test_global_with_default_true_is_inherited(self):
        self.assertEqual(ini.read_global(self.global_values, "resolution_setup"), ("inherit", "3"))

    def test_global_with_default_false_is_the_value(self):
        self.assertEqual(ini.read_global(self.global_values, "dma_accuracy"), ("2", "2"))

    def test_global_with_no_lines_has_no_known_value(self):
        self.assertEqual(ini.read_global({}, "frame_gen_type"), ("inherit", None))

    def test_a_missing_default_line_counts_as_default(self):
        # config.cpp reads "key\default" with true as the fallback.
        self.assertEqual(ini.read_global({"frame_gen": "true"}, "frame_gen"), ("inherit", "true"))

    def test_game_override_wins_over_global(self):
        self.assertEqual(
            ini.read_game(self.game_values, self.global_values, "frame_gen"), ("true", "true")
        )

    def test_game_use_global_takes_the_global_value(self):
        self.assertEqual(
            ini.read_game(self.game_values, self.global_values, "resolution_setup"), ("inherit", "3")
        )

    def test_game_with_no_lines_takes_the_global_value(self):
        self.assertEqual(ini.read_game({}, self.global_values, "dma_accuracy"), ("inherit", "2"))


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "qt-config.ini")
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            f.write("first\n")

    def read(self, path):
        with open(path, newline="", encoding="utf-8") as f:
            return f.read()

    def test_backup_holds_the_first_text_only(self):
        ini.write_file(self.path, "second\n")
        ini.write_file(self.path, "third\n")
        self.assertEqual(self.read(self.path), "third\n")
        self.assertEqual(self.read(self.path + ini.BACKUP_SUFFIX), "first\n")

    def test_a_failed_replace_keeps_the_old_file_and_no_temp_file(self):
        with mock.patch("os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                ini.write_file(self.path, "second\n")
        self.assertEqual(self.read(self.path), "first\n")
        self.assertEqual(
            sorted(os.listdir(self.tmp.name)), ["qt-config.ini", "qt-config.ini" + ini.BACKUP_SUFFIX]
        )

    def test_invalid_bytes_survive_a_round_trip(self):
        raw = b"[UI]\nname=caf\xe9\n"
        with open(self.path, "wb") as f:
            f.write(raw)
        ini.write_file(self.path, ini.read_file(self.path))
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), raw)


class Config(unittest.TestCase):
    TITLE = "040074A01BF12000"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        os.mkdir(os.path.join(self.dir, "custom"))
        self.global_path = os.path.join(self.dir, "qt-config.ini")
        self.game_path = os.path.join(self.dir, "custom", self.TITLE + ".ini")
        with open(self.global_path, "w", newline="", encoding="utf-8") as f:
            f.write(GLOBAL_TEXT)
        with open(self.game_path, "w", newline="", encoding="utf-8") as f:
            f.write(GAME_TEXT)

    def read(self, path):
        with open(path, newline="", encoding="utf-8") as f:
            return f.read()

    def test_state_lists_the_game_files_and_the_values(self):
        state = ini.get_state(self.dir, self.TITLE, running=False)
        self.assertEqual([t["id"] for t in state["titles"]], [self.TITLE])
        by_key = {s["key"]: s for s in state["settings"]}
        self.assertEqual(by_key["frame_gen"]["selected"], "true")
        self.assertEqual(by_key["resolution_setup"]["selected"], "inherit")
        self.assertEqual(by_key["resolution_setup"]["effective"], "3")
        self.assertEqual(by_key["use_docked_mode"]["effective"], "1")
        self.assertEqual(state["dma"], "2")

    def test_a_game_name_from_a_loose_dump_does_not_hide_a_known_name(self):
        # A loose dump logs "Loading Unknown program (<title>) ...".
        titles = ini.list_titles(self.dir, (self.TITLE, "Unknown program"))
        self.assertEqual(titles, [{"id": self.TITLE, "name": "Donkey Kong Bananza"}])

    def test_a_new_game_takes_the_name_in_the_log_or_else_its_title_id(self):
        other = "0100000000000001"
        with open(os.path.join(self.dir, "custom", other + ".ini"), "w", encoding="utf-8") as f:
            f.write(GAME_TEXT)
        names = {t["id"]: t["name"] for t in ini.list_titles(self.dir, (other, "Some Game"))}
        self.assertEqual(names[other], "Some Game")
        names = {t["id"]: t["name"] for t in ini.list_titles(self.dir, (other, "Unknown program"))}
        self.assertEqual(names[other], other)

    def test_state_keeps_an_unknown_value_as_an_option(self):
        with open(self.global_path, "w", encoding="utf-8") as f:
            f.write("[Renderer]\nscaling_filter\\default=false\nscaling_filter=99\n")
        state = ini.get_state(self.dir, "global", running=False)
        setting = next(s for s in state["settings"] if s["key"] == "scaling_filter")
        self.assertEqual(setting["selected"], "99")
        self.assertIn("99", [o["value"] for o in setting["options"]])

    def test_a_game_change_writes_only_the_game_file(self):
        ini.apply_changes(self.dir, self.TITLE, {"resolution_setup": "1"}, running=False)
        self.assertIn("resolution_setup\\use_global=false\n", self.read(self.game_path))
        self.assertEqual(self.read(self.global_path), GLOBAL_TEXT)

    def test_a_game_change_is_allowed_while_the_emulator_runs(self):
        # Only the boot and the per-game dialog write this file.
        ini.apply_changes(self.dir, self.TITLE, {"resolution_setup": "1"}, running=True)
        self.assertIn("resolution_setup=1\n", self.read(self.game_path))

    def test_a_global_change_is_refused_while_the_emulator_runs(self):
        # The emulator saves its memory copy over this file at the next boot or exit.
        with self.assertRaises(ini.Refused):
            ini.apply_changes(self.dir, "global", {"resolution_setup": "1"}, running=True)
        self.assertEqual(self.read(self.global_path), GLOBAL_TEXT)

    def test_many_changes_write_one_backup_and_all_values(self):
        changes = {"resolution_setup": "2", "use_docked_mode": "0", "frame_gen": "true"}
        ini.apply_changes(self.dir, "global", changes, running=False)
        text = self.read(self.global_path)
        self.assertIn("resolution_setup=2\n", text)
        self.assertIn("frame_gen=true\n", text)
        self.assertIn("[System]\nuse_docked_mode\\default=false\nuse_docked_mode=0\n", text)
        self.assertEqual(self.read(self.global_path + ini.BACKUP_SUFFIX), GLOBAL_TEXT)

    def test_bad_requests_change_nothing(self):
        bad = [
            ("global", {"secret_key": "1"}),
            ("global", {"resolution_setup": "99"}),
            ("global", {"resolution_setup": "1\nevil=1"}),
            ("../../etc/passwd", {"resolution_setup": "1"}),
            ("040074a01bf12000", {"resolution_setup": "1"}),
            ("0400000000000001", {"resolution_setup": "1"}),
        ]
        for scope, changes in bad:
            with self.subTest(scope=scope, changes=changes):
                with self.assertRaises(ini.Refused):
                    ini.apply_changes(self.dir, scope, changes, running=False)
        self.assertEqual(self.read(self.global_path), GLOBAL_TEXT)
        self.assertEqual(self.read(self.game_path), GAME_TEXT)

    def test_no_preset_selects_gpu_accurate(self):
        # GPU High with asynchronous GPU gave a black 3D view in Bananza.
        for preset in ini.PRESETS:
            self.assertNotEqual(preset["values"].get("gpu_accuracy"), "1", preset["id"])

    def test_every_preset_can_be_applied(self):
        for preset in ini.PRESETS:
            ini.apply_preset(self.dir, "global", preset["id"], running=False)
            text = self.read(self.global_path)
            for key, value in preset["values"].items():
                self.assertIn(f"\n{key}={value}\n", text)


class Log(unittest.TestCase):
    LOG = (
        "[  87.6] Config <Info> common/settings.cpp:138:LogSettings: -- Renderer.frame_gen: false\n"
        "[  95.1] Core <Info> core/core.cpp:378:Load: Loading Mario Kart World (0400C3F00006E000) ...\n"
        "[ 120.0] Core <Info> core/core.cpp:378:Load: Loading Donkey Kong Bananza (040074A01BF12000) ...\n"
    )

    def test_the_last_loaded_game_wins(self):
        self.assertEqual(ini.last_loaded_title(self.LOG), ("040074A01BF12000", "Donkey Kong Bananza"))

    def test_a_log_with_no_game_gives_none(self):
        self.assertIsNone(ini.last_loaded_title("[ 0.1] Config <Info> nothing\n"))


class Process(unittest.TestCase):
    def test_the_emulator_binary_matches(self):
        self.assertTrue(ini.is_emulator_exe("/tmp/.mount_eglantABC/usr/bin/eglantine"))
        self.assertTrue(ini.is_emulator_exe("/tmp/.mount_eglantABC/usr/bin/eglantine (deleted)"))

    def test_other_programs_do_not_match(self):
        self.assertFalse(ini.is_emulator_exe("/home/deck/homebrew/services/PluginLoader"))
        self.assertFalse(ini.is_emulator_exe("/usr/bin/python3"))
        self.assertFalse(ini.is_emulator_exe("/home/deck/Applications/eglantine-build27.AppImage"))


if __name__ == "__main__":
    unittest.main()
