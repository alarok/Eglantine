import pathlib
import subprocess
import tempfile
import unittest

from tools.ci.classify_pr_changes import changed_paths, requires_full_build


class ClassifyPrChangesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "CI test")
        self.git("config", "user.email", "ci@example.invalid")
        self.write("src/old.cpp", "int old_source;\n")
        self.base = self.commit()

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *arguments):
        return subprocess.run(
            ["git", *arguments], cwd=self.repo, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "-q", "-m", "test fixture")
        return self.git("rev-parse", "HEAD")

    def classify_head(self):
        head = self.commit()
        return requires_full_build(changed_paths(self.base, head, cwd=self.repo))

    def test_documentation_workflow_and_ci_tests_skip_emulator_builds(self):
        self.write("docs/Notes for testers.md", "Updated help.\n")
        self.write(".github/workflows/sync.yml", "name: sync\n")
        self.write("tools/ci/helper.py", "print('check')\n")
        self.write("tests/ci/test_helper.py", "def test_check(): pass\n")
        self.write("tools/nx2/upstream_sync.md", "Upstream sync guide.\n")
        self.write("README.md", "Updated overview.\n")

        self.assertFalse(self.classify_head())

    def test_mixed_documentation_and_source_changes_run_emulator_builds(self):
        self.write("docs/rendering.md", "Updated help.\n")
        self.write("src/renderer.cpp", "int renderer;\n")

        self.assertTrue(self.classify_head())

    def test_build_files_run_emulator_builds(self):
        for path in ("CMakeLists.txt", "cpmfile.json", "unknown.build-config"):
            with self.subTest(path=path):
                self.git("reset", "--hard", self.base)
                self.git("clean", "-fdq")
                self.write(path, "changed\n")
                self.assertTrue(self.classify_head())

    def test_release_workflow_runs_the_builds_it_defines(self):
        self.write(".github/workflows/release-binaries.yml", "name: release\n")

        self.assertTrue(self.classify_head())

    def test_deleted_source_path_runs_emulator_builds(self):
        (self.repo / "src/old.cpp").unlink()

        changed = changed_paths(self.base, self.commit(), cwd=self.repo)

        self.assertEqual(changed, ["src/old.cpp"])
        self.assertTrue(requires_full_build(changed))

    def test_rename_from_source_into_docs_keeps_both_paths(self):
        (self.repo / "src/old.cpp").unlink()
        self.write("docs/old.cpp", "int old_source;\n")

        changed = changed_paths(self.base, self.commit(), cwd=self.repo)

        self.assertEqual(changed, ["docs/old.cpp", "src/old.cpp"])
        self.assertTrue(requires_full_build(changed))

    def test_empty_and_malformed_classifications_fail(self):
        with self.assertRaises(ValueError):
            requires_full_build([])
        with self.assertRaises(ValueError):
            requires_full_build([""])
        with self.assertRaises(ValueError):
            changed_paths(self.base, self.base, cwd=self.repo)


if __name__ == "__main__":
    unittest.main()
