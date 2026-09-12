from __future__ import annotations

import ast
import tokenize
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from importlib.metadata import version
from io import StringIO
from typing import Any

_PACKAGE_NAME = "flake8-import-type"
_ERROR_CODE = "IMT001"

_EXEMPT_MODULES = frozenset(
    {
        "__future__",
        "collections.abc",
        "six.moves",
        "typing",
        "typing_extensions",
    }
)

_FUNCTION_SCOPES = frozenset({"comprehension", "function", "lambda"})


@dataclass
class _ImportBinding:
    module: str
    line: int
    column: int
    name: str
    reported: bool = False


@dataclass
class _Scope:
    kind: str
    parent: _Scope | None
    bindings: dict[str, _ImportBinding | None] = field(default_factory=dict)
    globals: set[str] = field(default_factory=set)
    nonlocals: set[str] = field(default_factory=set)


class _LocalBindingCollector(ast.NodeVisitor):
    """Collect names whose binding belongs to one lexical scope."""

    def __init__(self) -> None:
        self.names: set[str] = set()
        self.globals: set[str] = set()
        self.nonlocals: set[str] = set()

    def _collect_target(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self.names.add(node.id)
        elif isinstance(node, (ast.List, ast.Tuple)):
            for element in node.elts:
                self._collect_target(element)
        elif isinstance(node, ast.Starred):
            self._collect_target(node.value)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._collect_target(target)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._collect_target(node.target)
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._collect_target(node.target)
        self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._collect_target(node.target)
        self.visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        self._collect_target(node.target)
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._collect_target(item.optional_vars)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.names.add(alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_ListComp(self, node: ast.ListComp) -> None:
        pass

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_Global(self, node: ast.Global) -> None:
        self.globals.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.nonlocals.update(node.names)


class _ImportTypeVisitor(ast.NodeVisitor):
    def __init__(self, lines: list[str] | None = None) -> None:
        self._scope = _Scope(kind="module", parent=None)
        self._tokens = self._tokenize(lines)
        self.errors: list[tuple[int, int, str]] = []

    @staticmethod
    def _tokenize(lines: list[str] | None) -> list[tokenize.TokenInfo]:
        if lines is None:
            return []
        try:
            return list(tokenize.generate_tokens(StringIO("".join(lines)).readline))
        except tokenize.TokenError:
            return []

    @staticmethod
    def _arguments(arguments: ast.arguments) -> Iterable[ast.arg]:
        yield from arguments.posonlyargs
        yield from arguments.args
        if arguments.vararg is not None:
            yield arguments.vararg
        yield from arguments.kwonlyargs
        if arguments.kwarg is not None:
            yield arguments.kwarg

    @staticmethod
    def _target_names(node: ast.AST) -> Iterator[str]:
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, (ast.List, ast.Tuple)):
            for element in node.elts:
                yield from _ImportTypeVisitor._target_names(element)
        elif isinstance(node, ast.Starred):
            yield from _ImportTypeVisitor._target_names(node.value)

    def _module_scope(self) -> _Scope:
        scope = self._scope
        while scope.parent is not None:
            scope = scope.parent
        return scope

    def _nonlocal_scope(self, name: str) -> _Scope:
        scope = self._scope.parent
        while scope is not None:
            if scope.kind in _FUNCTION_SCOPES and name in scope.bindings:
                return scope
            scope = scope.parent
        return self._module_scope()

    def _binding_scope(self, name: str) -> _Scope:
        if name in self._scope.globals:
            return self._module_scope()
        if name in self._scope.nonlocals:
            return self._nonlocal_scope(name)
        return self._scope

    def _bind(self, name: str, binding: _ImportBinding | None = None) -> None:
        self._binding_scope(name).bindings[name] = binding

    def _resolve(self, name: str) -> _ImportBinding | None:
        if name in self._scope.globals:
            return self._module_scope().bindings.get(name)
        if name in self._scope.nonlocals:
            return self._nonlocal_scope(name).bindings.get(name)

        scope: _Scope | None = self._scope
        skip_class_scopes = self._scope.kind in _FUNCTION_SCOPES
        while scope is not None:
            if not (skip_class_scopes and scope.kind == "class"):
                if name in scope.bindings:
                    return scope.bindings[name]
            scope = scope.parent
        return None

    def _check_name(self, name: str) -> None:
        imported = self._resolve(name)
        if imported is None or imported.reported or imported.module in _EXEMPT_MODULES:
            return

        imported.reported = True
        self.errors.append(
            (
                imported.line,
                imported.column,
                f"{_ERROR_CODE} Importing type/function `{imported.name}` "
                f"from module `{imported.module}`.",
            )
        )

    def _import_positions(self, node: ast.ImportFrom) -> list[tuple[int, int]]:
        positions = [(node.lineno, node.col_offset)] * len(node.names)
        if all(hasattr(alias, "lineno") for alias in node.names):
            return [(alias.lineno, alias.col_offset) for alias in node.names]
        if not self._tokens:
            return positions

        after_import = False
        alias_index = 0
        skip_asname: str | None = None
        for current in self._tokens:
            if current.start < (node.lineno, node.col_offset):
                continue
            if not after_import:
                if current.type == tokenize.NAME and current.string == "import":
                    after_import = True
                continue
            if alias_index >= len(node.names):
                break
            if skip_asname is not None:
                if current.type == tokenize.NAME and current.string == skip_asname:
                    skip_asname = None
                continue

            alias = node.names[alias_index]
            matches_name = (
                current.type == tokenize.NAME and current.string == alias.name
            )
            matches_star = (
                current.type == tokenize.OP and current.string == alias.name == "*"
            )
            if matches_name or matches_star:
                positions[alias_index] = current.start
                alias_index += 1
                skip_asname = alias.asname

        return positions

    @staticmethod
    def _subscript_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _check_type_expression(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self._check_name(node.id)
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                expression = ast.parse(node.value, mode="eval")
            except SyntaxError:
                return
            self._check_type_expression(expression)
            return
        if isinstance(node, ast.Subscript):
            self._check_type_expression(node.value)
            subscript_name = self._subscript_name(node.value)
            if subscript_name == "Literal":
                self.visit(node.slice)
                return
            if subscript_name == "Annotated" and isinstance(node.slice, ast.Tuple):
                self._check_type_expression(node.slice.elts[0])
                for metadata in node.slice.elts[1:]:
                    self.visit(metadata)
                return
            self._check_type_expression(node.slice)
            return

        for child in ast.iter_child_nodes(node):
            self._check_type_expression(child)

    def _check_decorator(self, node: ast.expr) -> None:
        if isinstance(node, ast.Name):
            self._check_name(node.id)
        self.visit(node)

    def _visit_target(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self._bind(node.id)
        elif isinstance(node, (ast.List, ast.Tuple)):
            for element in node.elts:
                self._visit_target(element)
        elif isinstance(node, ast.Starred):
            self._visit_target(node.value)
        elif isinstance(node, ast.Attribute):
            self.visit(node.value)
        elif isinstance(node, ast.Subscript):
            self.visit(node.value)
            self.visit(node.slice)

    def _enter_scope(
        self,
        kind: str,
        body: Iterable[ast.stmt],
        arguments: ast.arguments | None = None,
    ) -> None:
        collector = _LocalBindingCollector()
        for statement in body:
            collector.visit(statement)

        local_names = collector.names - collector.globals - collector.nonlocals
        scope = _Scope(
            kind=kind,
            parent=self._scope,
            bindings=dict.fromkeys(local_names),
            globals=collector.globals,
            nonlocals=collector.nonlocals,
        )
        if arguments is not None:
            scope.bindings.update(
                (argument.arg, None) for argument in self._arguments(arguments)
            )

        previous = self._scope
        self._scope = scope
        try:
            for statement in body:
                self.visit(statement)
        finally:
            self._scope = previous

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self._check_decorator(decorator)
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        for argument in self._arguments(node.args):
            if argument.annotation is not None:
                self._check_type_expression(argument.annotation)
        if node.returns is not None:
            self._check_type_expression(node.returns)
        for type_parameter in getattr(node, "type_params", ()):
            self._check_type_expression(type_parameter)

        self._bind(node.name)
        self._enter_scope("function", node.body, node.args)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)

        previous = self._scope
        self._scope = _Scope(kind="lambda", parent=previous)
        self._scope.bindings.update(
            (argument.arg, None) for argument in self._arguments(node.args)
        )
        try:
            self.visit(node.body)
        finally:
            self._scope = previous

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self._check_decorator(decorator)
        for base in node.bases:
            self._check_type_expression(base)
            self.visit(base)
        for keyword in node.keywords:
            if keyword.arg == "metaclass":
                self._check_type_expression(keyword.value)
            self.visit(keyword.value)
        for type_parameter in getattr(node, "type_params", ()):
            self._check_type_expression(type_parameter)

        self._bind(node.name)
        collector = _LocalBindingCollector()
        for statement in node.body:
            collector.visit(statement)
        previous = self._scope
        self._scope = _Scope(
            kind="class",
            parent=previous,
            globals=collector.globals,
            nonlocals=collector.nonlocals,
        )
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self._scope = previous

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._bind(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias, (line, column) in zip(node.names, self._import_positions(node)):
            if alias.name == "*":
                continue
            name = alias.asname or alias.name
            self._bind(
                name,
                _ImportBinding(module=module, line=line, column=column, name=name),
            )

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self._check_name(node.func.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_type_expression(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self._visit_target(node.target)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._visit_target(target)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.target)
        self.visit(node.value)
        self._visit_target(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        scope = self._scope
        while scope.kind == "comprehension" and scope.parent is not None:
            scope = scope.parent
        previous = self._scope
        self._scope = scope
        try:
            self._visit_target(node.target)
        finally:
            self._scope = previous

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        self._visit_target(node.target)
        for statement in (*node.body, *node.orelse):
            self.visit(statement)

    visit_AsyncFor = visit_For

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._visit_target(item.optional_vars)
        for statement in node.body:
            self.visit(statement)

    visit_AsyncWith = visit_With

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name is not None:
            self._bind(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._visit_target(target)

    def _visit_comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        first, *remaining = node.generators
        self.visit(first.iter)

        previous = self._scope
        self._scope = _Scope(kind="comprehension", parent=previous)
        try:
            for generator in node.generators:
                for name in self._target_names(generator.target):
                    self._scope.bindings[name] = None

            self._visit_target(first.target)
            for condition in first.ifs:
                self.visit(condition)
            for generator in remaining:
                self.visit(generator.iter)
                self._visit_target(generator.target)
                for condition in generator.ifs:
                    self.visit(condition)

            if isinstance(node, ast.DictComp):
                self.visit(node.key)
                self.visit(node.value)
            else:
                self.visit(node.elt)
        finally:
            self._scope = previous

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node)

    def visit_TypeAlias(self, node: ast.AST) -> None:
        self._check_type_expression(node.value)
        self._visit_target(node.name)


class ImportTypeChecker:
    name = _PACKAGE_NAME
    version = version(_PACKAGE_NAME)

    def __init__(self, tree: ast.AST, lines: list[str] | None = None) -> None:
        self._tree = tree
        self._lines = lines

    def run(self) -> Iterator[tuple[int, int, str, type[Any]]]:
        visitor = _ImportTypeVisitor(self._lines)
        visitor.visit(self._tree)
        for line, column, message in sorted(visitor.errors):
            yield line, column, message, type(self)
