# BlenDiff

**Semantic diff, snapshot history, and assisted merge for Blender `.blend` files.**

BlenDiff compares two `.blend` file states using Blender's Python API — not binary diffing — and provides a full assisted merge system. It ships as both a Blender addon and a pip-installable pure-Python library for headless/CI use.

BlenDiff aims to be **honest about what it knows**: it will not report a change it cannot substantiate, and will not claim to have applied one it did not. Domains an older snapshot never captured are reported as *not compared* rather than diffed, and merge conflicts BlenDiff cannot write back are shown as read-only rather than soliciting a decision it would discard.

---

## Features

- **Snapshot history** — named, timestamped snapshots in a human-readable `.blendiff` JSON sidecar next to your `.blend` file, written atomically so a crash can never truncate your history, and content-addressed so a hundred snapshots of a mostly-unchanged scene cost a fraction of a hundred copies
- **Rename tracking** — objects carry a persistent id, so renaming `Cube` to `Body_LOW` stays one modified object with all its other changes intact, instead of an unrelated delete plus add
- **Object & collection diffing** — detects added, removed, renamed, and modified objects with per-property change tracking (local transform, viewport/render visibility, multi-collection membership)
- **Material node graph diffing** — per-node, per-socket comparison including image names, input values, and rewired links
- **Render settings diffing** — engine, resolution, sampling, output format, color management, Cycles and EEVEE sub-settings
- **Camera & light diffing** — focal length, clip planes, DOF, sensor, light type, energy, shadow, spot/area/sun settings
- **Mesh geometry diffing** — content digests for vertex positions, topology and UVs, so a moved vertex is detected even when every count and bound is unchanged; plus counts, bounding box, UV layers, shape keys, vertex groups
- **World/environment diffing** — background color, strength, HDRI filepath, ambient occlusion
- **Modifier stack diffing** — ordered comparison of 15+ modifier types with per-param change detection
- **Armature & pose diffing** — bone hierarchy, rest positions, roll, deform and inheritance flags, bone collections, per-bone pose transforms, custom shapes, and bone constraints. Reparenting a finger, re-rolling a bone or rewiring an IK chain is now visible
- **Parent/child relationship diffing** — parent name, parent type, parent bone (critical for rigs)
- **Constraint stack diffing** — 25+ constraint types with per-param comparison (IK, Copy Location/Rotation/Scale, Track To, Child Of, and more)
- **Custom property diffing** — detects added, removed, and changed `obj[key]` properties with float tolerance
- **F-curve diffing** — per-channel keyframe count, frame range, interpolation, and extrapolation
- **Schema versioning** — snapshots record which domains they captured, so diffing across BlenDiff versions never invents changes for a feature that did not exist yet
- **Three-way merge** — conflict detection across *every* diff domain, with per-property resolution (Use A / Use B / Use Base) in a Blender UI that marks unappliable differences read-only
- **Annotated HTML export** — self-contained dark-themed report with per-entry annotation textareas and JSON round-trip
- **Headless CLI** — run diffs in CI without launching Blender

---

## Installation

### As a pip library (no Blender required)

```bash
pip install blendiff
```

### As a Blender addon (Blender 4.2+)

Edit → Preferences → **Get Extensions**, search for **BlenDiff**, click Install. Updates arrive automatically.

### As a Blender addon (Blender 3.6–4.1)

Download the latest `blendiff-0.7.0.zip` from [Releases](https://github.com/Vishrut2403/blendiff/releases) and install via **Edit → Preferences → Add-ons → Install**.

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

# Renames — matched by persistent id, not name
for diff in result.renamed_objects:
    print(diff.previous_name, "→", diff.name)

# Domains one snapshot never captured, so they were not compared
for note in result.skip_notes:
    print("not compared:", note)

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
├── data_model/      # Dataclasses — SceneDiff, ConstraintDiff, …, plus schema.py
├── diff_engine/     # Pure comparison logic — no bpy
├── serializer/      # mathutils → JSON-safe types
├── storage/         # .blendiff sidecar CRUD + schema migration
├── merge_engine/    # Three-way merge and the applier registry
├── export/          # Shared diff→dict conversion + HTML report generation
├── cli/             # Headless CLI + importable Python API
├── extractor/       # bpy readers (Blender-only)
└── ui/              # Blender panels and operators (Blender-only)
```

The extractor is the **only** module that reads from `bpy`. Everything downstream is pure Python and fully testable without Blender. The merge applier writes to `bpy`, but only inside individual writer functions that import it locally, so the module stays importable and testable outside Blender.

### What merge can and cannot apply

The applier registry (`merge_engine/property_appliers.py`) is the single source of truth, and `can_apply(property_path)` answers it directly. The merge UI uses that answer to decide whether to offer a resolution at all, so it never asks you to choose between two values it would then discard.

| Applied automatically | Reported, but reconcile by hand |
|---|---|
| Object name, local transform, rotation mode | Mesh geometry (hashed, not stored) |
| Viewport and render visibility | Modifier and constraint stacks |
| Collection membership | Keyframes, drivers, NLA strips |
| Material slot assignment | Material node graphs |
| Parenting (world position preserved) | Object type, collection hierarchy |
| Pose bone transforms | Rest bones (edit-mode only), bone constraints |
| Custom properties | Object creation (needs the source file) |
| Camera and light data | |

### Snapshot compatibility

Snapshots record a schema version and the set of domains they captured. A domain captured by only one of two snapshots is reported as **not compared** rather than diffed — otherwise a snapshot taken before F-curve support existed would make every curve in a newer snapshot look newly added. Older snapshots are migrated to the current schema as they are read; the file on disk is left alone until you call `SidecarManager.migrate_file()`.

---

## Running Tests

```bash
pip install blendiff[dev]

# Pure-Python core — no Blender needed
pytest tests/ -v -m "not integration"

# Everything, including the extractor tests that run inside Blender
pytest tests/ -v
```

1000+ unit tests run without Blender. A further 46 integration tests exercise the `extractor` package against a real Blender, and are skipped automatically when no Blender binary is found. Point `BLENDER_BINARY` at a specific build to test against a particular version:

```bash
BLENDER_BINARY=/opt/blender-4.2/blender pytest tests/integration -v
```

---

## CI Integration

```yaml
# .github/workflows/diff.yml
- name: Check for scene changes
  run: blendiff latest scene.blendiff --fail-on-changes
```

See `docs/ci_example.yml` for a diff-checking workflow template, and `.github/workflows/tests.yml` for the project's own CI — unit tests across Python 3.10–3.12, integration tests against Blender 4.2 and 5.1, and a check that the published wheel imports without Blender.

## Releasing

Releases are fully automated. Bump `__version__` in `blendiff/__init__.py`, update `CHANGELOG.md`, then push a tag:

```bash
git tag -a v0.9.0 -m "v0.9.0"
git push origin v0.9.0
```

`.github/workflows/release.yml` then verifies the tag matches the package version, runs the tests, builds the distributions, publishes to PyPI via Trusted Publishing (no API token), and attaches the Blender addon zip to the GitHub release with notes taken from the changelog.

---

## License

GPL-3.0-or-later. See `LICENSE`.

BlenDiff is licensed under the GNU General Public License v3 or later because
Blender's Extensions Platform requires it: anything using the `bpy` API is
treated as a derivative of Blender, which is itself GPL. The pip package and
the Blender addon ship the same code under the same terms.