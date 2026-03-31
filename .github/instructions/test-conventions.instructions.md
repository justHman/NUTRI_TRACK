---
applyTo: "tests/*.py"
---

# Test Conventions — NutriTrack

## Structure

Every test file in `tests/` must follow this layout:

```
1. Module docstring (title + one-line description of what is tested)
2. sys.path setup so `project_root` (app/) is importable
3. from config.logging_config import get_logger; logger = get_logger(__name__)
4. One private function per test case: _test_<case>() → list[tuple]
5. One public run_all() function that calls every case and prints grouped results
```

## Logging

- Every test file **must** declare `logger = get_logger(__name__)` at module level.
- Use `logger.error("…", exc_info=True)` inside individual test functions on unexpected exceptions.
- Use `logger.info("run_all …: %d/%d groups passed")` at the end of `run_all()`.
- Do **not** call `logger.title()` in test files — use `print()` for section headers.

## Console Silencing

`run_all()` must silence INFO/DEBUG console output from other modules while tests run,
then restore it afterwards, so only test result lines are visible in notebooks:

```python
from utils.test_helpers import silence_console, restore_console

<!-- utils.test_helpers -->
def silence_console():
    root = _stdlib_logging.getLogger()
    saved = []
    for h in root.handlers:
        if isinstance(h, _stdlib_logging.StreamHandler) and not isinstance(h, _stdlib_logging.FileHandler):
            saved.append((h, h.level))
            h.setLevel(_stdlib_logging.WARNING)
    return saved

def restore_console(saved):
    for h, level in saved:
        h.setLevel(level)
```

Wrap the body of `run_all()`:
```python
def run_all(...):
    _saved = silence_console()
    try:
        ...
    finally:
        restore_console(_saved)
```

**Exception:** WARNING-level log lines from the module under test are intentionally visible —
they document expected edge-case behavior (e.g., "invalid barcode", "falling back to mock").

## Test Case Functions

Each `_test_<case>()` function returns a `list[tuple]`:

```python
(ok: bool, label: str, detail: str)
```

- `ok=True` → passed, `ok=False` → failed, `ok=None` → skipped (e.g., resource missing).
- `label` is a short noun phrase describing the case (e.g., `'chicken breast'`, `'L1 cache hit'`).
- `detail` is a compact key=value summary of actual output (e.g., `"cal=165.0  pro=31.0"`).

## Output Format

Print groups with this exact pattern:

```
─── <Module> Tests ────────────────────────────────────────────────────

  ─────[GROUP NAME]─────
    1. <label>: <detail> (✅)
    2. <label>: <detail> (❌)
    2/2 passed ✅

  ─────[ANOTHER GROUP]─────
    ...

───────────────────────────────────────────────────────────────────────
  N/M passed ✅
```

Rules:
- Use `✅` for each passed case, `❌` for each failed case, `SKIP` (text) for skipped (`ok is None`).
- The header line uses `─── … ───` dashes (not `===`).
- Group tags use `─────[TAG]─────`.
- The summary line shows `{passed}/{total} passed ✅/❌`.
- Always call `print(..., flush=True)` to avoid buffering in notebooks.

## run_all() Return Value

`run_all()` must return a list that can be checked by `test_all.ipynb`:

- For **client tests** (one result per test case): return `list[bool]` — one bool per group
  (`True` = all cases in the group passed, `False` = at least one failed).
- For **API/pipeline tests** (result dicts): return `list[dict]` where each dict has a `"success"` key.

## Example Skeleton

```python
"""
Tests for FooBar Client
=======================
Tests the FooBar API client: lookup, cache, normalization.
"""

import os, sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import logging as _stdlib_logging
from config.logging_config import get_logger
from utils.test_helpers import silence_console, restore_console
logger = get_logger(__name__)

def _test_something(client) -> list:
    try:
        result = client.do_thing("input")
        assert result.get("found") is True
        return [(True, "'input'", f"val={result.get('value')}")]
    except Exception as e:
        logger.error("_test_something failed: %s", e, exc_info=True)
        return [(False, "'input'", str(e))]


def run_all(client) -> list:
    _saved = silence_console()
    try:
        group_results = []
        print("\n─── FooBar Client Tests ───────────────────────────────────────────────", flush=True)

        def _print_group(tag, cases):
            print(f"\n  ─────[{tag}]─────", flush=True)
            for i, (ok, label, detail) in enumerate(cases, 1):
                icon = "SKIP" if ok is None else ("✅" if ok else "❌")
                print(f"    {i}. {label}: {detail} ({icon})", flush=True)
            passed = sum(1 for ok, _, _ in cases if ok is True)
            total = len(cases)
            s_icon = "✅" if passed == total else "❌"
            print(f"    {passed}/{total} passed {s_icon}", flush=True)
            return all(ok is True or ok is None for ok, _, _ in cases)

        group_results.append(_print_group("SOMETHING TEST", _test_something(client)))

        passed = sum(group_results)
        total  = len(group_results)
        print(f"\n───────────────────────────────────────────────────────────────────────", flush=True)
        print(f"  {passed}/{total} groups passed {'✅' if passed == total else '❌'}\n", flush=True)
        logger.info("run_all foobar tests: %d/%d groups passed", passed, total)
        return group_results
    finally:
        restore_console(_saved)
```
