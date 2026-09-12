from __future__ import annotations

import ast
import subprocess
import sys
import textwrap

import pytest

from flake8_import_type import ImportTypeChecker


def check(source: str) -> list[tuple[int, int, str]]:
    source = textwrap.dedent(source)
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    return [result[:3] for result in ImportTypeChecker(tree, lines).run()]


def error(line: int, column: int, name: str, module: str) -> tuple[int, int, str]:
    return (
        line,
        column,
        f"IMT001 Importing type/function `{name}` from module `{module}`.",
    )


def test_reports_calls_annotations_and_class_contexts() -> None:
    assert check(
        """
        from pathlib import Path
        from os import dup as duplicate
        from subprocess import CompletedProcess
        from package import Arg, Base, Decorator, Forward, Meta

        path = Path("file.txt")
        fd = duplicate(0)

        def assert_success(cp: list[CompletedProcess], other: "Forward") -> None:
            pass

        @Decorator
        class Child(Base[Arg], metaclass=Meta):
            pass
        """
    ) == [
        error(2, 20, "Path", "pathlib"),
        error(3, 15, "duplicate", "os"),
        error(4, 23, "CompletedProcess", "subprocess"),
        error(5, 20, "Arg", "package"),
        error(5, 25, "Base", "package"),
        error(5, 31, "Decorator", "package"),
        error(5, 42, "Forward", "package"),
        error(5, 51, "Meta", "package"),
    ]


def test_reports_each_import_only_once() -> None:
    assert check(
        """
        from pathlib import Path

        first = Path("first")
        second = Path("second")
        values: list[Path]
        """
    ) == [error(2, 20, "Path", "pathlib")]


def test_ignores_literal_values_and_annotated_metadata() -> None:
    assert (
        check(
            """
            from package import metadata, status
            from typing import Annotated, Literal

            state: Literal["status"]
            value: Annotated[int, "metadata"]
            """
        )
        == []
    )


def test_rebinding_stops_tracking_an_import() -> None:
    assert (
        check(
            """
            from package import Factory
            Factory = lambda: None
            Factory()

            from package import LoopFactory
            for LoopFactory in factories:
                LoopFactory()

            from package import ContextFactory
            with manager() as ContextFactory:
                ContextFactory()
            """
        )
        == []
    )


def test_function_bindings_are_lexically_scoped() -> None:
    assert check(
        """
        from package import OuterFactory

        def uses_outer():
            OuterFactory()

        def shadows_outer(OuterFactory):
            OuterFactory()

        def imports_inner():
            from package import InnerFactory
            InnerFactory()

        InnerFactory()
        """
    ) == [
        error(2, 20, "OuterFactory", "package"),
        error(11, 24, "InnerFactory", "package"),
    ]


def test_function_local_binding_shadows_outer_for_the_whole_scope() -> None:
    assert (
        check(
            """
            from package import Factory

            def function():
                Factory()
                Factory = lambda: None
            """
        )
        == []
    )


def test_class_bindings_do_not_leak_into_methods() -> None:
    assert check(
        """
        from package import Factory

        class Namespace:
            Factory = lambda: None

            def method(self):
                Factory()
        """
    ) == [error(2, 20, "Factory", "package")]


def test_comprehension_targets_shadow_imports() -> None:
    assert check(
        """
        from package import Factory
        from package import Source

        values = [Factory() for Factory in factories]
        other = [item for item in Source()]
        """
    ) == [error(3, 20, "Source", "package")]


def test_ignores_modules_unused_symbols_wildcards_and_exempt_modules() -> None:
    assert (
        check(
            """
            import stat
            from package import *
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
    ) == [error(3, 28, "after", "package")]


def test_relative_import_keeps_the_import_level() -> None:
    assert check(
        """
        from ..package import Factory
        Factory()
        """
    ) == [error(2, 22, "Factory", "..package")]


def test_import_location_without_alias_positions() -> None:
    source = "from package import (\n    First,\n    Second as Alias,\n)\nAlias()\n"
    tree = ast.parse(source)
    import_node = tree.body[0]
    assert isinstance(import_node, ast.ImportFrom)
    for alias in import_node.names:
        del alias.lineno
        del alias.col_offset

    results = ImportTypeChecker(tree, source.splitlines(keepends=True)).run()

    assert [result[:3] for result in results] == [error(3, 4, "Alias", "package")]


@pytest.mark.skipif(sys.version_info < (3, 12), reason="requires Python 3.12")
def test_type_alias() -> None:
    assert check(
        """
        from package import Item
        type Items = list[Item]
        """
    ) == [error(2, 20, "Item", "package")]


def test_flake8_discovers_plugin() -> None:
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


def test_plugin_version_comes_from_package_metadata() -> None:
    assert ImportTypeChecker.version == "0.1.0"
