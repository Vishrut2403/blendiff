"""
blendiff.cli.api
~~~~~~~~~~~~~~~~~
Pure Python API for comparing snapshots outside Blender.

This module is the core of the headless/CI feature. It has:
  - Zero bpy imports
  - No argparse / CLI concerns
  - No side effects — all functions return data, callers decide what to do

Intended usage:

	# In a script or CI pipeline
	from blendiff.cli.api import compare_snapshots, list_snapshots

	snapshots = list_snapshots("my_scene.blendiff")
	result = compare_snapshots("my_scene.blendiff", "snap_id_a", "snap_id_b")
	print(result["summary"])

	# Or by label instead of ID
	result = compare_snapshots_by_label(
		"my_scene.blendiff", "Last approved", "Current"
	)
"""

from __future__ import annotations

import os
from typing import Optional

from ..storage.sidecar import SidecarManager, Snapshot
from ..diff_engine.diff_engine import DiffEngine


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_snapshots(sidecar_path: str) -> list[dict]:
	"""
	List all snapshots in a .blendiff sidecar file.

	Parameters
	----------
	sidecar_path:
		Path to the .blendiff file.

	Returns
	-------
	list of dicts with keys: id, label, timestamp, scene_name
	Data field is excluded for brevity.

	Raises
	------
	FileNotFoundError if sidecar_path does not exist.
	"""
	_require_sidecar(sidecar_path)
	mgr = _manager_for_sidecar(sidecar_path)
	snapshots = mgr.list_snapshots()
	return [
		{
			"id": s.id,
			"label": s.label,
			"timestamp": s.timestamp,
			"timestamp_display": s.timestamp_display(),
			"scene_name": s.scene_name,
		}
		for s in snapshots
	]


def compare_snapshots(
	sidecar_path: str,
	snapshot_id_a: str,
	snapshot_id_b: str,
) -> dict:
	"""
	Diff two snapshots by UUID.

	Parameters
	----------
	sidecar_path:
		Path to the .blendiff file.
	snapshot_id_a:
		UUID of the base snapshot (the "before").
	snapshot_id_b:
		UUID of the target snapshot (the "after").

	Returns
	-------
	dict with keys:
		summary        — human-readable summary string
		added_objects  — list of names
		removed_objects — list of names
		modified_objects — list of {name, changes: [{property_path, old_value, new_value}]}
		collection_diffs — list of {path, kind, changes}
		has_changes    — bool
		snapshot_a     — {id, label, timestamp}
		snapshot_b     — {id, label, timestamp}

	Raises
	------
	FileNotFoundError if sidecar_path does not exist.
	ValueError if either snapshot ID is not found.
	"""
	_require_sidecar(sidecar_path)
	mgr = _manager_for_sidecar(sidecar_path)

	snap_a = mgr.get_snapshot(snapshot_id_a)
	snap_b = mgr.get_snapshot(snapshot_id_b)

	if snap_a is None:
		raise ValueError(f"Snapshot not found: {snapshot_id_a}")
	if snap_b is None:
		raise ValueError(f"Snapshot not found: {snapshot_id_b}")

	return _run_diff(snap_a, snap_b)


def compare_snapshots_by_label(
	sidecar_path: str,
	label_a: str,
	label_b: str,
) -> dict:
	"""
	Diff two snapshots by label.

	If multiple snapshots share a label, the most recent one is used.

	Parameters
	----------
	sidecar_path:
		Path to the .blendiff file.
	label_a:
		Label of the base snapshot.
	label_b:
		Label of the target snapshot.

	Returns
	-------
	Same structure as compare_snapshots().

	Raises
	------
	FileNotFoundError if sidecar_path does not exist.
	ValueError if either label is not found.
	"""
	_require_sidecar(sidecar_path)
	mgr = _manager_for_sidecar(sidecar_path)

	# list_snapshots() returns newest-first, so first match = most recent
	all_snapshots = mgr.list_snapshots()

	snap_a = _find_by_label(all_snapshots, label_a)
	snap_b = _find_by_label(all_snapshots, label_b)

	if snap_a is None:
		raise ValueError(f"No snapshot found with label: '{label_a}'")
	if snap_b is None:
		raise ValueError(f"No snapshot found with label: '{label_b}'")

	return _run_diff(snap_a, snap_b)


def compare_latest_two(sidecar_path: str) -> dict:
	"""
	Diff the two most recent snapshots.

	Useful for CI: "what changed since the last snapshot?"

	Raises
	------
	FileNotFoundError if sidecar_path does not exist.
	ValueError if fewer than 2 snapshots exist.
	"""
	_require_sidecar(sidecar_path)
	mgr = _manager_for_sidecar(sidecar_path)
	snapshots = mgr.list_snapshots()  # newest first

	if len(snapshots) < 2:
		raise ValueError(
			f"Need at least 2 snapshots to diff, found {len(snapshots)}."
		)

	# newest = snapshots[0], second-newest = snapshots[1]
	# We diff second-newest → newest (chronological order)
	return _run_diff(snapshots[1], snapshots[0])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _manager_for_sidecar(sidecar_path: str) -> SidecarManager:
	"""
	Build a SidecarManager from a direct sidecar path.

	SidecarManager normally derives the sidecar path from a .blend path.
	Here we already have the sidecar path, so we reconstruct a fake blend
	path just for the manager's internal use — the actual file it reads
	is set directly.
	"""
	# Derive a synthetic blend path so SidecarManager is satisfied
	base = sidecar_path
	if base.endswith(".blendiff"):
		base = base[: -len(".blendiff")]
	blend_path = base + ".blend"

	mgr = SidecarManager(blend_path)
	# Override the sidecar path to use the actual file given
	mgr._sidecar_path = sidecar_path
	return mgr


def _require_sidecar(sidecar_path: str) -> None:
	if not os.path.exists(sidecar_path):
		raise FileNotFoundError(f"Sidecar file not found: {sidecar_path}")


def _find_by_label(snapshots: list[Snapshot], label: str) -> Optional[Snapshot]:
	"""Return the first (most recent) snapshot matching label."""
	for s in snapshots:
		if s.label == label:
			return s
	return None


def _run_diff(snap_a: Snapshot, snap_b: Snapshot) -> dict:
	"""Run DiffEngine on two Snapshot objects and return a result dict."""
	engine = DiffEngine()
	diff = engine.compare(snap_a.data, snap_b.data)
	s = diff.summary()

	return {
		"summary": (
			f"Added: {s['added']}  Removed: {s['removed']}  "
			f"Modified: {s['modified']}  Collections: {s['collection_changes']}"
		),
		"has_changes": diff.has_changes,
		"added_objects": [o.name for o in diff.added_objects],
		"removed_objects": [o.name for o in diff.removed_objects],
		"modified_objects": [
			{
				"name": o.name,
				"changes": [
					{
						"property_path": c.property_path,
						"old_value": c.old_value,
						"new_value": c.new_value,
					}
					for c in o.changes
				],
			}
			for o in diff.modified_objects
		],
		"collection_diffs": [
			{
				"path": cd.path,
				"kind": cd.kind.value,
				"changes": [
					{
						"property_path": c.property_path,
						"old_value": c.old_value,
						"new_value": c.new_value,
					}
					for c in cd.changes
				],
			}
			for cd in diff.collection_diffs
		],
		"snapshot_a": {
			"id": snap_a.id,
			"label": snap_a.label,
			"timestamp": snap_a.timestamp_display(),
		},
		"snapshot_b": {
			"id": snap_b.id,
			"label": snap_b.label,
			"timestamp": snap_b.timestamp_display(),
		},
	}
