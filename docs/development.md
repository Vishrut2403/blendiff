# Developing with BlenDiff

This covers the parts of BlenDiff aimed at scripts and pipelines rather than at
someone working in Blender. The [README](../README.md) covers the addon itself,
and [architecture.md](architecture.md) explains how the code is laid out.

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

# Renames, matched by persistent id rather than name
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


## Snapshot compatibility

Snapshots record a schema version and the set of domains they captured. A domain
captured by only one of two snapshots is reported as **not compared** rather than
diffed. Otherwise a snapshot taken before F-curve support existed would make every
curve in a newer snapshot look newly added. Older snapshots are migrated to the
current schema as they are read; the file on disk is left alone until you call
`SidecarManager.migrate_file()`.

---

## Running Tests

```bash
pip install blendiff[dev]

# Pure-Python core, no Blender needed
pytest tests/ -v -m "not integration"

# Everything, including the extractor tests that run inside Blender
pytest tests/ -v
```

1124 unit tests run without Blender. A further 74 integration tests exercise the `extractor` package against a real Blender, alongside 56 checks that install and drive the addon itself, and all of them are skipped automatically when no Blender binary is found. Point `BLENDER_BINARY` at a specific build to test against a particular version:

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

See `ci_example.yml` in this folder for a diff-checking workflow template, and `.github/workflows/tests.yml` for the project's own CI: unit tests across Python 3.10–3.12, integration tests against Blender 4.2 and 5.1, and a check that the published wheel imports without Blender.

## Releasing

Releases are fully automated. Bump `__version__` in `blendiff/__init__.py`, update `CHANGELOG.md`, then push a tag:

```bash
git tag -a v0.9.0 -m "v0.9.0"
git push origin v0.9.0
```

`.github/workflows/release.yml` then verifies the tag matches the package version, runs the tests, builds the distributions, publishes to PyPI via Trusted Publishing (no API token), and attaches the Blender addon zip to the GitHub release with notes taken from the changelog.

---

