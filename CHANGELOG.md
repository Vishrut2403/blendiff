# Changelog

## 0.7.0 — 2026-09-09

### Added
- **Mesh geometry diffing** — meshes now carry three content digests, so
  topology-preserving edits are detected at all. Previously mesh capture was
  counts plus a bounding box, which meant moving a vertex inside the existing
  bounds changed nothing BlenDiff recorded and the edit was reported as no
  change:
  - `mesh.vertex_positions` — a vertex moved; the model was sculpted or tweaked
  - `mesh.topology` — faces or edges were rebuilt, subdivided, or removed
  - `mesh.uvs` — the model is untouched but it was re-unwrapped, or a UV layer
    was renamed
- Digests are reported separately on purpose: positions changing while topology
  holds steady is a very different edit from both changing, and one combined
  flag would lose that
- Coordinates are quantised to the serializer's float precision before hashing,
  so a digest reflects geometry rather than float noise
- 47 new tests, including 7 in-Blender integration tests proving a moved vertex
  is caught while every previously-recorded count and bound stays identical

### Changed
- Snapshots record geometry digests. Older snapshots have none, and a digest is
  only compared when both sides recorded one, so upgrading never reports a
  phantom geometry edit
- Releases now publish to PyPI through Trusted Publishing on a version tag, so
  there is no long-lived API token

## 0.6.0 — 2026-09-09

The theme of this release is **trustworthiness**: BlenDiff now refuses to report
changes it cannot substantiate, and refuses to claim it applied changes it did
not.

### Added
- **Persistent object identity** — objects are stamped with a `_blendiff_id`
  custom property on snapshot capture, and diffs match on it before falling back
  to name. Renaming an object is now a single modified object carrying all its
  other changes, instead of an unrelated deletion plus addition
- **Snapshot schema versioning** — snapshots record their schema version and the
  domains they captured. A domain captured by only one of two snapshots is
  reported as *not compared* rather than diffed, so an old snapshot no longer
  makes every F-curve look newly added. Older snapshots are migrated on read
- **Applier registry** — the merge applier dispatches through a data-driven
  registry that also answers "can this be applied?", so the merge UI marks
  unappliable differences read-only instead of soliciting a resolution it would
  silently discard
- Merge now covers **every diff domain** — parenting, constraints, custom
  properties, F-curves, drivers, NLA, collections and scene-level settings.
  Previously only object property changes participated
- Merge can now apply parenting, custom properties, camera and light data,
  object renames, render visibility and multi-collection membership
- Render visibility (`hide_render`) and view-layer visibility are tracked
  independently of viewport visibility
- Full collection membership — an object linked into several collections keeps
  all of them, recorded as full paths
- `rotation_mode` is captured, along with quaternion and axis-angle values for
  objects driven by them
- **Headless Blender integration tests** — 39 tests exercising the `extractor`
  package against a real Blender, run in CI against Blender 4.2 and 5.1
- GitHub Actions workflow covering unit tests, integration tests and a check
  that the published wheel imports without Blender

### Fixed
- **Sidecar writes are now atomic.** The file holding the entire snapshot
  history was rewritten in place; a crash or full disk during the write
  destroyed every snapshot
- **Transforms are recorded in local space.** They were decomposed from
  `matrix_world`, which meant moving a parent reported a change on every
  descendant, and the merge applier wrote world-space values into local-space
  properties — teleporting any parented object it touched
- **Resolved delete/modify conflicts now take effect.** `__existence__` was
  filtered out before dispatch, making the most important conflict in any merge
  a guaranteed no-op
- **Merge results are counted per property, not per proposal.** A merge that
  applied nothing previously reported success
- **Auto-resolved conflicts apply the agreed value**, not the base value, which
  silently reverted changes both sides had made
- **The CLI reports every domain it diffs.** `blendiff compare` built its own
  result dict covering only objects and collections, so its summaries and HTML
  reports silently omitted eight domains. Both front-ends now share one
  conversion
- **Object collection paths are full paths.** Only the first collection's bare
  name was recorded, which could not be matched against the collection tree
- **Git hashes are no longer guessed.** When the .blend's directory was not a
  repository, snapshot capture fell back to the process working directory —
  stamping snapshots with the hash of whatever repository Blender was launched
  from
- **The published wheel imports inside Blender.** `blendiff/__init__` imported
  the UI package that the wheel deliberately excludes
- Malformed constraint or modifier entries no longer raise `KeyError` and take
  the entire scene diff down with them
- The version is stated in one place; `__init__.py`, `bl_info` and
  `pyproject.toml` had drifted to 0.3.0, 0.4.0 and 0.5.0 simultaneously
- Indentation normalised to tabs across the codebase

### Changed
- `ApplyResult` now reports `applied` / `skipped` / `failed` lists of named
  outcomes rather than bare proposal counts
- `SceneDiff` gains `renamed_objects`, `skipped_domains`, `skip_notes` and
  `object_pairs`
- Conflicts BlenDiff cannot apply no longer block a merge; they are surfaced as
  informational so the applicable changes can proceed
- Sidecar format version is now `0.2` (reading `0.1` is fully supported)

## 0.5.0 — 2026-04-30

### Added
- Custom property diffing — added/removed/changed `obj[key]` properties with float tolerance
- F-curve diffing — per-channel keyframe count, frame range, interpolation, extrapolation
- All new diff types fully wired end-to-end: extract → serialize → snapshot → diff → UI panel → HTML report
- `SceneDiff` now includes `custom_prop_diffs` and `fcurve_diffs`
- `summary()` now includes counts for all new diff types
- Serializer updated to pass through parent, constraint, custom prop, and F-curve data
- 63 new tests (28 custom props, 35 F-curves), total now 602+

### Fixed
- `SceneSerializer._serialize_object` was silently dropping parent, constraint, custom prop, and F-curve fields
- F-curve extraction compatible with both Blender 4.x (`action.fcurves`) and Blender 5.x layered action API

## 0.4.0 — 2026-04-29

### Added
- Parent/child relationship diffing — parent name, parent type, parent bone (critical for rigs)
- Constraint stack diffing — per-object constraint list, type, influence, target, and 25+ type-specific params covering IK, Copy Location/Rotation/Scale, Track To, Child Of, Floor, Follow Path, Shrinkwrap, Action, and more
- `SceneDiff.parent_diffs` and `SceneDiff.constraint_diffs` fields
- `SceneDiff.summary()` now includes `parent_changes` and `constraint_changes` counts
- `ParentDiff` and `ConstraintDiff` dataclasses with `.summary()` method
- 71 new tests (28 parent, 43 constraint), total now 574+

## 0.3.0 — 2026-04-25

### Added
- Render settings diffing (engine, resolution, sampling, output, color management, Cycles, EEVEE)
- Camera data block diffing (focal length, clip planes, DOF, sensor, shift)
- Light data block diffing (type, color, energy, shadow, spot/area/sun specific settings)
- Mesh summary diffing (vertex/edge/face counts, bounding box, UV layers, shape keys, vertex groups)
- World/environment diffing (background color, strength, HDRI filepath detection, ambient occlusion)
- Git commit hash auto-labelling on snapshots with graceful fallback
- `Snapshot.label_display()` showing label with hash suffix

### Fixed
- `SceneDiff` field renamed `render` → `render_diff` for consistency
- `SceneDiff.has_changes` now includes render and world changes
- Blender 5.1 compatibility for world ambient occlusion attribute

## 0.2.0 — 2026-04-22

### Added
- Initial release
- Object, transform, collection, material node graph diffing
- Three-way merge with conflict resolution UI
- Annotated HTML export
- Headless CLI with exit codes
- Sidecar snapshot storage
