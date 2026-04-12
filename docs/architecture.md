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

## Data flow

```
BlendFile A ──► SceneExtractor ──► Serializer ──► SceneSnapshot (dict)
                                                          │
                                                          ├── SceneSnapshot A
BlendFile B ──► SceneExtractor ──► Serializer ──► SceneSnapshot B
                                                          │
                                                   DiffEngine.compare()
                                                          │
                                                      SceneDiff (dict)
                                                          │
                                                      UI Panel / JSON
```

## Module contracts

### SceneExtractor
- Input: active `bpy.context` (or a loaded blend path)
- Output: raw Python dict matching `RawScene` shape
- Must never mutate `bpy.data`

### Serializer
- Input: raw Python dict from extractor
- Output: fully JSON-serialisable dict (no `mathutils.Vector`, no
  `bpy.types.*`)
- Normalises: `Vector/Euler/Quaternion → list[float]`, `None → null`

### DiffEngine
- Input: two `SerializedScene` dicts
- Output: `SceneDiff` dataclass (see `data_model/diff.py`)
- Stateless — compare() is a pure function

### DataModel
- All schemas live here as Python `dataclasses` (and as JSON Schema
  docs for external tooling)
- No business logic, no I/O

### MergeEngine (future)
- Input: `SceneDiff` + user selections
- Output: merge instructions (list of operations)
- Does NOT apply changes automatically — it proposes them

## Edge cases handled

| Situation | Handling |
|---|---|
| Object name collision | Names scoped under their collection path |
| Missing material slot | Serialised as `null` |
| Nested collections | Full path stored: `"Scene/Props/Small"` |
| Floating-point noise | Transforms compared with configurable epsilon |
| Object with no data | `data_block` key is `null`, no crash |