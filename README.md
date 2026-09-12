# flake8-import-type

`flake8-import-type` ports Ruff rule `RUF105` to Flake8. It reports direct
imports that are later used as functions, types in annotations, or class
bases:

```python
from pathlib import Path

path = Path("file.txt")
```

This produces:

```text
example.py:1:21: RUF105 Importing type/function `Path` from module `pathlib`.
```

Import the module instead:

```python
import pathlib

path = pathlib.Path("file.txt")
```

Install the package into the same environment as Flake8, then run Flake8 as
usual:

```shell
python -m pip install flake8 flake8-import-type
flake8 --select RUF105 path/to/code
```

Imports from `typing`, `typing_extensions`, `collections.abc`, `six.moves`,
and `__future__` are exempt, matching the original Ruff implementation.
