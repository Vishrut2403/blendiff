# Changelog

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
