# Changelog

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
