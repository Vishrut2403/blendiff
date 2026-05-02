# BlenDiff

**Semantic diff, snapshot history, and assisted merge for Blender `.blend` files.**

BlenDiff compares two `.blend` file states using Blender's Python API — not binary diffing — and provides a full assisted merge system. It ships as both a Blender addon and a pip-installable pure-Python library for headless/CI use.

---

## Features

- **Snapshot history** — named, timestamped snapshots stored in a human-readable `.blendiff` JSON sidecar next to your `.blend` file
- **Object & collection diffing** — detects added, removed, and modified objects with per-property change tracking (transform, visibility, collection membership)
- **Material node graph diffing** — per-node, per-socket comparison including image names, input values, and rewired links
- **Render settings diffing** — engine, resolution, sampling, output format, color management, Cycles and EEVEE sub-settings
- **Camera & light diffing** — focal length, clip planes, DOF, sensor, light type, energy, shadow, spot/area/sun settings
- **Mesh summary diffing** — vertex/edge/face counts, bounding box, UV layers, shape keys, vertex groups
- **World/environment diffing** — background color, strength, HDRI filepath, ambient occlusion
- **Modifier stack diffing** — ordered comparison of 15+ modifier types with per-param change detection
- **Parent/child relationship diffing** — parent name, parent type, parent bone (critical for rigs)
- **Constraint stack diffing** — 25+ constraint types with per-param comparison (IK, Copy Location/Rotation/Scale, Track To, Child Of, and more)
- **Custom property diffing** — detects added, removed, and changed `obj[key]` properties with float tolerance
- **F-curve diffing** — per-channel keyframe count, frame range, interpolation, and extrapolation
- **Three-way merge** — conflict detection and per-property resolution (Use A / Use B / Use Base) with a Blender UI
- **Annotated HTML export** — self-contained dark-themed report with per-entry annotation textareas and JSON round-trip
- **Headless CLI** — run diffs in CI without launching Blender

---

## Installation

### As a pip library (no Blender required)

```bash
pip install blendiff
```

### As a Blender addon

Download the latest `blendiff-0.5.0.zip` from [Releases](https://github.com/Vishrut2403/blendiff/releases) and install via **Edit → Preferences → Add-ons → Install**.

---

## CLI Usage

```bash
# List snapshots in a sidecar file
blendiff list scene.blendiff

# Compare two snapshots
blendiff compare scene.blendiff "Before rigging" "After rigging"

# Fail CI if any changes exist
blendiff latest scene.blendiff --fail-on-changes

# Export an HTML report
blendiff compare scene.blendiff "v1" "v2" --output report.html
```

---

## Python API

```python
from blendiff.storage.sidecar import SidecarManager
from blendiff.diff_engine.diff_engine import DiffEngine

mgr = SidecarManager("scene.blendiff")
snaps = {s.label: s for s in mgr.list_snapshots()}

engine = DiffEngine()
result = engine.compare(snaps["v1"].data, snaps["v2"].data)

# Render settings diff
print(result.render_diff.summary())

# Object diffs
for diff in result.object_diffs:
    print(diff.name, diff.kind)
    for change in diff.changes:
        print(" ", change.property_path, change.old_value, "→", change.new_value)

# Parent relationship diffs
for diff in result.parent_diffs:
    print(diff.summary())

# Constraint diffs
for diff in result.constraint_diffs:
    print(diff.summary())

# Custom property diffs
for diff in result.custom_prop_diffs:
    print(diff.summary())

# F-curve diffs
for diff in result.fcurve_diffs:
    print(diff.summary())
```

---

## Architecture

```
blendiff/
├── data_model/      # Dataclasses — SceneDiff, RenderDiff, ParentDiff, ConstraintDiff, …
├── diff_engine/     # Pure comparison logic — no bpy
├── serializer/      # mathutils → JSON-safe types
├── storage/         # .blendiff sidecar CRUD
├── export/          # Self-contained HTML report generation
├── cli/             # Headless CLI + importable Python API
├── extractor/       # bpy readers (Blender-only)
└── ui/              # Blender panels and operators (Blender-only)
```

The extractor is the **only** bpy-touching module. Everything downstream is pure Python and fully testable without Blender.

---

## Running Tests

```bash
pip install blendiff[dev]
pytest tests/ -v
```

600+ tests, all passing without a Blender installation.

---

## CI Integration

```yaml
# .github/workflows/diff.yml
- name: Check for scene changes
  run: blendiff latest scene.blendiff --fail-on-changes
```

See `docs/ci_example.yml` for a full GitHub Actions workflow template.

---

## License

MIT