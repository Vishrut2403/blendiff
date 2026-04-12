"""
storage/sidecar.py

Manages the .blendiff sidecar file that lives next to the .blend file on disk.
Stores named, timestamped snapshots of serialised scenes.

Zero bpy imports — fully testable without Blender.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

SIDECAR_VERSION = "0.1"
SIDECAR_EXTENSION = ".blendiff"


# Data model

@dataclass
class Snapshot:
	id: str
	label: str
	timestamp: str          # ISO-8601, UTC
	scene_name: str
	data: dict              # SerializedScene as a plain dict

	@staticmethod
	def create(label: str, scene_name: str, data: dict) -> "Snapshot":
		return Snapshot(
			id=str(uuid.uuid4()),
			label=label,
			timestamp=datetime.now(timezone.utc).isoformat(),
			scene_name=scene_name,
			data=data,
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

		Returns the created Snapshot.
		Raises RuntimeError if blend file is unsaved.
		"""
		self._require_available()

		snap = Snapshot.create(
			label=label,
			scene_name=scene_name,
			data=serialized_scene,
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
