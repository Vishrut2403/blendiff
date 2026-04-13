"""
tests/test_cli_api.py

Unit tests for cli/api.py and cli/__main__.py.
No bpy required — runs with plain pytest.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.cli.api import (
	list_snapshots,
	compare_snapshots,
	compare_snapshots_by_label,
	compare_latest_two,
)
from blendiff.storage.sidecar import SidecarManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCENE_A = {
	"blender_version": "5.1.0",
	"scene_name": "Scene",
	"objects": {
		"Cube": {
			"name": "Cube",
			"type": "MESH",
			"collection_path": "Collection",
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

SCENE_B = {
	"blender_version": "5.1.0",
	"scene_name": "Scene",
	"objects": {
		"Cube": {
			"name": "Cube",
			"type": "MESH",
			"collection_path": "Collection",
			"transform": {
				"location": [1.0, 2.0, 3.0],
				"rotation_euler": [0.0, 0.0, 0.0],
				"scale": [1.0, 1.0, 1.0],
			},
			"material_slots": [],
			"visible": True,
		},
		"Sphere": {
			"name": "Sphere",
			"type": "MESH",
			"collection_path": "Collection",
			"transform": {
				"location": [0.0, 0.0, 0.0],
				"rotation_euler": [0.0, 0.0, 0.0],
				"scale": [1.0, 1.0, 1.0],
			},
			"material_slots": [],
			"visible": True,
		},
	},
	"collections": {},
}

SCENE_C = {
	"blender_version": "5.1.0",
	"scene_name": "Scene",
	"objects": {},
	"collections": {},
}


@pytest.fixture
def sidecar_path(tmp_path):
	"""A populated .blendiff sidecar with 3 snapshots."""
	blend = str(tmp_path / "scene.blend")
	mgr = SidecarManager(blend)
	mgr.save_snapshot("Initial", "Scene", SCENE_A)
	mgr.save_snapshot("Added Sphere", "Scene", SCENE_B)
	mgr.save_snapshot("Empty Scene", "Scene", SCENE_C)
	return mgr.sidecar_path


@pytest.fixture
def empty_sidecar_path(tmp_path):
	"""A .blendiff sidecar with no snapshots."""
	blend = str(tmp_path / "empty.blend")
	mgr = SidecarManager(blend)
	# Touch the file by saving and deleting
	snap = mgr.save_snapshot("temp", "Scene", SCENE_A)
	mgr.delete_snapshot(snap.id)
	return mgr.sidecar_path


# ---------------------------------------------------------------------------
# list_snapshots
# ---------------------------------------------------------------------------

class TestListSnapshots:
	def test_returns_list(self, sidecar_path):
		result = list_snapshots(sidecar_path)
		assert isinstance(result, list)

	def test_correct_count(self, sidecar_path):
		result = list_snapshots(sidecar_path)
		assert len(result) == 3

	def test_contains_expected_keys(self, sidecar_path):
		result = list_snapshots(sidecar_path)
		for snap in result:
			assert "id" in snap
			assert "label" in snap
			assert "timestamp" in snap
			assert "timestamp_display" in snap
			assert "scene_name" in snap

	def test_no_data_field(self, sidecar_path):
		# data field should be excluded for brevity
		result = list_snapshots(sidecar_path)
		for snap in result:
			assert "data" not in snap

	def test_newest_first(self, sidecar_path):
		result = list_snapshots(sidecar_path)
		assert result[0]["label"] == "Empty Scene"
		assert result[2]["label"] == "Initial"

	def test_empty_sidecar(self, empty_sidecar_path):
		result = list_snapshots(empty_sidecar_path)
		assert result == []

	def test_missing_sidecar_raises(self, tmp_path):
		with pytest.raises(FileNotFoundError):
			list_snapshots(str(tmp_path / "nonexistent.blendiff"))


# ---------------------------------------------------------------------------
# compare_snapshots (by ID)
# ---------------------------------------------------------------------------

class TestCompareSnapshots:
	def test_returns_dict(self, sidecar_path):
		snaps = list_snapshots(sidecar_path)
		result = compare_snapshots(sidecar_path, snaps[2]["id"], snaps[1]["id"])
		assert isinstance(result, dict)

	def test_contains_expected_keys(self, sidecar_path):
		snaps = list_snapshots(sidecar_path)
		result = compare_snapshots(sidecar_path, snaps[2]["id"], snaps[1]["id"])
		for key in ("summary", "has_changes", "added_objects", "removed_objects",
					"modified_objects", "collection_diffs", "snapshot_a", "snapshot_b"):
			assert key in result

	def test_detects_added_object(self, sidecar_path):
		snaps = list_snapshots(sidecar_path)
		# Initial → Added Sphere
		id_initial = next(s["id"] for s in snaps if s["label"] == "Initial")
		id_added = next(s["id"] for s in snaps if s["label"] == "Added Sphere")
		result = compare_snapshots(sidecar_path, id_initial, id_added)
		assert "Sphere" in result["added_objects"]

	def test_detects_modified_object(self, sidecar_path):
		snaps = list_snapshots(sidecar_path)
		id_initial = next(s["id"] for s in snaps if s["label"] == "Initial")
		id_added = next(s["id"] for s in snaps if s["label"] == "Added Sphere")
		result = compare_snapshots(sidecar_path, id_initial, id_added)
		modified_names = [o["name"] for o in result["modified_objects"]]
		assert "Cube" in modified_names

	def test_has_changes_true_when_different(self, sidecar_path):
		snaps = list_snapshots(sidecar_path)
		id_initial = next(s["id"] for s in snaps if s["label"] == "Initial")
		id_added = next(s["id"] for s in snaps if s["label"] == "Added Sphere")
		result = compare_snapshots(sidecar_path, id_initial, id_added)
		assert result["has_changes"] is True

	def test_has_changes_false_when_identical(self, sidecar_path):
		snaps = list_snapshots(sidecar_path)
		id_initial = next(s["id"] for s in snaps if s["label"] == "Initial")
		result = compare_snapshots(sidecar_path, id_initial, id_initial)
		assert result["has_changes"] is False

	def test_snapshot_metadata_present(self, sidecar_path):
		snaps = list_snapshots(sidecar_path)
		id_initial = next(s["id"] for s in snaps if s["label"] == "Initial")
		id_added = next(s["id"] for s in snaps if s["label"] == "Added Sphere")
		result = compare_snapshots(sidecar_path, id_initial, id_added)
		assert result["snapshot_a"]["label"] == "Initial"
		assert result["snapshot_b"]["label"] == "Added Sphere"

	def test_missing_snapshot_id_raises(self, sidecar_path):
		with pytest.raises(ValueError, match="not found"):
			compare_snapshots(sidecar_path, "00000000-0000-0000-0000-000000000000", "anything")

	def test_missing_sidecar_raises(self, tmp_path):
		with pytest.raises(FileNotFoundError):
			compare_snapshots(str(tmp_path / "none.blendiff"), "a", "b")


# ---------------------------------------------------------------------------
# compare_snapshots_by_label
# ---------------------------------------------------------------------------

class TestCompareSnapshotsByLabel:
	def test_basic_diff_by_label(self, sidecar_path):
		result = compare_snapshots_by_label(sidecar_path, "Initial", "Added Sphere")
		assert result["has_changes"] is True

	def test_added_object_detected(self, sidecar_path):
		result = compare_snapshots_by_label(sidecar_path, "Initial", "Added Sphere")
		assert "Sphere" in result["added_objects"]

	def test_removed_objects_detected(self, sidecar_path):
		result = compare_snapshots_by_label(sidecar_path, "Added Sphere", "Empty Scene")
		assert "Cube" in result["removed_objects"]
		assert "Sphere" in result["removed_objects"]

	def test_identical_labels_no_changes(self, sidecar_path):
		result = compare_snapshots_by_label(sidecar_path, "Initial", "Initial")
		assert result["has_changes"] is False

	def test_missing_label_a_raises(self, sidecar_path):
		with pytest.raises(ValueError, match="Initial Nonexistent"):
			compare_snapshots_by_label(sidecar_path, "Initial Nonexistent", "Added Sphere")

	def test_missing_label_b_raises(self, sidecar_path):
		with pytest.raises(ValueError, match="Nonexistent"):
			compare_snapshots_by_label(sidecar_path, "Initial", "Nonexistent")

	def test_summary_is_string(self, sidecar_path):
		result = compare_snapshots_by_label(sidecar_path, "Initial", "Added Sphere")
		assert isinstance(result["summary"], str)
		assert "Added:" in result["summary"]

	def test_property_changes_present(self, sidecar_path):
		result = compare_snapshots_by_label(sidecar_path, "Initial", "Added Sphere")
		cube = next(o for o in result["modified_objects"] if o["name"] == "Cube")
		paths = [c["property_path"] for c in cube["changes"]]
		assert "transform.location" in paths


# ---------------------------------------------------------------------------
# compare_latest_two
# ---------------------------------------------------------------------------

class TestCompareLatestTwo:
	def test_diffs_two_most_recent(self, sidecar_path):
		# Most recent = "Empty Scene", second most recent = "Added Sphere"
		result = compare_latest_two(sidecar_path)
		# Going from Added Sphere → Empty Scene: Cube and Sphere removed
		assert "Cube" in result["removed_objects"]
		assert "Sphere" in result["removed_objects"]

	def test_raises_if_fewer_than_two(self, tmp_path):
		blend = str(tmp_path / "scene.blend")
		mgr = SidecarManager(blend)
		mgr.save_snapshot("Only one", "Scene", SCENE_A)
		with pytest.raises(ValueError, match="at least 2"):
			compare_latest_two(mgr.sidecar_path)

	def test_raises_if_empty(self, empty_sidecar_path):
		with pytest.raises(ValueError, match="at least 2"):
			compare_latest_two(empty_sidecar_path)


# ---------------------------------------------------------------------------
# CLI __main__ integration tests
# ---------------------------------------------------------------------------

class TestCLIMain:
	def _run(self, argv: list[str]) -> tuple[int, str]:
		"""Run the CLI and capture stdout."""
		import io
		from contextlib import redirect_stdout
		from blendiff.cli.__main__ import main

		buf = io.StringIO()
		with redirect_stdout(buf):
			try:
				code = main(argv)
			except SystemExit as e:
				code = e.code
		return code, buf.getvalue()

	def test_list_command_exit_zero(self, sidecar_path):
		code, _ = self._run(["list", sidecar_path])
		assert code == 0

	def test_list_command_shows_labels(self, sidecar_path):
		_, output = self._run(["list", sidecar_path])
		assert "Initial" in output
		assert "Added Sphere" in output

	def test_list_json_flag(self, sidecar_path):
		_, output = self._run(["list", sidecar_path, "--json"])
		data = json.loads(output)
		assert isinstance(data, list)
		assert len(data) == 3

	def test_compare_exit_zero_when_changes(self, sidecar_path):
		code, _ = self._run(["compare", sidecar_path, "Initial", "Added Sphere"])
		assert code == 0

	def test_compare_fail_on_changes(self, sidecar_path):
		code, _ = self._run([
			"compare", sidecar_path, "Initial", "Added Sphere",
			"--fail-on-changes"
		])
		assert code == 1

	def test_compare_no_fail_when_identical(self, sidecar_path):
		code, _ = self._run([
			"compare", sidecar_path, "Initial", "Initial",
			"--fail-on-changes"
		])
		assert code == 0

	def test_compare_json_output(self, sidecar_path):
		_, output = self._run([
			"compare", sidecar_path, "Initial", "Added Sphere", "--json"
		])
		data = json.loads(output)
		assert "has_changes" in data
		assert data["has_changes"] is True

	def test_compare_html_output(self, sidecar_path, tmp_path):
		output_path = str(tmp_path / "report.html")
		code, _ = self._run([
			"compare", sidecar_path, "Initial", "Added Sphere",
			"--output", output_path
		])
		assert code == 0
		assert os.path.exists(output_path)
		with open(output_path) as f:
			assert "<!DOCTYPE html>" in f.read()

	def test_latest_command(self, sidecar_path):
		code, output = self._run(["latest", sidecar_path])
		assert code == 0

	def test_latest_fail_on_changes(self, sidecar_path):
		code, _ = self._run(["latest", sidecar_path, "--fail-on-changes"])
		assert code == 1

	def test_missing_sidecar_exits_2(self, tmp_path):
		code, _ = self._run(["list", str(tmp_path / "none.blendiff")])
		assert code == 2

	def test_missing_label_exits_2(self, sidecar_path):
		code, _ = self._run([
			"compare", sidecar_path, "Nonexistent", "Initial"
		])
		assert code == 2

	def test_compare_shows_summary(self, sidecar_path):
		_, output = self._run(["compare", sidecar_path, "Initial", "Added Sphere"])
		assert "Added:" in output

	def test_quiet_suppresses_output(self, sidecar_path):
		_, output = self._run([
			"compare", sidecar_path, "Initial", "Added Sphere", "--quiet"
		])
		assert output.strip() == ""
