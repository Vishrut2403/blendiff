from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

SIDECAR_VERSION = "0.1"
SIDECAR_EXTENSION = ".blendiff"


# Git helper

def _get_git_hash(cwd: Optional[str] = None) -> Optional[str]:
	"""
	Return the short SHA of the current HEAD commit, or None if:
	- git is not installed
	- the working directory is not inside a git repo
	- any other error occurs

	Never raises — always degrades gracefully.

	Parameters
	----------
	cwd : str | None
		Directory to run git in. Defaults to the process working directory.
	"""
	try:
		result = subprocess.run(
			["git", "rev-parse", "--short", "HEAD"],
			cwd=cwd,
			capture_output=True,
			text=True,
			timeout=2,
		)
		if result.returncode == 0:
			return result.stdout.strip() or None
		return None
	except Exception:
		return None


# Data model

@dataclass
class Snapshot:
		id: str
		label: str
		timestamp: str          # ISO-8601, UTC
		scene_name: str
		data: dict              # SerializedScene as a plain dict
		git_hash: Optional[str] = None  # short SHA at snapshot time, or None

		@staticmethod
		def create(
				label: str,
				scene_name: str,
				data: dict,
				git_cwd: Optional[str] = None,
				git_hash_override: Optional[str] = None,
		) -> "Snapshot":
				return Snapshot(
						id=str(uuid.uuid4()),
						label=label,
						timestamp=datetime.now(timezone.utc).isoformat(),
						scene_name=scene_name,
						data=data,
						git_hash=git_hash_override if git_hash_override is not None else _get_git_hash(cwd=git_cwd),
				)

		def to_dict(self) -> dict:
				return asdict(self)

		@staticmethod
		def from_dict(d: dict) -> "Snapshot":
				return Snapshot(
						id=d["id"],
						label=d["label"],
						timestamp=d["timestamp"],
						scene_name=d["scene_name"],
						data=d["data"],
						git_hash=d.get("git_hash"),  # None for old snapshots without hash
				)

		def timestamp_display(self) -> str:
				"""Human-readable local timestamp for UI display."""
				try:
						dt = datetime.fromisoformat(self.timestamp)
						# Convert UTC → local for display
						local_dt = dt.astimezone()
						return local_dt.strftime("%Y-%m-%d %H:%M:%S")
				except Exception:
						return self.timestamp

		def label_display(self) -> str:
				"""
				Label with git hash suffix when available.
				e.g. "Before rigging [a3f2c1b]"
				"""
				if self.git_hash:
						return f"{self.label} [{self.git_hash}]"
				return self.label


# Sidecar file shape

def _empty_sidecar(blend_filename: str) -> dict:
		return {
				"blendiff_version": SIDECAR_VERSION,
				"blend_file": blend_filename,
				"snapshots": [],
		}


# SidecarManager

class SidecarManager:
		"""
		Reads and writes the .blendiff sidecar file.

		Usage:
				mgr = SidecarManager("/path/to/my_scene.blend")
				mgr.save_snapshot("Before rigging", "Scene", serialized_scene_dict)
				snapshots = mgr.list_snapshots()
				snap = mgr.get_snapshot(some_uuid)
				mgr.delete_snapshot(some_uuid)
		"""

		def __init__(self, blend_filepath: str):
				"""
				Parameters
				----------
				blend_filepath : str
						Absolute path to the .blend file, as returned by bpy.data.filepath.
						May be empty string if the file has never been saved.
				"""
				self._blend_filepath = blend_filepath
				self._sidecar_path = self._resolve_sidecar_path(blend_filepath)


		# Public API


		@property
		def sidecar_path(self) -> Optional[str]:
				"""Absolute path to the sidecar file, or None if blend is unsaved."""
				return self._sidecar_path

		@property
		def is_available(self) -> bool:
				"""False when the blend file has not been saved yet (no filepath)."""
				return self._sidecar_path is not None

		def list_snapshots(self) -> list[Snapshot]:
				"""Return all snapshots, newest first."""
				data = self._load_raw()
				snapshots = [Snapshot.from_dict(s) for s in data.get("snapshots", [])]
				# Newest first — reverse chronological
				snapshots.sort(key=lambda s: s.timestamp, reverse=True)
				return snapshots

		def get_snapshot(self, snapshot_id: str) -> Optional[Snapshot]:
				"""Return a snapshot by UUID, or None if not found."""
				data = self._load_raw()
				for s in data.get("snapshots", []):
						if s["id"] == snapshot_id:
								return Snapshot.from_dict(s)
				return None

		def save_snapshot(
				self,
				label: str,
				scene_name: str,
				serialized_scene: dict,
		) -> Snapshot:
				"""
				Create a new snapshot and append it to the sidecar.
				Automatically attaches the current git commit hash when available.

				Returns the created Snapshot.
				Raises RuntimeError if blend file is unsaved.
				"""
				self._require_available()

				# Use the blend file's directory as the git working dir so the
				# hash reflects the repo the asset lives in, not the CWD.
				blend_dir = os.path.dirname(self._blend_filepath) or None
				git_hash = _get_git_hash(cwd=blend_dir) or _get_git_hash(cwd=None)

				snap = Snapshot.create(
						label=label,
						scene_name=scene_name,
						data=serialized_scene,
						git_hash_override=git_hash,
				)

				data = self._load_raw()
				data["snapshots"].append(snap.to_dict())
				self._write_raw(data)

				return snap

		def delete_snapshot(self, snapshot_id: str) -> bool:
				"""
				Remove a snapshot by UUID.

				Returns True if deleted, False if not found.
				Raises RuntimeError if blend file is unsaved.
				"""
				self._require_available()

				data = self._load_raw()
				original_count = len(data["snapshots"])
				data["snapshots"] = [
						s for s in data["snapshots"] if s["id"] != snapshot_id
				]

				if len(data["snapshots"]) == original_count:
						return False

				self._write_raw(data)
				return True

		def rename_snapshot(self, snapshot_id: str, new_label: str) -> bool:
				"""
				Update the label of an existing snapshot.

				Returns True if renamed, False if not found.
				"""
				self._require_available()

				data = self._load_raw()
				for s in data["snapshots"]:
						if s["id"] == snapshot_id:
								s["label"] = new_label
								self._write_raw(data)
								return True
				return False

		def snapshot_count(self) -> int:
				"""Number of snapshots currently stored."""
				data = self._load_raw()
				return len(data.get("snapshots", []))


		# Internal helpers


		@staticmethod
		def _resolve_sidecar_path(blend_filepath: str) -> Optional[str]:
				"""
				Derive the sidecar path from the blend filepath.
				Returns None if blend_filepath is empty (unsaved file).
				"""
				if not blend_filepath:
						return None
				base, _ = os.path.splitext(blend_filepath)
				return base + SIDECAR_EXTENSION

		def _load_raw(self) -> dict:
				"""
				Load the sidecar JSON from disk.
				Returns an empty sidecar structure if the file doesn't exist yet.
				"""
				if not os.path.exists(self._sidecar_path):
						blend_filename = os.path.basename(self._blend_filepath)
						return _empty_sidecar(blend_filename)

				try:
						with open(self._sidecar_path, "r", encoding="utf-8") as f:
								return json.load(f)
				except (json.JSONDecodeError, OSError) as e:
						# Corrupted sidecar — return empty rather than crashing Blender
						print(f"[BlenDiff] Warning: could not read sidecar: {e}")
						blend_filename = os.path.basename(self._blend_filepath)
						return _empty_sidecar(blend_filename)

		def _write_raw(self, data: dict) -> None:
				"""Write the sidecar dict to disk as pretty-printed JSON."""
				with open(self._sidecar_path, "w", encoding="utf-8") as f:
						json.dump(data, f, indent=2, ensure_ascii=False)

		def _require_available(self) -> None:
				if not self.is_available:
						raise RuntimeError(
								"BlenDiff: Cannot write sidecar — the .blend file has not been "
								"saved yet. Please save your file first."
						)
