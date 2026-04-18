# BlenDiff — Architecture

## Design Principles

1. **No binary diffing.** `bpy` is the API; we trust it completely.
2. **Separation of concerns.** Each module has one job and one job only.
3. **Data model first.** All modules agree on schemas defined in
   `data_model/`. If you add a new property, you add it there first.
4. **Extensibility by design.** Adding geometry-node diffing means:
   - adding an extractor method
   - adding a schema entry
   - adding a diff comparator
   No other files change.
5. **Testable without Blender.** The extractor needs `bpy`; everything
   downstream works on plain Python dicts and dataclasses.
6. **MergeEngine never applies automatically.** Always propose, then
   confirm per-conflict. Applier only runs after full resolution.
7. **Sidecar is always human-readable JSON.** Version-controllable
   alongside the `.blend` file.

---

## Data Flow

```
BlendFile A ──► SceneExtractor ──► MaterialExtractor
                     │                     │
                     ▼                     ▼
                Serializer ────── node_graph passthrough
                     │
              SceneSnapshot A (dict)
                     │
BlendFile B ──► same pipeline ──► SceneSnapshot B (dict)
                                         │
                                  DiffEngine.compare()
                                     + MaterialDiff
                                         │
                                     SceneDiff
                                         │
                         ┌───────────────┼───────────────┐
                         ▼               ▼               ▼
                     UI Panel       HTMLExporter      CLI/API
                                         │               │
                                   .html report    python -m blendiff.cli


Three-Way Merge:

Base ──► SceneSnapshot
Ver A ──► SceneSnapshot  ──► MergeEngine.three_way_diff()
Ver B ──► SceneSnapshot              │
                               ThreeWayDiff
                                     │
                              Conflict UI Panel
                                     │
                    (after all conflicts resolved)
                                     │
                               Applier.apply_all()
                                     │
                            bpy scene updated
```

---

## Module Contracts

### SceneExtractor (`extractor/scene_extractor.py`)
- Input: active `bpy.context`
- Output: raw Python dict matching `RawScene` shape, including `node_graph`
  per material slot when `use_nodes` is True
- Must never mutate `bpy.data`
- Catches exceptions per-object — one bad object never kills extraction

### MaterialExtractor (`extractor/material_extractor.py`)
- Input: `bpy.types.Material`
- Output: plain dict matching `MaterialSnapshot` schema
- Normalises: socket values to JSON-safe types, NaN/Inf → None
- Image texture nodes: stores `image.name`, not image data
- Only bpy-touching module for materials

### Serializer (`serializer/scene_serializer.py`)
- Input: raw Python dict from extractor
- Output: fully JSON-serialisable dict
- Normalises: `Vector/Euler/Quaternion → list[float]`, NaN/Inf → 0.0
- Passes `node_graph` through untouched (already JSON-safe from MaterialExtractor)

### DiffEngine (`diff_engine/diff_engine.py`)
- Input: two `SerializedScene` dicts
- Output: `SceneDiff` dataclass
- Stateless — `compare()` is a pure function
- Calls `MaterialDiff.compare_materials()` per material slot

### MaterialDiff (`diff_engine/material_diff.py`)
- Input: two `MaterialSnapshot` dicts
- Output: `list[PropertyChange]`
- Detects: node added/removed, type changed, input value changed (epsilon),
  image name changed, links added/removed/rewired
- Links compared as sets — order irrelevant

### DataModel (`data_model/`)
- All schemas as Python `dataclasses`
- `scene.py` — Transform, MaterialSlot, SceneObject, CollectionNode, SerializedScene
- `diff.py` — ChangeKind, PropertyChange, ObjectDiff, CollectionDiff, SceneDiff
- `material.py` — NodeInputSnapshot, NodeSnapshot, LinkSnapshot, MaterialSnapshot
- `conflict.py` — ConflictKind, Resolution, PropertyConflict, NonConflictingChange,
  MergeProposal, ThreeWayDiff
- No business logic, no I/O

### SidecarManager (`storage/sidecar.py`)
- Manages `.blendiff` JSON file next to the `.blend`
- Stores named, timestamped snapshots with UUIDs
- CRUD: save, list, get, delete, rename
- Corrupted sidecar handled gracefully — never crashes Blender
- Zero bpy imports

### HTMLExporter (`export/html_exporter.py`)
- Input: diff result dict + snapshot label + blend filename
- Output: self-contained `.html` string
- Single file, inline CSS + JS, zero external dependencies
- Dark-themed, color coded: green=added, red=removed, yellow=modified
- Annotation textareas per diff entry, download/load via browser API
- Zero bpy imports

### CLI / Headless API (`cli/`)
- `api.py` — pure Python: `list_snapshots()`, `compare_snapshots()`,
  `compare_snapshots_by_label()`, `compare_latest_two()`
- `__main__.py` — `python -m blendiff.cli list|compare|latest`
- Flags: `--output`, `--json`, `--fail-on-changes`, `--quiet`
- Exit codes: 0=no changes, 1=changes+fail-on-changes, 2=error
- Zero bpy imports

### MergeEngine (`merge_engine/merge_engine.py`)
- Input: three `SerializedScene` dicts (base, version_a, version_b)
- Output: `ThreeWayDiff` with `MergeProposal` per touched object
- Detects: BOTH_MODIFIED, MODIFY_DELETE, DELETE_MODIFY, ADD_ADD
- Auto-resolves identical changes on both sides
- Stateless — `three_way_diff()` is a pure function
- Zero bpy imports

### Applier (`merge_engine/applier.py`)
- Input: fully-resolved `ThreeWayDiff` + `bpy.context`
- Raises `RuntimeError` if any conflict is still unresolved
- Applies: transforms, visibility, collection moves, material slot swaps,
  object removal
- Each proposal is independently catchable — one failure doesn't block the rest
- Never called automatically

---

## Edge Cases Handled

| Situation | Handling |
|---|---|
| Object name collision | Names scoped under their collection path |
| Missing material slot | Serialised as `null` |
| Nested collections | Full path stored: `"Scene/Props/Small"` |
| Floating-point noise | Transforms and node inputs compared with configurable epsilon |
| Object with no data | `data_block` key is `null`, no crash |
| Bad node in material | Caught per-node, logged, extraction continues |
| Corrupted sidecar | Falls back to empty sidecar, logs warning |
| Unsaved .blend file | Sidecar operations raise `RuntimeError` with clear message |
| Identical ADD_ADD | Auto-resolved, no proposal created |
| Links order in node tree | Compared as sets — order irrelevant |

---

## Test Coverage

| Module | Test file | Tests |
|---|---|---|
| DataModel | test_data_model.py | 7 |
| DiffEngine | test_diff_engine.py | 19 |
| Serializer | test_serializer.py | 11 |
| SidecarManager | test_sidecar.py | 31 |
| MaterialDiff | test_material_diff.py | 39 |
| HTMLExporter | test_html_exporter.py | 43 |
| CLI / API | test_cli_api.py | 41 |
| MergeEngine | test_merge_engine.py | 33 |
| **Total** | | **224** |

All tests run without Blender (`python -m pytest tests/ -v`).