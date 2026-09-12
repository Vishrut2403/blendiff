# Changelog

## 0.8.3 (2026-09-12)

### Removed
- **Snapshots no longer record the Git commit they were taken at.** Saving a
  snapshot used to run `git rev-parse --short HEAD` in the .blend file's own
  directory and store the result, so a snapshot could say which commit it
  belonged to.

  The Extensions Platform declined the submission over it. Terms of service 5.2
  does not allow an extension to need software beyond Blender installed, and it
  says so "even if those features are considered optional", which rules out the
  usual defence that the call was wrapped in try/except and degraded to None
  when git was absent. Running another program at all is the problem.

  The feature was not reachable from the interface in any case: the hash was
  only ever appended by `Snapshot.label_display()`, and the snapshot list draws
  `Snapshot.label` instead. `label_display()` has been removed along with it.

  Sidecar files written by earlier versions still carry a `git_hash` key.
  Loading ignores it rather than failing, so existing history opens unchanged.

### Added
- `tests/test_no_external_programs.py` parses every module for anything that
  starts or locates another program: the `subprocess` module, `os.system`,
  `os.popen`, the `os.exec*` and `os.spawn*` families, and `shutil.which`.
  The pre-submission checklist covered network access, `__file__` misuse and
  `sys.path` manipulation, and never looked for a subprocess, which is how this
  reached review.

## 0.8.2 (2026-09-11)

### Fixed
- **The GPL text was not shipped with the addon.** The manifest declared
  `SPDX:GPL-3.0-or-later`, which is what the Extensions Platform checks, but
  declaring a licence is not the same as conveying it. GPL-3.0 section 4
  requires every recipient to receive a copy of the licence along with the
  program, and the extension zip is built from the `blendiff/` directory alone,
  so the LICENSE at the repository root reached nobody who installed the addon.
  A copy now lives inside the package, and `tests/test_manifest.py` keeps it
  present and identical to the root one.

## 0.8.1 (2026-09-11)

### Fixed
- **The extension build did not work when installed as an extension.** Six
  modules under `diff_engine` imported the package by name, as
  `from blendiff.data_model.diff import ...`. That resolves for a pip install
  and for the legacy addon zip, where the package really is `blendiff`, and
  raises `ModuleNotFoundError` for an extension, where it is
  `bl_ext.<repository>.blendiff`. Enabling the extension failed with a message
  that named neither the module nor the cause, because `__init__.py` caught the
  ImportError and discarded it.

  Those imports are now relative, the discarded exception is kept and reported,
  and `tests/test_import_shape.py` parses every module for imports that name
  the package absolutely.

  Nothing caught this before: the unit suite imports the top-level package,
  where absolute imports are correct by definition, and the in-Blender tests
  load the source directory rather than an installed extension. It appeared the
  first time the built zip was installed the way the Extensions Platform
  installs it.

- **The addon did not appear in Preferences > Add-ons.** `bl_info["version"]`
  was computed from `__version__` rather than written out as a literal tuple.
  Blender never imports an addon to read its `bl_info`: it parses the source
  and runs `ast.literal_eval` on the dict, which accepts only literals. The
  computed tuple made that call raise, `addon_utils` skipped the module, and
  BlenDiff was absent from the list. Not greyed out, not failing to enable,
  simply not there, with nothing on screen to say why.

  The addon zip attached to every release since was therefore impossible to
  enable through the interface. Installing by hand and enabling from the
  console still worked, which is why unit tests, the in-Blender suite and the
  addon checks all passed: they import the module, and importing was never the
  broken part. `tests/test_manifest.py` now parses `__init__.py` the way
  Blender does, so a non-literal field fails in CI.

  Extensions installed from a `blender_manifest.toml` were unaffected, since
  the Extensions Platform reads the manifest and ignores `bl_info`.

- **Snapshot capture failed outright on many real scenes.** Three extractors
  guarded their value conversion with `hasattr(val, "__iter__")`, which is
  False for every mathutils type: Vector, Color, Euler, Quaternion and Matrix
  all implement the older sequence protocol instead. A Vector therefore passed
  through unconverted and `json.dumps` rejected the entire sidecar, so capture
  raised TypeError and wrote nothing at all. An Array modifier with a relative
  offset was enough to trigger it, and the same guard was used for constraint
  parameters and custom properties, so those leaked too.

  Conversion now attempts `list()` rather than asking the value which protocol
  it supports, and the serializer runs every passed-through field through the
  same helper, so one leaky extractor can no longer break capture for a whole
  scene.

  This went unnoticed because every test fixture built its modifiers from
  plain Python floats. It surfaced the first time BlenDiff ran against a
  .blend that a person had actually authored, and there is now a Blender test
  covering a vector modifier parameter, a vector constraint parameter and a
  vector custom property.


### Changed
- **Geometry hashing is about eleven times faster.** Profiling a scene shaped
  like a real asset (a 130k vertex hero mesh, a 200 bone rig, 60 props with
  node graphs) showed hashing taking most of extraction, at roughly 10.5
  microseconds per vertex. That put a two million vertex sculpt near 21 seconds
  per snapshot, long enough that an artist would assume the addon had hung.
  Two changes brought it to about 0.95 microseconds per vertex, measured as
  linear from 8k to 522k vertices:
  - `foreach_get` now fills a numpy buffer and quantisation runs in one
    vectorised pass, instead of a Python list and a per float loop
  - those buffers use float32, matching how Blender stores coordinates and UVs.
    A float64 buffer made `foreach_get` convert every element rather than copy
    the block: 12.7 ms against 2.9 ms for one dense mesh's vertices, and
    40.5 ms against 13.6 ms for its UVs. Widening to float64 afterwards is
    exact, so the quantised values and the digests are unchanged
  Warm extraction of the whole test scene went from about 1.5 seconds to 186
  ms. A two million vertex mesh drops from about 21 seconds to about 2. The
  pure Python path stays as a fallback and produces byte identical output,
  which is tested
- Geometry digests now carry a format version, written as `2:` followed by the
  hash. Digests are only meaningful against one produced the same way, so a
  snapshot taken before this change is treated as not comparable rather than as
  a scene where every mesh was edited. Without that, the first diff after
  upgrading would be full of geometry edits nobody made


### Added
- **Merge can now apply rest-bone changes.** Reparenting a bone, moving its
  rest position and changing its roll were reported as read-only, because those
  fields exist only on `EditBone` and reaching them means entering edit mode.
  That rules edit mode out during *extraction*, which runs on every diff, must
  not disturb the user's mode, and cannot touch a linked rig. None of that
  applies when the user has explicitly asked for a merge. Merge now
  handles a rigger's changes, not just an animator's
- Rest-bone changes are applied as a **single edit-mode session per object**
  rather than one attribute at a time, which would be slow on a real rig and
  would push a stack of undo steps. Fields are written in dependency order,
  with `use_connect` last because connecting a bone snaps its head onto the
  parent's tail
- Mode, active object and selection are restored afterwards. A merge that left
  an artist in edit mode on an object they had not selected would be
  disruptive, so this is asserted in both the unit and Blender suites
- Linked rigs and library overrides are reported with the reason rather than
  failing, and never enter edit mode
- Bone flags (`use_deform`, inheritance, envelopes, `hide`) and armature
  settings (`pose_position`, `display_type`) apply without a mode switch at
  all, because they are writable on `Bone` directly

## 0.8.0 (2026-09-10)

### Added
- **Armature and pose diffing.** Rigs were the largest blind spot: an ARMATURE
  object recorded only its own transform, so a character could be reparented,
  re-rolled, re-posed or have its IK chain rewired and BlenDiff reported
  nothing, even though rigs are what riggers and animators most often work on
  together. Now captured:
  - **Rest data** (the rigger's output, on the shared armature datablock): bone
    hierarchy and connection, head/tail rest positions, length, roll, deform
    and inheritance flags, envelope settings, bone collections, pose position
    and display type
  - **Pose** (the animator's output, on the object): per-bone location,
    rotation in whichever channel the bone's rotation mode selects, scale,
    custom shape, and bone constraints
  - Rest and pose are reported separately, so "the rig changed" stays
    distinguishable from "the pose changed"
- Bone roll is derived from the rest matrix via `Bone.AxisRollFromMatrix`, so a
  roll change is detected without switching the object into edit mode, which
  would disturb the user and is impossible on a linked rig
- Merge can apply pose bone transforms. Rest bones, bone addition and removal,
  and bone constraints are reported as informational, each with a reason
- Property paths use Blender's own data-path syntax
  (`pose.bones["Head"].location`), matching the UI, driver expressions and the
  F-curve paths BlenDiff already reports
- **Content-addressed snapshot storage**: each distinct object is stored once
  and referenced by digest, instead of every snapshot storing the whole scene
  again. On a realistic project (80 objects, 50 snapshots, a handful of edits
  each) the sidecar drops from **24.6 MB to 1.6 MB** and parse time from
  **280 ms to 17 ms**, so 15x smaller and 17x faster. The cost previously grew with
  disciplined use, so an artist who snapshotted before each session was
  punished for it
- Deleting a snapshot now reclaims the objects nothing else references, so
  removing history actually frees space
- `SidecarManager.storage_stats()` reports how much deduplication is saving
- Releases attach the Blender addon zip automatically, with notes taken from
  the changelog. A tag push now performs the entire release: verify, test,
  build, publish to PyPI, create the GitHub release with the addon attached
- **Addon end-to-end test tier.** The operators, panels, and the merge Applier
  against real bpy had no coverage at all. Every applier test used a fake, so
  the code that writes merge results into a live scene had never once run
  against Blender. 55 checks now drive the real addon inside Blender, and CI
  runs them

- **Blender Extensions Platform support.** A `blender_manifest.toml` inside
  `blendiff/` makes the addon installable from Edit → Preferences → Get
  Extensions, with automatic updates, no zip download and no terminal. The
  release workflow now publishes both an extension zip (Blender 4.2+) and the
  legacy addon zip (3.6+), since the manifest requires 4.2 while `bl_info`
  still supports older versions

### Changed
- **HTML reports no longer land in your project directory.** They are
  timestamped, so one accumulated per export and the folder holding the
  `.blend` slowly filled with files nobody chose to keep there. Exporting now
  opens a file browser, like every other export in Blender, defaulting to the
  system temp directory. A project directory holds just the `.blend` and its
  `.blendiff` sidecar
- **Relicensed to GPL-3.0-or-later.** The Extensions Platform requires it:
  anything using the `bpy` API is treated as a derivative of Blender, which is
  itself GPL. One licence covers the whole project, so the pip package and the
  addon remain the same code under the same terms

### Fixed
- **Object identity now survives a session closed without saving.** Snapshot
  capture stamps a `_blendiff_id` into each object, but writing a custom
  property does not set Blender's dirty flag, so the user was never prompted
  to save, the stamps evaporated on close, and the next session minted fresh
  ids matching nothing in the stored snapshots. Rename tracking, the whole
  reason identity exists, silently degraded to the name matching it replaces.
  Two fixes: stamping now marks the file modified so the save prompt appears,
  and an object missing its stamp recovers the id recorded for that name in
  the most recent snapshot, making the sidecar the durable record. A rename
  made *within* an unsaved session still cannot be recovered, because nothing
  links the old and new names. That limit is asserted in the test suite
- **A `.blend` separated from its `.blendiff` now says so.** Moving or renaming
  a `.blend` without its sidecar showed an empty snapshot list, identical to
  never having taken one. Objects keep their identity stamps inside the
  `.blend`, so stamps present with no sidecar beside the file proves history
  existed elsewhere, and BlenDiff reports it
- **Addon teardown is no longer all-or-nothing.** `unregister_class` raises for
  a class that is not registered, and the loops called it unguarded, so one
  such class aborted the rest of `unregister`, leaving the addon half torn down
  with WindowManager properties leaked and Blender reporting "Exception in
  module unregister()". This fires whenever registration partially failed, and
  in the case about to become common: installing the extension while the legacy
  addon zip is still enabled
- **`pip install blendiff` now ships the whole package.** `extractor/` was
  excluded from the wheel, so installing into Blender's own Python could not
  capture snapshots at all, breaking headless pipelines, despite every
  extractor module importing bpy lazily and importing fine without Blender.
  The wheel and the addon zip are now the same code; what differs is only that
  Blender discovers addons in its scripts/addons and extensions directories,
  not in site-packages
- `register()` no longer claims the PyPI package ships only the headless core,
  which stopped being true. It now distinguishes running outside Blender from
  the UI modules failing to import

## 0.7.0 (2026-09-09)

### Added
- **Mesh geometry diffing**: meshes now carry three content digests, so
  topology-preserving edits are detected at all. Previously mesh capture was
  counts plus a bounding box, which meant moving a vertex inside the existing
  bounds changed nothing BlenDiff recorded and the edit was reported as no
  change:
  - `mesh.vertex_positions`: a vertex moved; the model was sculpted or tweaked
  - `mesh.topology`: faces or edges were rebuilt, subdivided, or removed
  - `mesh.uvs`: the model is untouched but it was re-unwrapped, or a UV layer
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

## 0.6.0 (2026-09-09)

The theme of this release is **trustworthiness**: BlenDiff now refuses to report
changes it cannot substantiate, and refuses to claim it applied changes it did
not.

### Added
- **Persistent object identity**: objects are stamped with a `_blendiff_id`
  custom property on snapshot capture, and diffs match on it before falling back
  to name. Renaming an object is now a single modified object carrying all its
  other changes, instead of an unrelated deletion plus addition
- **Snapshot schema versioning**: snapshots record their schema version and the
  domains they captured. A domain captured by only one of two snapshots is
  reported as *not compared* rather than diffed, so an old snapshot no longer
  makes every F-curve look newly added. Older snapshots are migrated on read
- **Applier registry**: the merge applier dispatches through a data-driven
  registry that also answers "can this be applied?", so the merge UI marks
  unappliable differences read-only instead of soliciting a resolution it would
  silently discard
- Merge now covers **every diff domain**: parenting, constraints, custom
  properties, F-curves, drivers, NLA, collections and scene-level settings.
  Previously only object property changes participated
- Merge can now apply parenting, custom properties, camera and light data,
  object renames, render visibility and multi-collection membership
- Render visibility (`hide_render`) and view-layer visibility are tracked
  independently of viewport visibility
- Full collection membership: an object linked into several collections keeps
  all of them, recorded as full paths
- `rotation_mode` is captured, along with quaternion and axis-angle values for
  objects driven by them
- **Headless Blender integration tests**: 39 tests exercising the `extractor`
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
  properties, which teleported any parented object it touched
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
  repository, snapshot capture fell back to the process working directory,
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

## 0.5.0 (2026-04-30)

### Added
- Custom property diffing: added/removed/changed `obj[key]` properties with float tolerance
- F-curve diffing: per-channel keyframe count, frame range, interpolation, extrapolation
- All new diff types fully wired end-to-end: extract → serialize → snapshot → diff → UI panel → HTML report
- `SceneDiff` now includes `custom_prop_diffs` and `fcurve_diffs`
- `summary()` now includes counts for all new diff types
- Serializer updated to pass through parent, constraint, custom prop, and F-curve data
- 63 new tests (28 custom props, 35 F-curves), total now 602+

### Fixed
- `SceneSerializer._serialize_object` was silently dropping parent, constraint, custom prop, and F-curve fields
- F-curve extraction compatible with both Blender 4.x (`action.fcurves`) and Blender 5.x layered action API

## 0.4.0 (2026-04-29)

### Added
- Parent/child relationship diffing: parent name, parent type, parent bone (critical for rigs)
- Constraint stack diffing: per-object constraint list, type, influence, target, and 25+ type-specific params covering IK, Copy Location/Rotation/Scale, Track To, Child Of, Floor, Follow Path, Shrinkwrap, Action, and more
- `SceneDiff.parent_diffs` and `SceneDiff.constraint_diffs` fields
- `SceneDiff.summary()` now includes `parent_changes` and `constraint_changes` counts
- `ParentDiff` and `ConstraintDiff` dataclasses with `.summary()` method
- 71 new tests (28 parent, 43 constraint), total now 574+

## 0.3.0 (2026-04-25)

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

## 0.2.0 (2026-04-22)

### Added
- Initial release
- Object, transform, collection, material node graph diffing
- Three-way merge with conflict resolution UI
- Annotated HTML export
- Headless CLI with exit codes
- Sidecar snapshot storage
