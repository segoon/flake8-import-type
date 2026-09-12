from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version

assert version("flake8-import-type") == "0.1.0"

result = subprocess.run(
    [sys.executable, "-m", "flake8", "--isolated", "--select", "IMT001", "-"],
    input="from pathlib import Path\nPath('file.txt')\n",
    check=False,
    capture_output=True,
    text=True,
)

assert result.returncode == 1
assert result.stdout == (
    "stdin:1:21: IMT001 Importing type/function `Path` from module `pathlib`.\n"
)
assert result.stderr == ""
