from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from .migrate import migrate_scene, needs_migration
from .object_store import collect_garbage, pack_scene, pool_stats, unpack_scene

log = logging.getLogger(__name__)

SIDECAR_VERSION = "0.3"
SIDECAR_EXTENSION = ".blendiff"

# Sidecar files written by these versions are readable by the current loader.
# 0.3 introduced the shared object pool; earlier files store objects inline and
# are packed automatically the next time the sidecar is written.
SUPPORTED_SIDECAR_VERSIONS = ("0.1", "0.2", "0.3")


# Git helper

def _get_git_hash(cwd: Optional[str] = None) -> Optional[str]:
	"""
	Return the short HEAD hash of the repository containing ``cwd``.

	``cwd`` must be a real directory. There is deliberately no fallback to the
	process working directory: Blender's cwd is wherever it happened to be
	launched from, so falling back would stamp snapshots with the hash of a
	completely unrelated repository — silently wrong provenance, which is worse
	than no provenance at all.
	"""
	if not cwd or not os.path.isdir(cwd):
		return None

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
		timestamp: str
		scene_name: str
		data: dict
		git_hash: Optional[str] = None

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
		def from_dict(
				d: dict,
				pool: Optional[dict] = None,
				migrate: bool = True,
		) -> "Snapshot":
				"""
				Rebuild a Snapshot from its stored dict.

				Objects are stored once in a shared pool and referenced by
				digest, so they are rehydrated here: everything downstream sees
				an ordinary full scene and never learns that deduplication
				happened. Scene data is then migrated to the current schema, so
				nothing downstream reasons about historical shapes either.

				Both are in-memory only; the file is untouched until the next
				write.
				"""
				data = d["data"]
				if pool:
						data = unpack_scene(data, pool)
				if migrate:
						data = migrate_scene(data)
				return Snapshot(
						id=d["id"],
						label=d["label"],
						timestamp=d["timestamp"],
						scene_name=d["scene_name"],
						data=data,
						git_hash=d.get("git_hash"),
				)

		@property
		def schema_version(self) -> int:
				"""Schema version of this snapshot's scene data."""
				from ..data_model.schema import schema_version_of
				return schema_version_of(self.data)

		def timestamp_display(self) -> str:
				try:
						dt = datetime.fromisoformat(self.timestamp)

						local_dt = dt.astimezone()
						return local_dt.strftime("%Y-%m-%d %H:%M:%S")
				except Exception:
						return self.timestamp

		def label_display(self) -> str:

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

		def __init__(self, blend_filepath: str):

			self._blend_filepath = blend_filepath
			self._sidecar_path = self._resolve_sidecar_path(blend_filepath)


		# Public API

		@property
		def sidecar_path(self) -> Optional[str]:
				return self._sidecar_path

		@property
		def is_available(self) -> bool:
				return self._sidecar_path is not None

		def list_snapshots(self) -> list[Snapshot]:
				data = self._load_raw()
				pool = data.get("objects", {})
				snapshots = [
						Snapshot.from_dict(s, pool)
						for s in data.get("snapshots", [])
				]
				# Newest first — reverse chronological
				snapshots.sort(key=lambda s: s.timestamp, reverse=True)
				return snapshots

		def get_snapshot(self, snapshot_id: str) -> Optional[Snapshot]:
				"""Return a snapshot by UUID, or None if not found."""
				data = self._load_raw()
				pool = data.get("objects", {})
				for s in data.get("snapshots", []):
						if s["id"] == snapshot_id:
								return Snapshot.from_dict(s, pool)
				return None

		def save_snapshot(
				self,
				label: str,
				scene_name: str,
				serialized_scene: dict,
		) -> Snapshot:

				self._require_available()

				# Only the .blend file's own directory is consulted — see
				# _get_git_hash for why there is no process-cwd fallback.
				blend_dir = os.path.dirname(os.path.abspath(self._blend_filepath))
				git_hash = _get_git_hash(cwd=blend_dir)

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

				self._require_available()

				data = self._load_raw()
				for s in data["snapshots"]:
						if s["id"] == snapshot_id:
								s["label"] = new_label
								self._write_raw(data)
								return True
				return False

		def latest_object_ids(self) -> dict:
				"""
				Object name to identity, from the most recent snapshot.

				The stamps themselves live in the .blend, but a user who
				snapshots and closes without saving loses them. This makes the
				sidecar the durable record so identity — and therefore rename
				tracking — survives that.
				"""
				snapshots = self.list_snapshots()
				if not snapshots:
						return {}

				objects = snapshots[0].data.get("objects", {})
				if not isinstance(objects, dict):
						return {}

				return {
						name: obj["blendiff_id"]
						for name, obj in objects.items()
						if isinstance(obj, dict) and isinstance(obj.get("blendiff_id"), str)
				}

		def snapshot_count(self) -> int:
				data = self._load_raw()
				return len(data.get("snapshots", []))

		def storage_stats(self) -> dict:
				"""
				How much deduplication is saving on this sidecar.

				``references`` is how many object slots the snapshots occupy in
				total; ``stored`` is how many distinct objects are actually
				written to disk.
				"""
				data = self._load_raw()
				scenes = [s.get("data", {}) for s in data.get("snapshots", [])]
				stats = pool_stats(data.get("objects", {}), scenes)
				stats["snapshots"] = len(scenes)
				if os.path.exists(self._sidecar_path or ""):
						stats["bytes"] = os.path.getsize(self._sidecar_path)
				return stats

		def outdated_snapshot_ids(self) -> list[str]:
				"""
				IDs of snapshots stored in a pre-current schema version.

				These still diff correctly — they are migrated on read — but
				domains they never captured are reported as skipped rather than
				as changes.
				"""
				data = self._load_raw()
				return [
						s["id"] for s in data.get("snapshots", [])
						if needs_migration(s.get("data", {}))
				]

		def migrate_file(self) -> int:
				"""
				Rewrite the sidecar with every snapshot migrated to the current
				schema, and return how many were upgraded.

				This is opt-in: until it is called, the file stays readable by
				older BlenDiff versions. The write is atomic, so an interrupted
				migration leaves the original file intact.
				"""
				self._require_available()

				data = self._load_raw()
				upgraded = 0
				for snap in data.get("snapshots", []):
						scene = snap.get("data", {})
						if needs_migration(scene):
								snap["data"] = migrate_scene(scene)
								upgraded += 1

				if upgraded:
						self._write_raw(data)
				return upgraded


		# Internal helpers


		@staticmethod
		def _resolve_sidecar_path(blend_filepath: str) -> Optional[str]:

				if not blend_filepath:
						return None
				base, _ = os.path.splitext(blend_filepath)
				return base + SIDECAR_EXTENSION

		def _load_raw(self) -> dict:

				if not os.path.exists(self._sidecar_path):
						blend_filename = os.path.basename(self._blend_filepath)
						return _empty_sidecar(blend_filename)

				try:
						with open(self._sidecar_path, "r", encoding="utf-8") as f:
								return json.load(f)
				except (json.JSONDecodeError, OSError) as e:
						print(f"[BlenDiff] Warning: could not read sidecar: {e}")
						blend_filename = os.path.basename(self._blend_filepath)
						return _empty_sidecar(blend_filename)

		def _write_raw(self, data: dict) -> None:
				"""
				Write the sidecar atomically.

				The sidecar holds the user's entire version history, so it must
				never be left truncated. Writing in place means a crash, a full
				disk, or a killed Blender process during the write destroys
				every snapshot. Instead the payload goes to a temporary file in
				the same directory (same filesystem, so the rename is atomic),
				is flushed all the way to disk, and only then replaces the real
				file via os.replace — which is atomic on POSIX and Windows.
				"""
				data["blendiff_version"] = SIDECAR_VERSION

				# Deduplicate before writing. Doing it here rather than at each
				# call site means every path — save, delete, rename, migrate —
				# gets it, and a legacy sidecar with inline objects is packed
				# the first time it is written.
				pool = data.setdefault("objects", {})
				snapshots = data.get("snapshots", [])
				for snapshot in snapshots:
						snapshot["data"] = pack_scene(snapshot.get("data", {}), pool)

				# Reclaim objects no surviving snapshot references, or deleting
				# a snapshot would free nothing and the pool would only grow.
				collect_garbage(pool, [s.get("data", {}) for s in snapshots])

				directory = os.path.dirname(os.path.abspath(self._sidecar_path))
				os.makedirs(directory, exist_ok=True)

				fd, tmp_path = tempfile.mkstemp(
						prefix=".blendiff-", suffix=".tmp", dir=directory,
				)
				try:
						with os.fdopen(fd, "w", encoding="utf-8") as f:
								json.dump(data, f, indent=2, ensure_ascii=False)
								f.flush()
								os.fsync(f.fileno())
						os.replace(tmp_path, self._sidecar_path)
				except Exception:
						# Leave the existing sidecar untouched and clean up.
						try:
								os.unlink(tmp_path)
						except OSError:
								pass
						raise

		def _require_available(self) -> None:
				if not self.is_available:
						raise RuntimeError(
								"BlenDiff: Cannot write sidecar — the .blend file has not been "
								"saved yet. Please save your file first."
						)
