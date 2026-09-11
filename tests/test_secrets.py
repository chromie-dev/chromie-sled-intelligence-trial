"""Credentials must not escape `.env`.

SECURITY.md: never in git, fixtures, logs, screenshots, generated outputs under `build/`,
or the source registry. This asserts it mechanically rather than trusting review.

These tests never print a secret. A failure names the variable and the file it leaked
into, because printing the value to make the message friendlier would put it in CI logs --
which is the same leak the test exists to prevent.
"""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
# Anything shorter is not distinctive enough to search for -- a two-character value would
# match half the repo and the failures would be noise.
MIN_SECRET_LEN = 12
SEARCHED = ("build", "tests/fixtures", "data/examples", "sources", "docs", "contracts")


def env_secrets() -> dict[str, str]:
    """Variable name -> value, for values long enough to search for. Empty if no .env."""
    if not ENV.exists():
        return {}
    out = {}
    for line in ENV.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if len(value) >= MIN_SECRET_LEN:
            out[name.strip()] = value
    return out


def searchable_files():
    for rel in SEARCHED:
        base = ROOT / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                yield path


class EnvHygieneTests(unittest.TestCase):
    def test_dotenv_is_ignored_by_git(self) -> None:
        result = subprocess.run(["git", "check-ignore", ".env"], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, ".env is not gitignored")

    def test_dotenv_is_not_tracked(self) -> None:
        tracked = subprocess.run(["git", "ls-files", ".env"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.strip()
        self.assertEqual(tracked, "", ".env is committed")

    def test_the_example_file_carries_names_but_no_values(self) -> None:
        # A placeholder value is worse than an empty one: it gets committed, looks real,
        # and for an LLM provider key it produces a misleading "API key not valid".
        for line in (ROOT / ".env.example").read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, _, value = line.partition("=")
            self.assertEqual(value.strip(), "", f"{name} has a value in .env.example")


class LeakTests(unittest.TestCase):
    """Nothing that is in .env may appear anywhere we generate or commit."""

    def setUp(self) -> None:
        self.secrets = env_secrets()

    def test_no_secret_value_appears_in_generated_or_committed_files(self) -> None:
        if not self.secrets:
            self.skipTest("no .env on this machine; nothing to leak")
        leaks = []
        for path in searchable_files():
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            for name, value in self.secrets.items():
                if value in text:
                    leaks.append(f"{name} -> {path.relative_to(ROOT)}")
        self.assertEqual(leaks, [], f"credential leaked into: {leaks}")

    def test_no_secret_value_is_tracked_by_git(self) -> None:
        if not self.secrets:
            self.skipTest("no .env on this machine; nothing to leak")
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.split()
        leaks = []
        for rel in tracked:
            path = ROOT / rel
            if not path.is_file():
                continue
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            for name, value in self.secrets.items():
                if value in text:
                    leaks.append(f"{name} -> {rel}")
        self.assertEqual(leaks, [], f"credential leaked into: {leaks}")

    def test_a_planted_secret_would_actually_be_found(self) -> None:
        # Guards the guard: if `searchable_files` ever stops walking anything, the two
        # tests above pass vacuously and the check silently stops protecting us.
        planted = ROOT / "build" / ".secret_probe"
        planted.parent.mkdir(exist_ok=True)
        token = "probe-" + "x" * MIN_SECRET_LEN
        planted.write_text(token)
        try:
            found = any(token in p.read_text(errors="ignore")
                        for p in searchable_files() if p.is_file())
        finally:
            planted.unlink()
        self.assertTrue(found, "the leak scan is not reading build/; it proves nothing")


if __name__ == "__main__":
    unittest.main()
