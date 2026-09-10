# BlenDiff — Architecture

## Design Principles

1. **No binary diffing.** `bpy` is the API; we trust it completely.
2. **Separation of concerns.** Each module has one job and one job only.
3. **Data model first.** All modules agree on schemas defined in
   `data_model/`. If you add a new property, you add it there first.
4. **Extensibility by design.** Adding geometry-node diffing means:
   - adding an extractor method
   - adding a domain to `data_model/schema.py`
   - adding a diff comparator
   - adding an applier entry, or leaving it explicitly unsupported
   No other files change.
5. **Testable without Blender.** The extractor needs `bpy`; everything
   downstream works on plain Python dicts and dataclasses. The extractor
   itself is covered by integration tests that run inside real Blender.
6. **MergeEngine never applies automatically.** Always propose, then
   confirm per-conflict. Applier only runs after full resolution.
7. **Sidecar is always human-readable JSON.** Version-controllable
   alongside the `.blend` file, and written atomically so a crash can
   never leave a truncated history.
8. **Never report a change you cannot substantiate.** A domain captured by
   only one of two snapshots is reported as *not compared*, never diffed.
   Transforms recorded in different spaces are not compared at all.
9. **Never claim to apply what you did not.** The applier registry answers
   `can_apply()` for every property path, results are counted per property,
   and unappliable differences are surfaced as read-only.

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

---

## Object Identity

Diffing keyed on `obj.name` cannot survive a rename: "Cube" becoming
"Body_LOW" reads as a deletion plus an unrelated addition, and every property
change on that object is lost with it. Artists rename constantly, so this was
the single largest correctness gap in the tool.

`obj.session_uid` is unique but regenerated on file load, so it cannot link two
snapshots. Instead each object is stamped with a UUID in a custom property,
`_blendiff_id`. Custom properties are saved inside the `.blend`, so the id
survives reload, rename, append and link.

Rules that keep this honest:

* **Stamping is opt-in per call.** Only snapshot capture stamps, because
  stamping writes to the `.blend` and marks it modified. Running a diff is
  read-only and never dirties the user's file.
* **Linked and library-overridden objects are never stamped.** Their data
  belongs to another file and cannot be saved.
* **Ambiguous ids are discarded.** Duplicating an object with Shift+D copies
  its custom properties, id included, so an id appearing on two objects is
  useless for matching. Those objects fall back to name matching, which
  handles duplication correctly: the original keeps its name and pairs up,
  the copy is a genuine addition.
* **The id is hidden from custom-property diffing**, since it is BlenDiff
  bookkeeping rather than user data.

Matching runs id-first, then name, then whatever remains is a real addition or
removal (`diff_engine/identity_match.py`). The resulting pairing is computed
once and shared by every domain, so parenting, constraints and animation all
agree on which object is which.

---

## Snapshot Schema Versioning

Snapshots outlive releases. BlenDiff's schema has grown every version — 0.3
added render and world, 0.4 parenting and constraints, 0.5 custom properties
and animation — and a snapshot taken before a feature existed has no data for
it.

Without version tracking, that absence is indistinguishable from deletion: a
0.4 snapshot has no `fcurves` key, so every curve in a 0.5 snapshot reads as
newly added and gets attributed to someone who never touched the animation.

Each snapshot therefore records `schema_version` and `captured_domains`
(`data_model/schema.py`). **A domain is diffed only when both snapshots
captured it**; otherwise it is reported in `SceneDiff.skipped_domains` with a
human-readable explanation in `skip_notes`, which the panel, the HTML report
and the CLI all surface.

Legacy snapshots have their captured domains *inferred* from which keys are
physically present — exactly what those keys meant before versioning existed.
Migration (`storage/migrate.py`) runs in memory on read, so an older BlenDiff
can still open the sidecar; the file is only rewritten when the user calls
`SidecarManager.migrate_file()`.

Transform space is tracked the same way. Schema v1 stored transforms
decomposed from `matrix_world`; v2 stores local transforms. The two are not
comparable — a parented object has entirely different values in each — so a
snapshot pair mixing them skips transform diffing rather than reporting noise.

---

## The Applier Registry

The diff engine reports property paths across sixteen domains. The applier
originally handled six of them through an `if/elif` chain, sending everything
else to a debug log. The merge UI would let a user resolve a modifier or
constraint conflict, report success, and write nothing — a silent no-op on the
operation where silence is most dangerous.

`merge_engine/property_appliers.py` makes the mapping data instead of control
flow. Each entry pairs a path pattern with a writer, and the module exposes:

* `can_apply(path)` — used by MergeEngine to mark each conflict `applicable`,
  and by the UI to decide whether to offer resolution buttons at all;
* `unsupported_reason(path)` — an explicit, user-facing reason for each known
  limitation, so "cannot apply" is never an unexplained blank.

Two consequences follow. Adding a diff domain without an applier is now
*visible* rather than silent: the domain simply reports `applicable=False`
everywhere. And conflicts BlenDiff cannot write back no longer block a merge —
requiring a decision there would hold up the changes it *can* apply in exchange
for a choice that would be discarded.

Results are accounted per property (`ApplyResult.applied` / `.skipped` /
`.failed`, each a named outcome) rather than per proposal, because a
proposal-level count cannot distinguish a merge that wrote everything from one
that wrote nothing.

---

## Testing Strategy

Two tiers, with different purposes.

**Unit tests** (900+, run in under a second without Blender) cover everything
downstream of the extractor. This is what makes the diff engine fast to iterate
on, and it is why the `bpy` boundary is worth defending so strictly. The merge
applier is included here: it writes to `bpy`, but only inside writer functions
that import it locally, so a fake `bpy` (`tests/fake_bpy.py`) exercises every
apply path including the failure paths.

**Integration tests** (`tests/integration/run_in_blender.py`, run via
`blender --background`) cover the `extractor` package — the only code that
touches real Blender data, and therefore the only place Blender API drift can
break BlenDiff silently. The Blender 5.x layered action API used for F-curve
extraction is exactly that kind of code: on Blender 5.1 the legacy
`action.fcurves` attribute does not exist at all, so the layered path is the
only one that runs.

Scenes there are built programmatically rather than loaded from committed
`.blend` fixtures. `.blend` is a binary format tied to a Blender version, so
fixtures rot and cannot be reviewed in a diff; building the scene in code keeps
the tests readable and portable across versions.

CI runs the unit tier on Python 3.10–3.12, the integration tier against two
Blender versions, and a packaging job asserting the published wheel imports
without Blender.


---

## Snapshot Storage

Every snapshot used to store the entire scene again, even when a single object
had moved. Measured on a realistic project — 80 objects, 50 snapshots, a
handful of edits each — that was 24.6 MB of sidecar and a 280 ms parse, paid
*every time the snapshot list was drawn*. The cost grew with disciplined use:
an artist who snapshotted before each session was punished for it, which is
exactly backwards for a version control tool.

Snapshots are now content-addressed. Each distinct object is stored once in a
shared pool keyed by a digest of its content, and snapshots reference it by
that digest (`storage/object_store.py`). An object untouched across forty
snapshots is written once instead of forty times. The same benchmark drops to
1.6 MB and a 17 ms parse — 15x smaller, 17x faster.

Packing happens in `_write_raw`, so every path that writes — save, delete,
rename, migrate — gets it, and a pre-0.3 sidecar with inline objects is packed
the first time anything is written. Unpacking happens in `Snapshot.from_dict`,
so the diff engine, the merge engine and the exporters never learn that any of
this occurred.

Deleting a snapshot runs a garbage collection pass over the pool. Without it
the pool would only grow, and removing history would free nothing.

### Why this stayed one file

A directory-based object store was the obvious alternative, and it was measured
before being rejected. At 17 ms there is nothing left to win, and a directory
would have cost the two properties that make the sidecar pleasant to live with:
it is a single human-readable file you can open, diff and commit next to the
`.blend`, and `blendiff list scene.blendiff` takes a file path. Deduplication
alone captures the benefit without spending either.

One caveat worth knowing: the saving is proportional to object size, because a
reference costs a fixed 32 characters. Real objects carry material node graphs
and run to kilobytes, so the trade is overwhelmingly favourable — but for
trivially small objects a reference costs about as much as the object it
replaces.


---

## Armatures

Rigs were the largest blind spot in the tool. An ARMATURE object recorded its
own transform, visibility and parent, and nothing about the rig itself — no
bones, no hierarchy, no rest pose, no pose transforms, no bone constraints.
Since rigs are the shared artefact riggers and animators collide over, that was
the case where a semantic diff and an assisted merge mattered most.

### Rest and pose are separate

They are different things, owned by different people, stored in different
places:

* **Rest data** lives on the armature datablock (`obj.data`), which can be
  shared between objects. It is the rigger's output: hierarchy, rest positions,
  roll, deform flags, bone collections.
* **Pose** lives on the object (`obj.pose`). It is the animator's output:
  per-bone transforms layered over the rest pose.

Keeping them apart means "the rig changed" and "the pose changed" stay
distinguishable, which is the distinction a team actually acts on. An
integration test asserts that posing a bone reports no rest-data change at all.

### Roll without edit mode

`roll` exists only on `EditBone`, so reading it directly would mean switching
the user's object into edit mode during extraction — invasive, and impossible
on a linked rig. `Bone.AxisRollFromMatrix` recovers the same value from the
bone's rest matrix, verified against a known 30° roll in the integration suite.

### Matching and reuse

Bones are matched by **name**. They have no stable id, and their order in the
datablock is an implementation detail. A renamed bone therefore reads as one
removed and one added, which is honest: BlenDiff has no way to know the two are
related.

Two pieces of existing machinery carried over unchanged. `extract_constraint_stack`
reads only `.constraints`, so it works verbatim on a pose bone — bone
constraints came free. `diff_constraint_stack` likewise compares a bone's
constraint stack with the same code that compares an object's.

### What merge can do here

Pose transforms are directly settable and are applied. Rest bones are not:
changing them requires edit mode, so they are reported as informational with
that reason attached. Bone addition and removal, and bone constraints, are
likewise reported rather than applied.
