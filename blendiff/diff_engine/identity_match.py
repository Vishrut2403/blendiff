"""
blendiff.diff_engine.identity_match
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pair objects across two snapshots so renames keep their history.

Matching two snapshots on object name alone throws away the most common edit an
artist makes. Renaming "Cube" to "Body_LOW" is reported as one deletion and one
unrelated addition, and every property change on that object silently vanishes
from the diff.

Strategy
--------
1. **Persistent id.** Objects stamped with ``_blendiff_id`` are paired by id,
   regardless of name. This is the only way a rename can be recognised.
2. **Name.** Objects that were never stamped — snapshots from older BlenDiff
   versions, or linked objects that cannot be written to — fall back to exact
   name matching, which is what BlenDiff always did.
3. **Whatever is left** is a genuine addition or removal.

Handling duplicate ids
----------------------
Duplicating an object in Blender (Shift+D) copies its custom properties, id
included, so two objects can legitimately share one. An id that is ambiguous on
either side is therefore discarded for matching purposes and those objects fall
through to name matching, which handles the duplicate case correctly: the
original keeps its name and pairs up, the copy is a genuine addition.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Key under which a serialized object carries its persistent identity.
ID_FIELD = "blendiff_id"


@dataclass
class ObjectPairing:
	"""
	The result of matching objects across two snapshots.

	``matched`` holds ``(name_in_a, name_in_b)`` pairs; the two names differ
	only when the object was renamed. ``added`` and ``removed`` hold names that
	exist on exactly one side.
	"""

	matched: list[tuple[str, str]] = field(default_factory=list)
	added: list[str] = field(default_factory=list)
	removed: list[str] = field(default_factory=list)

	@property
	def renamed(self) -> list[tuple[str, str]]:
		"""Matched pairs whose name changed between the two snapshots."""
		return [(a, b) for a, b in self.matched if a != b]

	def name_map_a_to_b(self) -> dict[str, str]:
		return {a: b for a, b in self.matched}


def _unique_ids(objects: dict[str, dict]) -> dict[str, str]:
	"""
	Map each unambiguous identity to its object name.

	Ids appearing on more than one object are dropped: a duplicated object
	carries a copy of the original's id, and guessing which one is "the"
	original would silently attribute one object's history to another.
	"""
	seen: dict[str, list[str]] = {}
	for name, obj in objects.items():
		if not isinstance(obj, dict):
			continue
		obj_id = obj.get(ID_FIELD)
		if isinstance(obj_id, str) and obj_id:
			seen.setdefault(obj_id, []).append(name)

	return {
		obj_id: names[0]
		for obj_id, names in seen.items()
		if len(names) == 1
	}


def pair_objects(
	objs_a: dict[str, dict],
	objs_b: dict[str, dict],
) -> ObjectPairing:
	"""
	Pair objects between two serialized scenes.

	Falls back cleanly to pure name matching when neither snapshot carries
	identities, which is exactly the behaviour of every pre-0.6 snapshot.
	"""
	pairing = ObjectPairing()

	ids_a = _unique_ids(objs_a)
	ids_b = _unique_ids(objs_b)

	unmatched_a = set(objs_a)
	unmatched_b = set(objs_b)

	# 1. Identity matches — the only rename-surviving pass.
	for obj_id, name_a in sorted(ids_a.items(), key=lambda kv: kv[1]):
		name_b = ids_b.get(obj_id)
		if name_b is None:
			continue
		if name_a in unmatched_a and name_b in unmatched_b:
			pairing.matched.append((name_a, name_b))
			unmatched_a.discard(name_a)
			unmatched_b.discard(name_b)

	# 2. Name matches for everything still unpaired.
	for name in sorted(unmatched_a & unmatched_b):
		pairing.matched.append((name, name))
	unmatched_both = unmatched_a & unmatched_b
	unmatched_a -= unmatched_both
	unmatched_b -= unmatched_both

	# 3. Whatever remains genuinely appeared or disappeared.
	pairing.added = sorted(unmatched_b)
	pairing.removed = sorted(unmatched_a)
	pairing.matched.sort(key=lambda pair: pair[1])

	return pairing


def resolve_pairs(
	objs_a: dict[str, dict],
	objs_b: dict[str, dict],
	pairs: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
	"""
	Normalise an optional pairing into ``(name_a, name_b)`` tuples.

	Per-domain diff functions accept a pairing computed once by the engine so
	every domain agrees on which object is which. When called directly — as
	tests and library users do — ``pairs`` is None and plain name matching
	applies, which is the behaviour these functions have always had.
	"""
	if pairs is not None:
		return [
			(a, b) for a, b in pairs
			if a in objs_a and b in objs_b
		]
	return [(name, name) for name in sorted(set(objs_a) & set(objs_b))]
