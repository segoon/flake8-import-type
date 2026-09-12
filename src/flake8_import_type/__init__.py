from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import Any

__version__ = "0.1.0"

_EXEMPT_MODULES = frozenset(
    {
        "__future__",
        "collections.abc",
        "six.moves",
        "typing",
        "typing_extensions",
    }
)


class _ImportTypeVisitor(ast.NodeVisitor):
    def __init__(self, tree: ast.AST) -> None:
        self._imports: dict[str, tuple[str, ast.alias]] = {}
        self._annotation_names = self._collect_annotation_names(tree)
        self.errors: list[tuple[int, int, str]] = []

    @staticmethod
    def _collect_annotation_names(tree: ast.AST) -> set[int]:
        roots: list[ast.expr] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.arg) and node.annotation is not None:
                roots.append(node.annotation)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.returns is not None:
                    roots.append(node.returns)
            elif isinstance(node, ast.AnnAssign):
                roots.append(node.annotation)

        return {
            id(node)
            for root in roots
            for node in ast.walk(root)
            if isinstance(node, ast.Name)
        }

    def _check_symbol(self, name: str) -> None:
        imported = self._imports.get(name)
        if imported is None:
            return

        module, alias = imported
        if module in _EXEMPT_MODULES:
            return

        self.errors.append(
            (
                alias.lineno,
                alias.col_offset,
                f"RUF105 Importing type/function `{name}` from module `{module}`.",
            )
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.generic_visit(node)

        module = node.module or "."
        for alias in node.names:
            self._imports[alias.asname or alias.name] = (module, alias)

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name):
            self._check_symbol(node.func.id)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.generic_visit(node)
        for base in node.bases:
            if isinstance(base, ast.Name):
                self._check_symbol(base.id)

    def visit_Name(self, node: ast.Name) -> None:
        if id(node) in self._annotation_names:
            self._check_symbol(node.id)


class ImportTypeChecker:
    name = "flake8-import-type"
    version = __version__

    def __init__(self, tree: ast.AST) -> None:
        self._tree = tree

    def run(self) -> Iterator[tuple[int, int, str, type[Any]]]:
        visitor = _ImportTypeVisitor(self._tree)
        visitor.visit(self._tree)
        for line, column, message in visitor.errors:
            yield line, column, message, type(self)
