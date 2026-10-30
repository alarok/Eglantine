import argparse
import subprocess
import sys


ROOT_DOCUMENTS = {
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
}
DOCUMENT_EXTENSIONS = {".md", ".markdown", ".rst"}


def changed_paths(base, head, cwd=None):
    if not isinstance(base, str) or not base or not isinstance(head, str) or not head:
        raise ValueError("Base and head commits are required")

    result = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", "-z", base, head],
        cwd=cwd,
        check=True,
        capture_output=True,
    )
    raw_paths = result.stdout
    if not raw_paths or not raw_paths.endswith(b"\0"):
        raise ValueError("Git returned an empty or malformed path list")

    try:
        paths = [path.decode("utf-8") for path in raw_paths[:-1].split(b"\0")]
    except UnicodeDecodeError as error:
        raise ValueError("Git returned a path that is not valid UTF-8") from error
    return paths


def is_docs_or_ci_path(path):
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        raise ValueError("Git returned a malformed repository path")
    if path.startswith("docs/") or path.startswith("tools/ci/") or path.startswith("tests/ci/"):
        return True
    if path.startswith(".github/workflows/"):
        return path.endswith((".yml", ".yaml"))
    return path in ROOT_DOCUMENTS or path.rsplit("/", 1)[-1].lower().endswith(tuple(DOCUMENT_EXTENSIONS))


def requires_full_build(paths):
    if not paths:
        raise ValueError("Git reported no changed paths")
    return any(not is_docs_or_ci_path(path) for path in paths)


def main():
    parser = argparse.ArgumentParser(description="Classify a pull request for emulator builds.")
    parser.add_argument("base", help="Base commit SHA")
    parser.add_argument("head", help="Head commit SHA")
    arguments = parser.parse_args()

    try:
        full_build = requires_full_build(changed_paths(arguments.base, arguments.head))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Cannot classify pull request changes: {error}", file=sys.stderr)
        return 1

    print(f"full_build={'true' if full_build else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
