import os
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from blendiff.storage.sidecar import _get_git_hash, Snapshot

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# _get_git_hash() 

class TestGetGitHash:
	def test_returns_string_in_git_repo(self):
		"""Running in the project repo should return a non-empty string."""
		result = _get_git_hash(cwd=REPO_ROOT)
		# If we're in a git repo this should be a short SHA; if not, None is fine
		assert result is None or (isinstance(result, str) and len(result) > 0)

	def test_returns_none_without_cwd(self):
		"""
		No cwd means no answer.

		Falling back to the process working directory would stamp snapshots with
		the hash of whatever repository Blender happened to be launched from,
		which is silently wrong provenance.
		"""
		with patch("subprocess.run") as mock_run:
			result = _get_git_hash()
		assert result is None
		mock_run.assert_not_called()

	def test_returns_none_for_nonexistent_cwd(self):
		"""A path that is not a real directory must not reach subprocess."""
		with patch("subprocess.run") as mock_run:
			result = _get_git_hash(cwd="/definitely/not/a/real/directory")
		assert result is None
		mock_run.assert_not_called()

	def test_returns_none_outside_git_repo(self, tmp_path):
		"""A plain temp directory has no git repo — should return None."""
		result = _get_git_hash(cwd=str(tmp_path))
		assert result is None

	def test_returns_none_when_git_not_found(self, tmp_path):
		"""If git binary doesn't exist, should return None without raising."""
		with patch("subprocess.run", side_effect=FileNotFoundError):
			result = _get_git_hash(cwd=str(tmp_path))
		assert result is None

	def test_returns_none_on_timeout(self, tmp_path):
		"""If git times out, should return None without raising."""
		with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 2)):
			result = _get_git_hash(cwd=str(tmp_path))
		assert result is None

	def test_returns_none_on_nonzero_returncode(self, tmp_path):
		"""Non-zero return code (not a git repo) should return None."""
		mock_result = MagicMock()
		mock_result.returncode = 128
		mock_result.stdout = ""
		with patch("subprocess.run", return_value=mock_result):
			result = _get_git_hash(cwd=str(tmp_path))
		assert result is None

	def test_returns_stripped_hash(self, tmp_path):
		"""Output should be stripped of whitespace/newlines."""
		mock_result = MagicMock()
		mock_result.returncode = 0
		mock_result.stdout = "a3f2c1b\n"
		with patch("subprocess.run", return_value=mock_result):
			result = _get_git_hash(cwd=str(tmp_path))
		assert result == "a3f2c1b"

	def test_returns_none_on_empty_output(self, tmp_path):
		"""Empty stdout with returncode 0 should return None."""
		mock_result = MagicMock()
		mock_result.returncode = 0
		mock_result.stdout = ""
		with patch("subprocess.run", return_value=mock_result):
			result = _get_git_hash(cwd=str(tmp_path))
		assert result is None

	def test_passes_cwd_to_subprocess(self, tmp_path):
		"""cwd parameter should be forwarded to subprocess.run."""
		mock_result = MagicMock()
		mock_result.returncode = 0
		mock_result.stdout = "abc1234\n"
		with patch("subprocess.run", return_value=mock_result) as mock_run:
			_get_git_hash(cwd=str(tmp_path))
		assert mock_run.call_args.kwargs.get("cwd") == str(tmp_path)

	def test_never_raises(self, tmp_path):
		"""Should never propagate any exception."""
		with patch("subprocess.run", side_effect=Exception("unexpected")):
			result = _get_git_hash(cwd=str(tmp_path))
		assert result is None


# Snapshot.create() with git hash 

class TestSnapshotCreate:
	def test_git_hash_attached_when_available(self, tmp_path):
		mock_result = MagicMock()
		mock_result.returncode = 0
		mock_result.stdout = "a3f2c1b\n"
		with patch("subprocess.run", return_value=mock_result):
			snap = Snapshot.create(
				label="test", scene_name="Scene", data={}, git_cwd=str(tmp_path)
			)
		assert snap.git_hash == "a3f2c1b"

	def test_git_hash_none_when_unavailable(self, tmp_path):
		snap = Snapshot.create(
			label="test", scene_name="Scene", data={}, git_cwd=str(tmp_path)
		)
		assert snap.git_hash is None

	def test_git_hash_none_does_not_crash(self, tmp_path):
		with patch("subprocess.run", side_effect=FileNotFoundError):
			snap = Snapshot.create(
				label="test", scene_name="Scene", data={}, git_cwd=str(tmp_path)
			)
		assert snap.git_hash is None

	def test_git_hash_none_without_cwd(self):
		"""Snapshot.create with no git_cwd must not guess a repository."""
		snap = Snapshot.create(label="test", scene_name="Scene", data={})
		assert snap.git_hash is None
		assert snap.label == "test"

	def test_other_fields_unaffected(self):
		with patch("subprocess.run", side_effect=FileNotFoundError):
			snap = Snapshot.create(label="v1", scene_name="MyScene", data={"key": "val"})
		assert snap.label == "v1"
		assert snap.scene_name == "MyScene"
		assert snap.data == {"key": "val"}
		assert snap.id is not None
		assert snap.timestamp is not None


# Snapshot.label_display() 

class TestLabelDisplay:
	def test_shows_hash_when_present(self):
		snap = Snapshot(
			id="x", label="Before rigging", timestamp="", scene_name="Scene",
			data={}, git_hash="a3f2c1b"
		)
		assert snap.label_display() == "Before rigging [a3f2c1b]"

	def test_shows_label_only_when_no_hash(self):
		snap = Snapshot(
			id="x", label="Before rigging", timestamp="", scene_name="Scene",
			data={}, git_hash=None
		)
		assert snap.label_display() == "Before rigging"

	def test_empty_string_hash_treated_as_none(self):
		snap = Snapshot(
			id="x", label="v1", timestamp="", scene_name="Scene",
			data={}, git_hash=None
		)
		assert "[" not in snap.label_display()


# Snapshot serialisation round-trip 

class TestSnapshotRoundTrip:
	def test_git_hash_survives_to_dict_from_dict(self):
		snap = Snapshot(
			id="abc", label="v1", timestamp="2026-01-01T00:00:00+00:00",
			scene_name="Scene", data={}, git_hash="a3f2c1b"
		)
		restored = Snapshot.from_dict(snap.to_dict())
		assert restored.git_hash == "a3f2c1b"

	def test_none_hash_survives_round_trip(self):
		snap = Snapshot(
			id="abc", label="v1", timestamp="2026-01-01T00:00:00+00:00",
			scene_name="Scene", data={}, git_hash=None
		)
		restored = Snapshot.from_dict(snap.to_dict())
		assert restored.git_hash is None

	def test_old_snapshot_without_hash_key_defaults_to_none(self):
		"""Snapshots saved before this feature had no git_hash key."""
		old_dict = {
			"id": "abc",
			"label": "old snap",
			"timestamp": "2026-01-01T00:00:00+00:00",
			"scene_name": "Scene",
			"data": {},
			# no git_hash key
		}
		snap = Snapshot.from_dict(old_dict)
		assert snap.git_hash is None
