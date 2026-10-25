"""
blendiff.extractor.geometry_store
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Storing vertex positions, so a snapshot can be returned to exactly.

Snapshots record a digest of a mesh rather than the mesh itself, which is what
keeps a sidecar small enough to live beside the .blend. That answers "did the
geometry change" and cannot answer "put it back". This module stores the
positions themselves, for snapshots where the user asks for it, so restoring
one returns the mesh to the shape it had.

Why only positions
------------------
Restoring a whole mesh means clearing it and rebuilding, and that destroys
what hangs off the geometry. Measured on a sphere with UVs and a vertex group:

    foreach_set positions:  uv=2  vgroups=1  shapekeys=2  materials=1
    clear + from_pydata:    uv=0  vgroups=0  shapekeys=2  materials=1

Writing positions into the existing mesh keeps all of it and is exact. So
positions are stored, and they are only written back when the topology still
matches, which the existing topology digest already tells us. A snapshot taken
before a re-mesh cannot be restored onto the re-meshed object, and saying so is
better than rebuilding and quietly dropping the UVs.

How they are encoded
--------------------
Three steps, each measured against the alternative on a two million vertex
mesh:

    plain JSON                   62.0 MB
    zlib + base64, float32       20.0 MB
    zlib + base64, quantised     15.0 MB

Quantising to the same grid the digests use costs nothing, since coordinates
are already rounded there, and it compresses far better than raw floats
because neighbouring vertices share high-order bytes.

The result is a string, so it travels inside the sidecar like everything else
and the one-file promise holds: a .blend and a .blendiff, nothing beside them.
"""

from __future__ import annotations

import base64
import logging
import struct
import zlib

from .geometry_hash import PRECISION

log = logging.getLogger(__name__)

#: Grid positions are snapped to, matching the digests so the two agree about
#: when two coordinates are the same.
_QUANTUM = 10 ** PRECISION

#: Prefix on every stored blob, so a future encoding can be told apart from
#: this one rather than being fed to the wrong decoder.
FORMAT = "q1"

#: zlib level. 6 is the default and sits where the curve flattens; 9 costs
#: noticeably more time for a few per cent on data this regular.
_COMPRESSION = 6


def encode_positions(coordinates) -> str:
	"""
	Pack a flat sequence of coordinates into one storable string.

	The flat form is what ``foreach_get("co", ...)`` produces, three floats per
	vertex, which is also the order they are written back in.
	"""
	try:
		import numpy as np

		array = np.asarray(coordinates, dtype=np.float64)
		packed = np.rint(array * _QUANTUM).astype("<i4").tobytes()
	except ImportError:
		values = [int(round(float(c) * _QUANTUM)) for c in coordinates]
		packed = struct.pack(f"<{len(values)}i", *values)

	blob = base64.b64encode(zlib.compress(packed, _COMPRESSION)).decode("ascii")
	return f"{FORMAT}:{blob}"


def decode_positions(stored: str) -> list[float]:
	"""
	Unpack what encode_positions produced, back to a flat list of floats.

	Raises ValueError on anything it does not recognise, rather than returning
	a partial result. Half a mesh written into a scene is worse than a refusal.
	"""
	if not isinstance(stored, str) or ":" not in stored:
		raise ValueError("Stored geometry is not in a recognised format.")

	tag, _, blob = stored.partition(":")
	if tag != FORMAT:
		raise ValueError(
			f"Stored geometry is format {tag!r}; this BlenDiff writes {FORMAT!r}."
		)

	try:
		raw = zlib.decompress(base64.b64decode(blob))
	except Exception as exc:
		raise ValueError(f"Stored geometry could not be read: {exc}") from exc

	if len(raw) % 4:
		raise ValueError("Stored geometry is truncated.")

	count = len(raw) // 4
	values = struct.unpack(f"<{count}i", raw)
	return [v / _QUANTUM for v in values]


def is_stored_geometry(value) -> bool:
	"""True when a value looks like something decode_positions can read."""
	return isinstance(value, str) and value.startswith(f"{FORMAT}:")
