"""
blendiff.extractor.geometry_hash
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Content digests for mesh geometry.

The problem
-----------
Mesh capture was summary-only: vertex/edge/face counts and a bounding box.
Topology-preserving edits are invisible to that. Move a vertex inside the
existing bounds — a sculpt tweak, a weight-paint-driven adjustment, nudging a
face by hand — and every recorded number stays identical, so BlenDiff reports
*no change*. For a tool whose purpose is semantic diffing of .blend files, that
is a hole in the core promise, not a missing nicety.

Storing full geometry is not the answer: a million-vertex mesh would balloon
every snapshot, and the sidecar is meant to stay human-readable and
diffable alongside the .blend.

The approach
------------
Hash the geometry instead. A digest is 32 characters regardless of mesh size,
so it costs nothing to store, and any change to the underlying data changes it.
This detects *that* geometry changed, which is the question artists actually
ask of a version control tool, without pretending to reconstruct what changed.

Three separate digests rather than one, because "the mesh changed" is much less
useful than knowing which way:

* ``vertex_hash``   — positions only. Differs alone → vertices moved, topology
  intact. That is a sculpt or a tweak.
* ``topology_hash`` — which vertices each face and edge connects. Differs →
  the mesh was re-meshed, subdivided, or had geometry added or removed.
* ``uv_hash``       — UV coordinates. Differs alone → the model is untouched
  and someone re-unwrapped it.

Stability
---------
Coordinates are quantised before hashing, so a digest reflects geometry rather
than float noise. Without it, any operation that round-trips a coordinate
through a slightly different code path would report a phantom edit. The
quantum matches the serializer's float precision so the whole codebase agrees
on when two coordinates are "the same".
"""

from __future__ import annotations

import hashlib
import logging
import struct
from typing import Any, Iterable, Optional, Sequence

log = logging.getLogger(__name__)

#: Decimal places coordinates are rounded to before hashing. Matches
#: SceneSerializer's float precision so both agree on coordinate identity.
PRECISION = 6

#: Grid coordinates are snapped to, derived from PRECISION.
_QUANTUM = 10 ** PRECISION

#: Digest length in bytes. 16 gives a 32-character hex string — short enough to
#: keep the sidecar readable, and far beyond any realistic collision risk for
#: comparing two versions of one mesh.
_DIGEST_SIZE = 16

#: Sentinel for a mesh with nothing to hash, so "empty" is distinguishable from
#: "not captured" (absent key) without a special case at every call site.
EMPTY = "empty"

#: Version of the digest format, stored as a prefix on every hash.
#
# A digest is only meaningful against another digest computed the same way.
# Version 1 built a comma-joined decimal string in Python, which cost about
# 3.5 microseconds per float and put a two-million-vertex sculpt at roughly
# twenty seconds per snapshot. Version 2 packs quantised integers as binary
# instead, which is the same information far faster.
#
# The prefix exists so that a v1 snapshot compared against a v2 one is treated
# as *not comparable* rather than as a scene where every mesh changed. Without
# it, upgrading would fill the first diff with geometry edits nobody made.
HASH_VERSION = 2


def _digest(data: bytes) -> str:
	"""blake2b digest as hex, prefixed with the format version."""
	return f"{HASH_VERSION}:{hashlib.blake2b(data, digest_size=_DIGEST_SIZE).hexdigest()}"


def hash_version(digest: str) -> int:
	"""
	Version a digest was produced with; 1 for the unprefixed original format.

	Comparing digests across versions is meaningless, so callers use this to
	skip rather than report a change.
	"""
	if not isinstance(digest, str) or ":" not in digest:
		return 1
	head = digest.split(":", 1)[0]
	return int(head) if head.isdigit() else 1


def comparable(first: str, second: str) -> bool:
	"""True when two digests were produced the same way."""
	return hash_version(first) == hash_version(second)


def _pack_quantised(values: Iterable[float]) -> Optional[bytes]:
	"""
	Quantise coordinates and pack them as little-endian int64.

	numpy does this in one vectorised pass. It ships with Blender, so this is
	the normal path; the pure-Python fallback below produces byte-identical
	output for environments without it.
	"""
	try:
		import numpy as np
	except ImportError:
		return None

	array = np.asarray(values, dtype=np.float64)
	if array.size == 0:
		return b""
	# rint matches Python's round() for halfway cases, so both paths agree.
	return np.rint(array * _QUANTUM).astype("<i8").tobytes()


def _pack_quantised_python(values: Iterable[float]) -> bytes:
	"""Fallback packing, byte-identical to the numpy path."""
	quantised = [quantize(v) for v in values]
	if not quantised:
		return b""
	return struct.pack(f"<{len(quantised)}q", *quantised)


def quantize(value: float) -> int:
	"""
	Snap one coordinate to the hashing grid.

	Returning an int rather than a rounded float is deliberate: two floats that
	should be equal can still differ in their last bit and serialise
	differently, whereas the integers they quantise to are exactly comparable.
	"""
	return int(round(float(value) * _QUANTUM))


def hash_floats(values: Iterable[float]) -> str:
	"""
	Hash a flat sequence of coordinates.

	Values are quantised first, so the digest reflects geometry rather than
	float representation.
	"""
	if len(values) == 0:
		return EMPTY

	payload = _pack_quantised(values)
	if payload is None:
		payload = _pack_quantised_python(values)
	return _digest(payload)


def hash_ints(values: Iterable[int]) -> str:
	"""Hash a flat sequence of indices, used for topology."""
	items = values
	if len(items) == 0:
		return EMPTY

	try:
		import numpy as np

		payload = np.asarray(items, dtype="<i8").tobytes()
	except ImportError:
		payload = struct.pack(f"<{len(items)}q", *(int(v) for v in items))

	# Tag index data so it cannot collide with coordinate data of the same
	# numeric value.
	return _digest(b"i" + payload)


def combine(parts: Sequence[str]) -> str:
	"""
	Combine several digests into one.

	Used where a single logical property spans multiple arrays — UV coordinates
	across several layers, or topology across faces and edges.
	"""
	if not parts:
		return EMPTY
	if all(p == EMPTY for p in parts):
		return EMPTY
	return _digest("|".join(parts).encode("ascii"))


# bpy-facing extraction
#
# Everything below reads from Blender. It uses foreach_get, which fills a
# buffer in one C-side call, because iterating mesh.vertices in Python is
# orders of magnitude slower and this runs on every snapshot.

def _buffer(size: int, float_type: bool):
	"""
	Allocate the buffer foreach_get fills.

	A numpy array keeps the whole read in C. A Python list of a few million
	floats is the single most expensive thing about hashing a dense mesh, so
	this is the difference between a snapshot taking seconds and taking
	minutes on a heavy sculpt.

	Floats use **float32**, matching how Blender stores coordinates and UVs.
	A float64 buffer makes foreach_get convert every element instead of
	copying the block: measured at 12.7 ms against 2.9 ms for one dense mesh's
	vertices, and 40.5 ms against 13.6 ms for its UVs. Widening float32 to
	float64 afterwards is exact, so the quantised values and therefore the
	digests are unchanged.

	Integers stay at int64 because the same measurement showed no difference
	for them.
	"""
	try:
		import numpy as np

		return np.empty(size, dtype=np.float32 if float_type else np.int64)
	except ImportError:
		return [0.0 if float_type else 0] * size


def _flat_floats(collection: Any, attr: str, width: int):
	"""Read a flat float buffer out of a bpy collection, or None on failure."""
	count = len(collection)
	if count == 0:
		return []
	try:
		buffer = _buffer(count * width, True)
		collection.foreach_get(attr, buffer)
		return buffer
	except Exception as exc:
		log.warning("Could not read %r for hashing: %s", attr, exc)
		return None


def _flat_ints(collection: Any, attr: str, width: int):
	"""Read a flat integer buffer out of a bpy collection, or None on failure."""
	count = len(collection)
	if count == 0:
		return []
	try:
		buffer = _buffer(count * width, False)
		collection.foreach_get(attr, buffer)
		return buffer
	except Exception as exc:
		log.warning("Could not read %r for hashing: %s", attr, exc)
		return None


def hash_vertex_positions(mesh: Any) -> str:
	"""Digest of every vertex coordinate, in vertex-index order."""
	buffer = _flat_floats(mesh.vertices, "co", 3)
	if buffer is None:
		return EMPTY
	return hash_floats(buffer)


def hash_topology(mesh: Any) -> str:
	"""
	Digest of how vertices are connected.

	Combines per-corner vertex indices with each face's corner count, which
	together fully describe face topology, plus the edge vertex pairs so that
	loose edges are covered too.
	"""
	loops = _flat_ints(mesh.loops, "vertex_index", 1)
	totals = _flat_ints(mesh.polygons, "loop_total", 1)
	edges = _flat_ints(mesh.edges, "vertices", 2)

	parts = [
		hash_ints(loops) if loops is not None else EMPTY,
		hash_ints(totals) if totals is not None else EMPTY,
		hash_ints(edges) if edges is not None else EMPTY,
	]
	return combine(parts)


def hash_uvs(mesh: Any) -> str:
	"""
	Digest of every UV layer's coordinates.

	Layer names are folded in, so renaming a UV map registers as a change —
	downstream shaders reference layers by name.
	"""
	parts: list[str] = []
	try:
		layers = list(mesh.uv_layers)
	except Exception as exc:
		log.warning("Could not read UV layers for hashing: %s", exc)
		return EMPTY

	for layer in layers:
		try:
			buffer = _flat_floats(layer.data, "uv", 2)
		except Exception as exc:
			log.warning("Could not read UVs for layer %r: %s", layer.name, exc)
			continue
		if buffer is None:
			continue
		parts.append(_digest(layer.name.encode("utf-8")))
		parts.append(hash_floats(buffer))

	return combine(parts)


def extract_geometry_hashes(mesh: Any) -> dict[str, str]:
	"""
	All geometry digests for one mesh.

	Never raises: a failure on any one digest degrades that entry to EMPTY
	rather than losing the whole snapshot, matching how the rest of extraction
	treats partial failure.
	"""
	hashes = {}
	for key, fn in (
		("vertex_hash", hash_vertex_positions),
		("topology_hash", hash_topology),
		("uv_hash", hash_uvs),
	):
		try:
			hashes[key] = fn(mesh)
		except Exception as exc:
			log.warning("Failed to compute %s: %s", key, exc)
			hashes[key] = EMPTY
	return hashes
