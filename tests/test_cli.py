import subprocess
import sys

from pydantic_tagged_dc import __version__


def test_cli_version():
    cmd = [sys.executable, "-m", "pydantic_tagged_dc", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__
