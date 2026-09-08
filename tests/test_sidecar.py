"""
tests/test_sidecar.py

Unit tests for storage/sidecar.py.
No bpy required — runs with plain pytest.
"""

import json
import os
import tempfile
import pytest
from unittest.mock import patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.storage.sidecar import (
	SidecarManager, Snapshot, SIDECAR_EXTENSION, SIDECAR_VERSION,
)
from blendiff.data_model.schema import SCHEMA_VERSION


# Fixtures

MOCK_SCENE = {
	"blender_version": [4, 0, 0],
	"scene_name": "Scene",
	"objects": {
		"Cube": {
			"name": "Cube",
			"type": "MESH",
			"collection_path": "Scene Collection/Collection",
			"transform": {
				"location": [0.0, 0.0, 0.0],
				"rotation_euler": [0.0, 0.0, 0.0],
				"scale": [1.0, 1.0, 1.0],
			},
			"material_slots": [],
			"visible": True,
		}
	},
	"collections": {},
}


@pytest.fixture
def blend_file(tmp_path):
	"""A fake .blend filepath inside a temp dir."""
	return str(tmp_path / "my_scene.blend")


@pytest.fixture
def mgr(blend_file):
	return SidecarManager(blend_file)


# SidecarManager.is_available

class TestIsAvailable:
	def test_available_when_filepath_given(self, blend_file):
		mgr = SidecarManager(blend_file)
		assert mgr.is_available is True

	def test_not_available_when_empty_filepath(self):
		mgr = SidecarManager("")
		assert mgr.is_available is False

	def test_sidecar_path_uses_blendiff_extension(self, blend_file):
		mgr = SidecarManager(blend_file)
		assert mgr.sidecar_path.endswith(SIDECAR_EXTENSION)

	def test_sidecar_path_none_for_unsaved(self):
		mgr = SidecarManager("")
		assert mgr.sidecar_path is None


# list_snapshots / snapshot_count — empty state

class TestEmptyState:
	def test_list_snapshots_empty_when_no_sidecar(self, mgr):
		assert mgr.list_snapshots() == []

	def test_snapshot_count_zero_when_no_sidecar(self, mgr):
		assert mgr.snapshot_count() == 0


# save_snapshot

class TestSaveSnapshot:
	def test_save_creates_sidecar_file(self, mgr, blend_file):
		mgr.save_snapshot("Before rigging", "Scene", MOCK_SCENE)
		expected_path = blend_file.replace(".blend", SIDECAR_EXTENSION)
		assert os.path.exists(expected_path)

	def test_save_returns_snapshot_with_correct_label(self, mgr):
		snap = mgr.save_snapshot("Before rigging", "Scene", MOCK_SCENE)
		assert snap.label == "Before rigging"

	def test_save_returns_snapshot_with_uuid(self, mgr):
		snap = mgr.save_snapshot("Test", "Scene", MOCK_SCENE)
		assert len(snap.id) == 36  # UUID4 format

	def test_save_returns_snapshot_with_scene_name(self, mgr):
		snap = mgr.save_snapshot("Test", "MyScene", MOCK_SCENE)
		assert snap.scene_name == "MyScene"

	def test_save_increments_count(self, mgr):
		mgr.save_snapshot("A", "Scene", MOCK_SCENE)
		mgr.save_snapshot("B", "Scene", MOCK_SCENE)
		assert mgr.snapshot_count() == 2

	def test_save_persists_data(self, mgr, blend_file):
		mgr.save_snapshot("Checkpoint", "Scene", MOCK_SCENE)
		# Re-create manager to force re-read from disk
		mgr2 = SidecarManager(blend_file)
		snapshots = mgr2.list_snapshots()
		assert len(snapshots) == 1
		assert snapshots[0].label == "Checkpoint"

	def test_save_raises_for_unsaved_blend(self):
		mgr = SidecarManager("")
		with pytest.raises(RuntimeError, match="not been saved"):
			mgr.save_snapshot("Test", "Scene", MOCK_SCENE)

	def test_sidecar_is_valid_json(self, mgr, blend_file):
		mgr.save_snapshot("Test", "Scene", MOCK_SCENE)
		sidecar_path = blend_file.replace(".blend", SIDECAR_EXTENSION)
		with open(sidecar_path) as f:
			data = json.load(f)
		assert "snapshots" in data
		assert data["blendiff_version"] == SIDECAR_VERSION


# get_snapshot

class TestGetSnapshot:
	def test_get_existing_snapshot(self, mgr):
		snap = mgr.save_snapshot("Test", "Scene", MOCK_SCENE)
		retrieved = mgr.get_snapshot(snap.id)
		assert retrieved is not None
		assert retrieved.id == snap.id
		assert retrieved.label == "Test"

	def test_get_nonexistent_returns_none(self, mgr):
		result = mgr.get_snapshot("00000000-0000-0000-0000-000000000000")
		assert result is None

	def test_get_preserves_scene_data(self, mgr):
		snap = mgr.save_snapshot("Test", "Scene", MOCK_SCENE)
		retrieved = mgr.get_snapshot(snap.id)
		assert retrieved.data["scene_name"] == "Scene"
		assert "Cube" in retrieved.data["objects"]


# delete_snapshot

class TestDeleteSnapshot:
	def test_delete_existing_returns_true(self, mgr):
		snap = mgr.save_snapshot("ToDelete", "Scene", MOCK_SCENE)
		assert mgr.delete_snapshot(snap.id) is True

	def test_delete_nonexistent_returns_false(self, mgr):
		assert mgr.delete_snapshot("00000000-0000-0000-0000-000000000000") is False

	def test_delete_removes_from_list(self, mgr):
		snap = mgr.save_snapshot("ToDelete", "Scene", MOCK_SCENE)
		mgr.delete_snapshot(snap.id)
		assert mgr.snapshot_count() == 0

	def test_delete_only_removes_target(self, mgr):
		snap_a = mgr.save_snapshot("Keep", "Scene", MOCK_SCENE)
		snap_b = mgr.save_snapshot("Delete", "Scene", MOCK_SCENE)
		mgr.delete_snapshot(snap_b.id)
		remaining = mgr.list_snapshots()
		assert len(remaining) == 1
		assert remaining[0].id == snap_a.id

	def test_delete_raises_for_unsaved_blend(self):
		mgr = SidecarManager("")
		with pytest.raises(RuntimeError):
			mgr.delete_snapshot("any-id")


# rename_snapshot

class TestRenameSnapshot:
	def test_rename_existing_returns_true(self, mgr):
		snap = mgr.save_snapshot("Old Label", "Scene", MOCK_SCENE)
		assert mgr.rename_snapshot(snap.id, "New Label") is True

	def test_rename_updates_label(self, mgr, blend_file):
		snap = mgr.save_snapshot("Old Label", "Scene", MOCK_SCENE)
		mgr.rename_snapshot(snap.id, "New Label")
		mgr2 = SidecarManager(blend_file)
		retrieved = mgr2.get_snapshot(snap.id)
		assert retrieved.label == "New Label"

	def test_rename_nonexistent_returns_false(self, mgr):
		assert mgr.rename_snapshot("nonexistent", "Label") is False


# list_snapshots ordering

class TestOrdering:
	def test_list_returns_newest_first(self, mgr):
		mgr.save_snapshot("First", "Scene", MOCK_SCENE)
		mgr.save_snapshot("Second", "Scene", MOCK_SCENE)
		mgr.save_snapshot("Third", "Scene", MOCK_SCENE)
		snapshots = mgr.list_snapshots()
		# Newest first
		assert snapshots[0].label == "Third"
		assert snapshots[2].label == "First"


# Snapshot dataclass

class TestSnapshotDataclass:
	def test_create_sets_all_fields(self):
		snap = Snapshot.create("Label", "Scene", MOCK_SCENE)
		assert snap.label == "Label"
		assert snap.scene_name == "Scene"
		assert snap.data == MOCK_SCENE
		assert len(snap.id) == 36

	def test_roundtrip_to_from_dict(self):
		snap = Snapshot.create("Test", "Scene", MOCK_SCENE)
		d = snap.to_dict()
		restored = Snapshot.from_dict(d)
		assert restored.id == snap.id
		assert restored.label == snap.label
		assert restored.scene_name == snap.scene_name

	def test_roundtrip_preserves_scene_content(self):
		"""
		Loading migrates the scene forward, so data is not byte-identical —
		but every field the snapshot actually stored survives untouched.
		"""
		snap = Snapshot.create("Test", "Scene", MOCK_SCENE)
		restored = Snapshot.from_dict(snap.to_dict())
		for key, value in MOCK_SCENE.items():
			assert restored.data[key] == value

	def test_roundtrip_without_migration_is_identical(self):
		snap = Snapshot.create("Test", "Scene", MOCK_SCENE)
		restored = Snapshot.from_dict(snap.to_dict(), migrate=False)
		assert restored.data == snap.data

	def test_load_migrates_legacy_scene_data(self):
		snap = Snapshot.create("Test", "Scene", MOCK_SCENE)
		restored = Snapshot.from_dict(snap.to_dict())
		assert restored.schema_version == SCHEMA_VERSION

	def test_timestamp_display_is_string(self):
		snap = Snapshot.create("Test", "Scene", MOCK_SCENE)
		display = snap.timestamp_display()
		assert isinstance(display, str)
		assert len(display) > 0


# Corrupted sidecar graceful handling

class TestCorruptedSidecar:
	def test_corrupted_sidecar_returns_empty_list(self, blend_file):
		sidecar_path = blend_file.replace(".blend", SIDECAR_EXTENSION)
		with open(sidecar_path, "w") as f:
			f.write("this is not valid json {{{")

		mgr = SidecarManager(blend_file)
		# Should not raise — returns empty
		assert mgr.list_snapshots() == []

	def test_can_save_after_corruption(self, blend_file):
		sidecar_path = blend_file.replace(".blend", SIDECAR_EXTENSION)
		with open(sidecar_path, "w") as f:
			f.write("corrupted")

		mgr = SidecarManager(blend_file)
		snap = mgr.save_snapshot("Recovery", "Scene", MOCK_SCENE)
		assert snap.label == "Recovery"

# Atomic writes

class TestAtomicWrite:
	"""
	The sidecar holds the user's entire snapshot history, so a partial write
	must never be observable. These tests assert the write is all-or-nothing.
	"""

	def test_failed_write_leaves_original_intact(self, mgr, blend_file):
		mgr.save_snapshot("Good", "Scene", MOCK_SCENE)
		sidecar_path = blend_file.replace(".blend", SIDECAR_EXTENSION)
		with open(sidecar_path) as f:
			before = f.read()

		# Fail midway through serialising the replacement payload.
		with patch("json.dump", side_effect=OSError("disk full")):
			with pytest.raises(OSError):
				mgr.save_snapshot("Bad", "Scene", MOCK_SCENE)

		with open(sidecar_path) as f:
			after = f.read()
		assert after == before

	def test_failed_write_leaves_no_temp_files(self, mgr, blend_file):
		mgr.save_snapshot("Good", "Scene", MOCK_SCENE)
		directory = os.path.dirname(os.path.abspath(blend_file))

		with patch("json.dump", side_effect=OSError("disk full")):
			with pytest.raises(OSError):
				mgr.save_snapshot("Bad", "Scene", MOCK_SCENE)

		leftovers = [f for f in os.listdir(directory) if f.startswith(".blendiff-")]
		assert leftovers == []

	def test_history_survives_failed_write(self, mgr):
		mgr.save_snapshot("First", "Scene", MOCK_SCENE)
		mgr.save_snapshot("Second", "Scene", MOCK_SCENE)

		with patch("json.dump", side_effect=OSError("disk full")):
			with pytest.raises(OSError):
				mgr.save_snapshot("Third", "Scene", MOCK_SCENE)

		labels = {s.label for s in mgr.list_snapshots()}
		assert labels == {"First", "Second"}

	def test_write_upgrades_stored_sidecar_version(self, mgr, blend_file):
		mgr.save_snapshot("Test", "Scene", MOCK_SCENE)
		sidecar_path = blend_file.replace(".blend", SIDECAR_EXTENSION)
		with open(sidecar_path) as f:
			assert json.load(f)["blendiff_version"] == SIDECAR_VERSION


# Schema migration through the manager

class TestSidecarMigration:
	def test_outdated_snapshots_are_reported(self, mgr, blend_file):
		mgr.save_snapshot("Legacy", "Scene", MOCK_SCENE)
		_downgrade_stored_snapshots(blend_file)
		assert len(mgr.outdated_snapshot_ids()) == 1

	def test_migrate_file_upgrades_snapshots(self, mgr, blend_file):
		mgr.save_snapshot("Legacy", "Scene", MOCK_SCENE)
		_downgrade_stored_snapshots(blend_file)

		assert mgr.migrate_file() == 1
		assert mgr.outdated_snapshot_ids() == []

	def test_migrate_file_is_idempotent(self, mgr, blend_file):
		mgr.save_snapshot("Legacy", "Scene", MOCK_SCENE)
		_downgrade_stored_snapshots(blend_file)

		mgr.migrate_file()
		assert mgr.migrate_file() == 0

	def test_snapshots_load_migrated(self, mgr, blend_file):
		mgr.save_snapshot("Legacy", "Scene", MOCK_SCENE)
		_downgrade_stored_snapshots(blend_file)

		snap = mgr.list_snapshots()[0]
		assert snap.schema_version == SCHEMA_VERSION


def _downgrade_stored_snapshots(blend_file):
	"""Strip schema markers from the file, simulating a pre-0.6 sidecar."""
	sidecar_path = blend_file.replace(".blend", SIDECAR_EXTENSION)
	with open(sidecar_path) as f:
		data = json.load(f)
	for snap in data["snapshots"]:
		snap["data"].pop("schema_version", None)
		snap["data"].pop("captured_domains", None)
		snap["data"].pop("transform_space", None)
	with open(sidecar_path, "w") as f:
		json.dump(data, f)


# Content-addressed storage

class TestDeduplication:
	"""
	Snapshots share one object pool, so an object untouched across many
	snapshots is written once rather than once per snapshot. Before this,
	80 objects across 50 snapshots cost 24.6 MB and a 280 ms parse, paid every
	time the snapshot list was drawn.
	"""

	def _scene(self, objects):
		return {
			"objects": objects,
			"collections": {},
			"scene_name": "Scene",
			"schema_version": SCHEMA_VERSION,
			"captured_domains": ["objects"],
			"transform_space": "local",
		}

	def _obj(self, name, **extra):
		data = {"name": name, "type": "MESH", "transform": {"location": [0, 0, 0]}}
		data.update(extra)
		return data

	def _pool(self, blend_file):
		with open(blend_file.replace(".blend", SIDECAR_EXTENSION)) as f:
			return json.load(f).get("objects", {})

	def test_repeated_snapshots_do_not_duplicate_objects(self, mgr, blend_file):
		scene = self._scene({"Cube": self._obj("Cube")})
		for i in range(10):
			mgr.save_snapshot(f"snap{i}", "Scene", scene)

		assert len(self._pool(blend_file)) == 1

	def test_changed_object_adds_one_entry(self, mgr, blend_file):
		mgr.save_snapshot("a", "Scene", self._scene({"Cube": self._obj("Cube")}))
		mgr.save_snapshot("b", "Scene",
		                  self._scene({"Cube": self._obj("Cube", moved=True)}))

		assert len(self._pool(blend_file)) == 2

	def test_round_trip_returns_full_objects(self, mgr):
		scene = self._scene({"Cube": self._obj("Cube"), "Lamp": self._obj("Lamp")})
		mgr.save_snapshot("a", "Scene", scene)

		loaded = mgr.list_snapshots()[0]
		assert loaded.data["objects"]["Cube"]["type"] == "MESH"
		assert set(loaded.data["objects"]) == {"Cube", "Lamp"}

	def test_get_snapshot_also_rehydrates(self, mgr):
		snap = mgr.save_snapshot("a", "Scene",
		                         self._scene({"Cube": self._obj("Cube")}))
		fetched = mgr.get_snapshot(snap.id)
		assert fetched.data["objects"]["Cube"]["name"] == "Cube"

	def test_saved_snapshot_keeps_inline_data_for_the_caller(self, mgr):
		"""Packing is a storage detail; the returned snapshot is a real scene."""
		scene = self._scene({"Cube": self._obj("Cube")})
		snap = mgr.save_snapshot("a", "Scene", scene)
		assert snap.data["objects"]["Cube"]["type"] == "MESH"

	def test_deleting_a_snapshot_reclaims_its_objects(self, mgr, blend_file):
		mgr.save_snapshot("keep", "Scene", self._scene({"Cube": self._obj("Cube")}))
		doomed = mgr.save_snapshot(
			"drop", "Scene", self._scene({"Gone": self._obj("Gone")}))
		assert len(self._pool(blend_file)) == 2

		mgr.delete_snapshot(doomed.id)
		assert len(self._pool(blend_file)) == 1

	def test_shared_object_survives_deleting_one_snapshot(self, mgr):
		scene = self._scene({"Cube": self._obj("Cube")})
		first = mgr.save_snapshot("a", "Scene", scene)
		mgr.save_snapshot("b", "Scene", scene)

		mgr.delete_snapshot(first.id)
		remaining = mgr.list_snapshots()[0]
		assert remaining.data["objects"]["Cube"]["name"] == "Cube"

	def test_deleting_everything_empties_the_pool(self, mgr, blend_file):
		snap = mgr.save_snapshot("a", "Scene",
		                         self._scene({"Cube": self._obj("Cube")}))
		mgr.delete_snapshot(snap.id)
		assert self._pool(blend_file) == {}

	def test_legacy_inline_sidecar_is_packed_on_next_write(self, mgr, blend_file):
		"""A pre-0.3 sidecar must open, and shrink the first time it is saved."""
		path = blend_file.replace(".blend", SIDECAR_EXTENSION)
		legacy = {
			"blendiff_version": "0.2",
			"blend_file": "scene.blend",
			"snapshots": [{
				"id": "old-1", "label": "legacy", "timestamp": "2020-01-01T00:00:00+00:00",
				"scene_name": "Scene",
				"data": self._scene({"Cube": self._obj("Cube")}),
			}],
		}
		with open(path, "w") as f:
			json.dump(legacy, f)

		# Readable as-is.
		assert mgr.list_snapshots()[0].data["objects"]["Cube"]["type"] == "MESH"

		# And packed once anything is written.
		mgr.save_snapshot("new", "Scene", self._scene({"Cube": self._obj("Cube")}))
		assert len(self._pool(blend_file)) == 1

	def test_storage_stats_report_savings(self, mgr):
		scene = self._scene({"Cube": self._obj("Cube")})
		for i in range(5):
			mgr.save_snapshot(f"snap{i}", "Scene", scene)

		stats = mgr.storage_stats()
		assert stats["stored"] == 1
		assert stats["references"] == 5
		assert stats["saved"] == 4

	def _heavy_obj(self, name):
		"""
		An object of realistic weight.

		Deduplication replaces an object with a 32-character digest, so the
		saving is proportional to how big the object was. Real objects carry
		material node graphs and run to kilobytes; a three-field stub would
		make the reference cost as much as the object and understate the
		feature to the point of measuring nothing.
		"""
		return {
			"name": name,
			"type": "MESH",
			"transform": {"location": [0, 0, 0], "rotation_euler": [0, 0, 0],
			              "scale": [1, 1, 1], "rotation_mode": "XYZ"},
			"material_slots": [{
				"index": 0, "name": "Material", "use_nodes": True,
				"node_graph": {"nodes": {
					f"node{n}": {"type": "BSDF_PRINCIPLED",
					             "inputs": {f"in{i}": 0.5 for i in range(8)}}
					for n in range(12)
				}},
			}],
			"mesh_data": {"vertex_count": 5000, "vertex_hash": "a" * 32},
		}

	def test_repeated_snapshots_grow_sublinearly(self, mgr, blend_file):
		"""End to end: repeated snapshots must not multiply the file size."""
		scene = self._scene({f"Obj{i}": self._heavy_obj(f"Obj{i}") for i in range(20)})
		mgr.save_snapshot("first", "Scene", scene)
		one = os.path.getsize(blend_file.replace(".blend", SIDECAR_EXTENSION))

		for i in range(9):
			mgr.save_snapshot(f"more{i}", "Scene", scene)
		ten = os.path.getsize(blend_file.replace(".blend", SIDECAR_EXTENSION))

		# Ten identical snapshots pay for one copy of the objects plus nine
		# sets of references, nowhere near ten full copies.
		assert ten < one * 2, f"expected sublinear growth, got {one} -> {ten}"

	def test_edited_snapshot_costs_only_the_edit(self, mgr, blend_file):
		"""Changing one object of twenty must not rewrite the other nineteen."""
		objects = {f"Obj{i}": self._heavy_obj(f"Obj{i}") for i in range(20)}
		mgr.save_snapshot("before", "Scene", self._scene(objects))
		one = os.path.getsize(blend_file.replace(".blend", SIDECAR_EXTENSION))

		edited = dict(objects)
		edited["Obj0"] = {**self._heavy_obj("Obj0"), "moved": True}
		mgr.save_snapshot("after", "Scene", self._scene(edited))
		two = os.path.getsize(blend_file.replace(".blend", SIDECAR_EXTENSION))

		# The second snapshot adds one object plus a reference map, so growth
		# should be a small fraction of a full second copy.
		growth = (two - one) / one
		assert growth < 0.35, f"second snapshot grew the file by {growth:.0%}"
