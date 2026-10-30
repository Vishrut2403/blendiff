from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from .migrate import migrate_scene, needs_migration
from .object_store import collect_garbage, pack_scene, pool_stats, unpack_scene

log = logging.getLogger(__name__)

#: Version stamped into every sidecar this BlenDiff writes.
#
# The format promise, from 1.0 onwards: any 1.x BlenDiff reads any sidecar
# written by any other 1.x, and every older format keeps opening. A snapshot
# is somebody's history, and history that stops opening when the add-on
# updates is not history.
#
# Keeping this at "0.3" while the add-on was called 1.0 would have been a
# small lie with a long tail: the number in the file is the only thing a
# future reader has to go on.
SIDECAR_VERSION = "1.0"
SIDECAR_EXTENSION = ".blendiff"

# Formats this loader understands.
#
# 0.1 and 0.2 store objects inline; 0.3 introduced the shared object pool and
# both are packed into it the next time the sidecar is written. 1.0 is 0.3's
# layout with a version that matches the add-on, so nothing has to be migrated
# between them.
SUPPORTED_SIDECAR_VERSIONS = ("0.1", "0.2", "0.3", "1.0")


def scene_stores_geometry(scene_dict: dict) -> bool:
		"""
		True when any mesh in a serialized scene kept its vertex positions.

		Used to label a snapshot once, when it is written, so the panel can
		say which ones can be restored exactly without reading every mesh on
		every redraw.
		"""
		objects = scene_dict.get("objects") if isinstance(scene_dict, dict) else None
		for obj in (objects or {}).values():
				mesh = obj.get("mesh_data") if isinstance(obj, dict) else None
				if isinstance(mesh, dict) and mesh.get("stored_geometry"):
						return True
		return False


# Data model

@dataclass
class Snapshot:
		id: str
		label: str
		timestamp: str
		scene_name: str
		data: dict
		#: True when this snapshot kept vertex positions, not just digests.
		#
		# Recorded at write time rather than worked out on every panel
		# redraw, which would mean walking every mesh in the scene each time
		# the sidebar draws. Absent in older sidecars, which reads as False:
		# nothing written before the option existed stored geometry.
		has_geometry: bool = False

		#: True when a save handler took this, rather than the user.
		#
		# Automatic snapshots are the ones pruning is allowed to remove. A
		# snapshot somebody chose to take and name is theirs to delete.
		# Absent in sidecars written before snapshot-on-save existed, which
		# reads as False: everything older was taken by hand.
		auto: bool = False

		@staticmethod
		def create(
				label: str,
				scene_name: str,
				data: dict,
				auto: bool = False,
				has_geometry: bool = False,
		) -> "Snapshot":
				return Snapshot(
						id=str(uuid.uuid4()),
						label=label,
						timestamp=datetime.now(timezone.utc).isoformat(),
						scene_name=scene_name,
						data=data,
						auto=auto,
						has_geometry=has_geometry,
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
						auto=bool(d.get("auto", False)),
						has_geometry=bool(d.get("has_geometry", False)),
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
				auto: bool = False,
		) -> Snapshot:

				self._require_available()

				snap = Snapshot.create(
						label=label,
						scene_name=scene_name,
						data=serialized_scene,
						auto=auto,
						has_geometry=scene_stores_geometry(serialized_scene),
				)

				data = self._load_raw()
				data["snapshots"].append(snap.to_dict())
				self._write_raw(data)

				return snap

		def prune_auto_snapshots(self, keep: int) -> int:
				"""
				Drop the oldest automatic snapshots, keeping the newest `keep`.

				Only automatic ones. A snapshot somebody chose to take and name
				is theirs to delete, and a history that silently throws away the
				point you meant to come back to is worse than no history.

				Returns how many were removed. `keep` of zero or less removes
				nothing, so a misconfigured preference cannot wipe the history.
				"""
				self._require_available()
				if keep <= 0:
						return 0

				data = self._load_raw()
				entries = data.get("snapshots", [])

				autos = [s for s in entries if s.get("auto")]
				if len(autos) <= keep:
						return 0

				autos.sort(key=lambda s: s.get("timestamp", ""))
				doomed = {s["id"] for s in autos[: len(autos) - keep]}

				data["snapshots"] = [s for s in entries if s["id"] not in doomed]
				self._write_raw(data)
				return len(doomed)

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

				blend_filename = os.path.basename(self._blend_filepath)
				try:
						with open(self._sidecar_path, "r", encoding="utf-8") as f:
								data = json.load(f)
				except (json.JSONDecodeError, OSError) as e:
						log.warning("Could not read sidecar: %s", e)
						return _empty_sidecar(blend_filename)

				# Valid JSON of the wrong shape was not caught here, and the
				# TypeError it caused came out of list_snapshots(), which the
				# panel calls on every redraw. A sidecar is a plain JSON file
				# sitting next to the .blend: people hand-edit them, merge them
				# in git and sync them half-written, so a wrong shape is a thing
				# that happens rather than a thing that cannot.
				if not isinstance(data, dict):
						log.warning(
								"Sidecar is a %s, not an object; ignoring it.",
								type(data).__name__,
						)
						return _empty_sidecar(blend_filename)

				snapshots = data.get("snapshots")
				if snapshots is not None and not isinstance(snapshots, list):
						log.warning("Sidecar 'snapshots' is a %s, not a list; ignoring it.",
									type(snapshots).__name__)
						return _empty_sidecar(blend_filename)

				# Entries that are not objects would fail on their first key
				# lookup. Dropping them keeps the readable snapshots readable.
				if snapshots:
						usable = [s for s in snapshots if isinstance(s, dict) and "id" in s]
						if len(usable) != len(snapshots):
								log.warning(
										"Sidecar has %d unreadable snapshot entr(ies); skipping them.",
										len(snapshots) - len(usable),
								)
								data = dict(data, snapshots=usable)

				pool = data.get("objects")
				if pool is not None and not isinstance(pool, dict):
						log.warning("Sidecar object pool is a %s, not an object; ignoring it.",
									type(pool).__name__)
						data = dict(data, objects={})

				# SUPPORTED_SIDECAR_VERSIONS was declared and never consulted, so
				# a file written by a future BlenDiff was read as though it were
				# current. Reading it anyway is still the right behaviour, since
				# refusing would lock somebody out of their own history over a
				# version string, but saying so turns a confusing result into an
				# explained one.
				written_by = data.get("blendiff_version")
				if written_by and written_by not in SUPPORTED_SIDECAR_VERSIONS:
						log.warning(
								"Sidecar was written by BlenDiff format %s, which this "
								"version does not know. Reading it anyway; some of it may "
								"not be understood.",
								written_by,
						)

				return data

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
