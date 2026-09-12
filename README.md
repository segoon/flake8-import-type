# flake8-import-type

[![CI](https://github.com/segoon/flake8-import-type/actions/workflows/ci.yml/badge.svg)](https://github.com/segoon/flake8-import-type/actions/workflows/ci.yml)

`flake8-import-type` is a Flake8 plugin that encourages importing modules
instead of importing the types and functions used from them. Module-qualified
names make the origin of a symbol visible at its use site and reduce ambiguity
when several modules expose similarly named objects.

## Installation

Install the plugin into the same environment as Flake8:

```shell
python -m pip install flake8 flake8-import-type
```

The plugin is enabled automatically. If your Flake8 configuration uses
`select`, include `IMT` or `IMT001`:

```shell
flake8 --select IMT path/to/code
```

## Rule

### IMT001: directly imported type or function

This code reports `IMT001` at the imported name:

```python
from pathlib import Path

path = Path("file.txt")
```

```text
example.py:1:21: IMT001 Importing type/function `Path` from module `pathlib`.
```

Import and qualify the module instead:

```python
import pathlib

path = pathlib.Path("file.txt")
```

The plugin reports a `from ... import ...` binding when it is subsequently
used as:

- a direct callable, including a decorator;
- a type in an annotation or explicit string annotation;
- a class base, including a subscripted base;
- a metaclass;
- the value of a Python 3.12 `type` alias.

Each imported binding produces at most one diagnostic. Aliases are shown by
their local name:

```python
from pathlib import Path as FilePath

path = FilePath("file.txt")  # IMT001 is reported at `FilePath` in the import
```

Imports from the following modules are exempt:

- `__future__`
- `collections.abc`
- `six.moves`
- `typing`
- `typing_extensions`

Suppress an intentional direct import with a normal Flake8 suppression:

```python
from package import Factory  # noqa: IMT001

Factory()
```

## Compatibility and limitations

`flake8-import-type` supports Python 3.9 through 3.14 and Flake8 7.0 or newer.

The check is syntactic and processes bindings in source order. It does not
perform control-flow or runtime type inference, so it cannot determine whether
a conditional import executes or whether an imported object is actually a
class or function. Legacy `# type:` comments are not checked because the AST
provided by Flake8 does not retain them.

## Development

The project uses [uv](https://docs.astral.sh/uv/):

```shell
uv sync --dev
uv run pytest
uv run ruff check .
uv build
uv run twine check dist/*
```

CI runs the tests on every supported Python version, verifies the minimum
Flake8 version, and validates the distributions.

## Releasing

1. Update the version in `pyproject.toml` and merge the change.
2. Publish a GitHub Release whose tag is exactly `v<version>`, such as
   `v0.1.0`.
3. Approve the protected `pypi` environment deployment.

The release workflow checks the tag, builds and validates the distributions,
and publishes them through PyPI Trusted Publishing. No PyPI API token is
stored in GitHub.

## License

This project is distributed under the [MIT License](LICENSE).
