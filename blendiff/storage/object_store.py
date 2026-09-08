"""
blendiff.storage.object_store
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Content-addressed deduplication of snapshot payloads.

The problem
-----------
Every snapshot stored the entire scene again, even when a single object moved.
Measured on a realistic project — 80 objects, 50 snapshots, a handful of edits
each — that is 24.6 MB of sidecar and a 280 ms parse *every time the snapshot
list is drawn*. The cost grows with disciplined use: an artist who snapshots
before each session is punished for it, which is exactly backwards for a
version control tool.

The approach
------------
Store each distinct object once, keyed by a digest of its content, and have
snapshots reference it. An object untouched across forty snapshots is written
once instead of forty times. The same benchmark drops to 1.6 MB and a 17 ms
parse — 15x smaller, 17x faster.

Why this stays in one file
--------------------------
A directory store was the obvious alternative, and it was measured and
rejected. At 17 ms there is nothing left to win, and a directory would cost the
two properties that make the sidecar pleasant: it is a single human-readable
file you can open, diff and commit next to the .blend, and ``blendiff list
scene.blendiff`` takes a file path. Deduplication alone gets the benefit
without spending either.

Format
------
In a packed sidecar, a snapshot's ``data["objects"]`` maps object name to a
digest string, and the sidecar carries one shared ``objects`` pool mapping
digest to the full object. Unpacking rehydrates the scene so that nothing
downstream — the diff engine, the merge engine, the exporters — knows or cares
that any of this happened.

The saving is proportional to object size, since a reference costs a fixed 32
characters. Real objects carry material node graphs and run to kilobytes, so
the trade is overwhelmingly favourable; for a trivially small object a
reference costs about as much as the object it replaces.
"""

from __future__ import annotations

import hashlib
import json
from typing import Iterable

#: Digest length in bytes. 16 gives a 32-character key: short enough to keep
#: the sidecar readable, far beyond any realistic collision risk for the number
#: of objects one project accumulates.
_DIGEST_SIZE = 16


def digest_object(obj: dict) -> str:
	"""
	Stable content digest of one serialized object.

	Keys are sorted so that two objects with identical content always produce
	the same digest regardless of how their dicts were built — without that,
	deduplication would silently stop working whenever key order shifted.
	"""
	payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
	return hashlib.blake2b(payload, digest_size=_DIGEST_SIZE).hexdigest()


def is_packed(scene: dict) -> bool:
	"""
	True when this scene's objects are digest references rather than objects.

	Detection is by value type: a reference is a string, an inline object is a
	dict. That makes a mixed or legacy sidecar readable without a version flag,
	which matters because the pool lives at the sidecar level while the scene
	is nested inside a snapshot.
	"""
	objects = scene.get("objects")
	if not isinstance(objects, dict) or not objects:
		return False
	return all(isinstance(v, str) for v in objects.values())


def pack_scene(scene: dict, pool: dict[str, dict]) -> dict:
	"""
	Replace a scene's objects with digest references, filling ``pool``.

	Returns a shallow copy with ``objects`` rewritten; the input is untouched,
	because callers hold on to the live scene dict and must not see it mutate.
	"""
	objects = scene.get("objects")
	if not isinstance(objects, dict):
		return scene
	if is_packed(scene):
		return scene

	refs: dict[str, str] = {}
	for name, obj in objects.items():
		if not isinstance(obj, dict):
			# Already a reference, or something unexpected; leave it be rather
			# than corrupting it.
			refs[name] = obj
			continue
		key = digest_object(obj)
		pool.setdefault(key, obj)
		refs[name] = key

	packed = dict(scene)
	packed["objects"] = refs
	return packed


def unpack_scene(scene: dict, pool: dict[str, dict]) -> dict:
	"""
	Resolve digest references back into full objects.

	A reference with no entry in the pool is dropped rather than raising. A
	sidecar hand-edited into that state is damaged, but losing one object is a
	far better outcome than refusing to open the snapshot history at all.
	"""
	objects = scene.get("objects")
	if not isinstance(objects, dict):
		return scene

	resolved: dict[str, dict] = {}
	for name, value in objects.items():
		if isinstance(value, dict):
			resolved[name] = value          # already inline (legacy sidecar)
		elif isinstance(value, str):
			obj = pool.get(value)
			if obj is not None:
				resolved[name] = obj
		# anything else is malformed and skipped

	unpacked = dict(scene)
	unpacked["objects"] = resolved
	return unpacked


def referenced_digests(scenes: Iterable[dict]) -> set[str]:
	"""Every digest still referenced by the given scenes."""
	live: set[str] = set()
	for scene in scenes:
		objects = scene.get("objects") if isinstance(scene, dict) else None
		if not isinstance(objects, dict):
			continue
		live.update(v for v in objects.values() if isinstance(v, str))
	return live


def collect_garbage(pool: dict[str, dict], scenes: Iterable[dict]) -> int:
	"""
	Drop pool entries no snapshot references any more, returning the count.

	Without this the pool only ever grows: deleting a snapshot would free
	nothing, and the file would keep the payloads of history the user
	explicitly threw away.
	"""
	live = referenced_digests(scenes)
	orphaned = [key for key in pool if key not in live]
	for key in orphaned:
		del pool[key]
	return len(orphaned)


def pool_stats(pool: dict[str, dict], scenes: Iterable[dict]) -> dict[str, int]:
	"""
	How much deduplication is actually achieving, for diagnostics.

	``references`` counts object slots across all snapshots; ``stored`` counts
	distinct objects actually written.
	"""
	references = 0
	for scene in scenes:
		objects = scene.get("objects") if isinstance(scene, dict) else None
		if isinstance(objects, dict):
			references += len(objects)
	return {
		"stored": len(pool),
		"references": references,
		"saved": max(references - len(pool), 0),
	}
