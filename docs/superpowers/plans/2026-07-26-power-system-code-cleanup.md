# Power System Code Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the power-system implementation into focused modules while preserving every public API and generated output.

**Architecture:** Keep `packages.story_core.power_systems` as a compatibility facade. Move specification normalization and validation into `power_system_spec.py`, prompt projection into `power_system_prompt.py`, and the one-project migration payload into `scripts/p_gou_power_system_data.py`; templates and writing packets remain consumers with unchanged behavior.

**Tech Stack:** Python 3.11+, pytest, FastAPI/Pydantic integration tests, Git.

---

## File Structure

- Create `packages/story_core/power_system_spec.py`: canonical schema, bounded normalization, template-aware validation, and `PowerSystemValidationError`.
- Create `packages/story_core/power_system_prompt.py`: legacy summary redaction, stage/path selection, and bounded prompt projection.
- Modify `packages/story_core/power_systems.py`: small public compatibility facade only.
- Create `scripts/p_gou_power_system_data.py`: fixed `p-gou-webgame-restored` path definitions and validated power-system payload.
- Modify `scripts/upgrade_project_power_system.py`: migration orchestration and a compatibility wrapper around the extracted payload builder.
- Modify `tests/story_core/test_power_systems.py`: characterize facade ownership and unchanged outputs.
- Modify `tests/test_upgrade_project_power_system.py`: characterize extracted payload equivalence.

### Task 1: Lock the Compatibility Boundary

**Files:**
- Modify: `tests/story_core/test_power_systems.py`

- [ ] **Step 1: Add the failing specification-facade test**

Add these imports and this test to `tests/story_core/test_power_systems.py`:

```python
from packages.story_core import power_system_spec
from packages.story_core import power_systems as power_system_facade


def test_public_facade_reexports_specification_api() -> None:
    assert power_system_facade.PowerSystemValidationError is power_system_spec.PowerSystemValidationError
    assert power_system_facade.normalize_power_system_spec is power_system_spec.normalize_power_system_spec
    assert power_system_facade.validate_power_system_spec is power_system_spec.validate_power_system_spec
```

- [ ] **Step 2: Run the new tests and verify collection fails**

Run:

```powershell
pytest tests/story_core/test_power_systems.py -q
```

Expected: collection fails because `power_system_spec` does not exist yet.

- [ ] **Step 3: Commit the red tests**

```powershell
git add tests/story_core/test_power_systems.py
git commit -m "test: lock power system module boundaries"
```

### Task 2: Extract Specification Normalization and Validation

**Files:**
- Create: `packages/story_core/power_system_spec.py`
- Modify: `packages/story_core/power_systems.py`
- Test: `tests/story_core/test_power_systems.py`

- [ ] **Step 1: Create the specification module from the current implementation**

Move the following symbols and all constants used exclusively by them from `power_systems.py` into `power_system_spec.py` without changing their bodies:

```text
PowerSystemValidationError
_mapping_items
_mapping_get
_has_key
_text
_items
_text_list
_number
_normalize_record
normalize_power_system_spec
_selected_template
_required_sections
_minimum_path_count
_is_empty
_ledger_key
_ledger_covers
_inferred_stage_level
_is_level_twenty_second_transfer
_is_placeholder_content
_contains_placeholder_content
validate_power_system_spec
```

Keep their exact dependencies at the top of the new module:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from itertools import islice
import math
import re
from typing import Any

from packages.story_core.novel_type_ids import canonical_novel_type_id
from packages.story_core.power_system_templates import POWER_SYSTEM_TEMPLATES
```

Do not move money-redaction or prompt-budget constants into this module.

- [ ] **Step 2: Make the facade reexport the specification API**

Replace the moved definitions in `power_systems.py` with these imports while leaving the prompt implementation temporarily in place:

```python
from packages.story_core.power_system_spec import (
    PowerSystemValidationError,
    _text,
    normalize_power_system_spec,
    validate_power_system_spec,
)
```

The private `_text` import is temporary and is used only by the still-local prompt implementation.

- [ ] **Step 3: Run specification and facade tests**

```powershell
pytest tests/story_core/test_power_systems.py -q
```

Expected: all tests pass, including the new specification-facade identity test.

- [ ] **Step 4: Run template and world integration tests**

```powershell
pytest tests/story_core/test_power_system_templates.py tests/story_core/test_novel_type_catalog.py tests/story_core/test_novel_type_library.py tests/api/test_project_world_enrichment.py -q
```

Expected: all tests pass with unchanged validation messages and payloads.

- [ ] **Step 5: Commit the specification extraction**

```powershell
git add packages/story_core/power_system_spec.py packages/story_core/power_systems.py
git commit -m "refactor: isolate power system validation"
```

### Task 3: Extract Prompt Projection

**Files:**
- Create: `packages/story_core/power_system_prompt.py`
- Modify: `packages/story_core/power_systems.py`
- Test: `tests/story_core/test_power_systems.py`
- Test: `tests/story_core/test_writing_packet.py`
- Test: `tests/story_core/test_world_blueprint_context.py`

- [ ] **Step 1: Add and run the failing prompt-facade test**

Add this import and test to `tests/story_core/test_power_systems.py`:

```python
from packages.story_core import power_system_prompt


def test_public_facade_reexports_prompt_api() -> None:
    assert power_system_facade.legacy_power_summary is power_system_prompt.legacy_power_summary
    assert power_system_facade.power_system_prompt_slice is power_system_prompt.power_system_prompt_slice
```

Run:

```powershell
pytest tests/story_core/test_power_systems.py -q
```

Expected: collection fails because `power_system_prompt` does not exist yet.

- [ ] **Step 2: Create the prompt module from the remaining implementation**

Move all remaining constants and functions from `power_systems.py` into `power_system_prompt.py`, including the complete redaction section beginning with the currency regular expressions and these functions:

```text
_semantic_bounds
_nearest_preceding_semantic_distance
_nearest_following_semantic_distance
_redact_ambiguous_yuan
_redact_financial_percentages
_redact_exact_money
legacy_power_summary
_compact_prompt_value
_stage_slice
_path_slice
_json_length
_fit_prompt_budget
power_system_prompt_slice
```

Use these imports without changing function bodies:

```python
from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
import json
import math
import re
from typing import Any

from packages.story_core.power_system_spec import _text, normalize_power_system_spec
```

- [ ] **Step 3: Reduce the original module to a complete compatibility facade**

`packages/story_core/power_systems.py` must contain only:

```python
from __future__ import annotations

from packages.story_core.power_system_prompt import (
    legacy_power_summary,
    power_system_prompt_slice,
)
from packages.story_core.power_system_spec import (
    PowerSystemValidationError,
    normalize_power_system_spec,
    validate_power_system_spec,
)

__all__ = (
    "PowerSystemValidationError",
    "legacy_power_summary",
    "normalize_power_system_spec",
    "power_system_prompt_slice",
    "validate_power_system_spec",
)
```

- [ ] **Step 4: Run all power-system tests**

```powershell
pytest tests/story_core/test_power_systems.py tests/story_core/test_power_system_templates.py -q
```

Expected: all tests pass, including facade identity, money redaction, hostile-input bounds, path matching, and prompt budget tests.

- [ ] **Step 5: Run prompt consumers**

```powershell
pytest tests/story_core/test_writing_packet.py tests/story_core/test_writing_packet_plot.py tests/story_core/test_world_blueprint_context.py tests/api/test_project_world_enrichment.py -q
```

Expected: all tests pass with unchanged writing-packet and world-context snapshots.

- [ ] **Step 6: Commit the prompt extraction**

```powershell
git add packages/story_core/power_system_prompt.py packages/story_core/power_systems.py tests/story_core/test_power_systems.py
git commit -m "refactor: isolate power system prompt projection"
```

### Task 4: Extract the Project-Specific Migration Payload

**Files:**
- Create: `scripts/p_gou_power_system_data.py`
- Modify: `scripts/upgrade_project_power_system.py`
- Test: `tests/test_upgrade_project_power_system.py`

- [ ] **Step 1: Add and run the failing extracted-payload test**

Add this import and test to `tests/test_upgrade_project_power_system.py`:

```python
from scripts.p_gou_power_system_data import build_power_system_spec


def test_migration_payload_builder_delegates_to_extracted_project_data() -> None:
    assert migration._build_power_system_spec() == build_power_system_spec()
```

Run:

```powershell
pytest tests/test_upgrade_project_power_system.py -q
```

Expected: collection fails because `p_gou_power_system_data` does not exist yet.

- [ ] **Step 2: Move fixed project data into its own module**

Move `_PATH_DETAILS` and the full body of `_build_power_system_spec` into `scripts/p_gou_power_system_data.py`. Rename the extracted function to `build_power_system_spec` and keep its validation call unchanged.

The new module imports are:

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any

from packages.story_core.power_systems import validate_power_system_spec
```

The module exposes only the builder:

```python
__all__ = ("build_power_system_spec",)
```

- [ ] **Step 3: Keep the migration script's existing internal entry point**

Import the builder after repository-path setup:

```python
from scripts.p_gou_power_system_data import build_power_system_spec  # noqa: E402
```

Replace the original payload block with the compatibility wrapper:

```python
def _build_power_system_spec() -> dict[str, Any]:
    return build_power_system_spec()
```

Keep `validate_power_system_spec` imported in the migration script because `upgrade_project` performs a second validation of persisted project data.

- [ ] **Step 4: Run migration tests**

```powershell
pytest tests/test_upgrade_project_power_system.py -q
```

Expected: all tests pass, including payload equivalence, target-project rejection, backup creation, rollback, and check mode.

- [ ] **Step 5: Verify the migration is byte-stable in check mode**

```powershell
python scripts/upgrade_project_power_system.py data/exported-projects/p-gou-webgame-restored --check
```

Expected: the command exits successfully and reports the same check result as before extraction; it must not modify project files.

- [ ] **Step 6: Commit the migration extraction**

```powershell
git add scripts/p_gou_power_system_data.py scripts/upgrade_project_power_system.py tests/test_upgrade_project_power_system.py
git commit -m "refactor: separate project power migration data"
```

### Task 5: Final Regression and Cleanup Check

**Files:**
- Verify: all files changed in Tasks 1-4

- [ ] **Step 1: Run the focused cross-module suite**

```powershell
pytest tests/story_core/test_power_systems.py tests/story_core/test_power_system_templates.py tests/story_core/test_novel_type_catalog.py tests/story_core/test_novel_type_library.py tests/story_core/test_novel_type_runtime_integration.py tests/story_core/test_writing_packet.py tests/story_core/test_writing_packet_plot.py tests/story_core/test_world_blueprint_context.py tests/api/test_project_world_enrichment.py tests/api/test_novel_type_routes.py tests/test_upgrade_project_power_system.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the full Python suite**

```powershell
pytest -q
```

Expected: all tests pass. Any unrelated pre-existing failure must be recorded with its test name and left unmodified.

- [ ] **Step 3: Check repository hygiene**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors, generated project data, cache files, or unrelated changes.

- [ ] **Step 4: Inspect the final dependency direction**

```powershell
rg -n "from packages\.story_core\.power_system" packages/story_core apps scripts
```

Expected: consumers use `power_systems` unless they are the two internal implementation modules; `power_system_spec.py` does not import `power_system_prompt.py`.

- [ ] **Step 5: Commit any test-only cleanup if needed**

Only when Step 3 shows deliberate uncommitted test adjustments:

```powershell
git add tests
git commit -m "test: verify power system refactor integration"
```

If the worktree is already clean, do not create an empty commit.
