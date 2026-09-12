from __future__ import annotations

import ast
import subprocess
import sys
import textwrap

from flake8_import_type import ImportTypeChecker


def check(source: str) -> list[tuple[int, int, str]]:
    tree = ast.parse(textwrap.dedent(source))
    return [result[:3] for result in ImportTypeChecker(tree).run()]


def test_reports_calls_annotations_and_class_bases() -> None:
    assert check(
        """
        from pathlib import Path
        from os import dup as duplicate
        from subprocess import CompletedProcess
        from argparse import ArgumentError

        path = Path("file.txt")
        fd = duplicate(0)

        def assert_success(cp: list[CompletedProcess]) -> None:
            pass

        class MyError(ArgumentError):
            pass
        """
    ) == [
        (2, 20, "RUF105 Importing type/function `Path` from module `pathlib`."),
        (3, 15, "RUF105 Importing type/function `duplicate` from module `os`."),
        (
            4,
            23,
            "RUF105 Importing type/function `CompletedProcess` "
            "from module `subprocess`.",
        ),
        (
            5,
            21,
            "RUF105 Importing type/function `ArgumentError` from module `argparse`.",
        ),
    ]


def test_ignores_modules_and_unused_symbols() -> None:
    assert (
        check(
            """
            import stat
            from collections.abc import Set
            from six.moves import reload_module
            from sys import exit
            from typing import Any
            from typing_extensions import get_origin

            stat.filemode(0o666)
            reload_module(stat)
            get_origin(Any)

            class MySet(Set):
                pass
            """
        )
        == []
    )


def test_reports_import_location_only_after_import_is_seen() -> None:
    assert check(
        """
        before()
        from package import before, after
        after()
        """
    ) == [
        (3, 28, "RUF105 Importing type/function `after` from module `package`."),
    ]


def test_relative_import() -> None:
    assert check(
        """
        from . import Factory
        Factory()
        """
    ) == [
        (2, 14, "RUF105 Importing type/function `Factory` from module `.`."),
    ]


def test_flake8_discovers_plugin() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "flake8", "--isolated", "--select", "RUF105", "-"],
        input="from pathlib import Path\nPath('file.txt')\n",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == (
        "stdin:1:21: RUF105 Importing type/function `Path` from module `pathlib`.\n"
    )
    assert result.stderr == ""
