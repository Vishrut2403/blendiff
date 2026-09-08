"""
tests/test_identity_match.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Object pairing across snapshots.

The behaviour under test is the one that matters most for a version control
tool: a rename must not destroy an object's history.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.diff_engine.identity_match import (
	ObjectPairing,
	pair_objects,
	resolve_pairs,
)


def _obj(obj_id=None, **extra):
	data = dict(extra)
	if obj_id is not None:
		data["blendiff_id"] = obj_id
	return data


class TestNameFallback:
	"""Snapshots with no identities behave exactly as they always did."""

	def test_identical_names_all_matched(self):
		a = {"Cube": _obj(), "Lamp": _obj()}
		p = pair_objects(a, dict(a))
		assert p.matched == [("Cube", "Cube"), ("Lamp", "Lamp")]
		assert p.added == [] and p.removed == []

	def test_added_object(self):
		p = pair_objects({"Cube": _obj()}, {"Cube": _obj(), "Lamp": _obj()})
		assert p.added == ["Lamp"]
		assert p.removed == []

	def test_removed_object(self):
		p = pair_objects({"Cube": _obj(), "Lamp": _obj()}, {"Cube": _obj()})
		assert p.removed == ["Lamp"]
		assert p.added == []

	def test_rename_without_ids_is_add_plus_remove(self):
		"""Without identity there is no way to know a rename happened."""
		p = pair_objects({"Cube": _obj()}, {"Body": _obj()})
		assert p.added == ["Body"]
		assert p.removed == ["Cube"]
		assert p.renamed == []

	def test_empty_scenes(self):
		p = pair_objects({}, {})
		assert p.matched == [] and p.added == [] and p.removed == []


class TestIdentityMatching:
	def test_rename_is_matched_by_id(self):
		a = {"Cube": _obj("id-1")}
		b = {"Body_LOW": _obj("id-1")}
		p = pair_objects(a, b)
		assert p.matched == [("Cube", "Body_LOW")]
		assert p.renamed == [("Cube", "Body_LOW")]
		assert p.added == [] and p.removed == []

	def test_unchanged_name_with_id_still_matches(self):
		p = pair_objects({"Cube": _obj("id-1")}, {"Cube": _obj("id-1")})
		assert p.matched == [("Cube", "Cube")]
		assert p.renamed == []

	def test_different_ids_are_not_paired(self):
		"""Same name, different identity — a replaced object, not an edit."""
		p = pair_objects({"Cube": _obj("id-1")}, {"Cube": _obj("id-2")})
		assert p.matched == [("Cube", "Cube")]

	def test_id_match_wins_over_name_match(self):
		"""
		Two objects swapping names must follow their identities, not their
		names, or each would inherit the other's history.
		"""
		a = {"Cube": _obj("id-1"), "Sphere": _obj("id-2")}
		b = {"Sphere": _obj("id-1"), "Cube": _obj("id-2")}
		p = pair_objects(a, b)
		assert sorted(p.matched) == [("Cube", "Sphere"), ("Sphere", "Cube")]
		assert p.added == [] and p.removed == []

	def test_mixed_identified_and_unidentified(self):
		a = {"Cube": _obj("id-1"), "Legacy": _obj()}
		b = {"Renamed": _obj("id-1"), "Legacy": _obj()}
		p = pair_objects(a, b)
		assert ("Cube", "Renamed") in p.matched
		assert ("Legacy", "Legacy") in p.matched
		assert p.added == [] and p.removed == []

	def test_renamed_and_added_together(self):
		a = {"Cube": _obj("id-1")}
		b = {"Body": _obj("id-1"), "New": _obj("id-2")}
		p = pair_objects(a, b)
		assert p.renamed == [("Cube", "Body")]
		assert p.added == ["New"]

	def test_object_with_id_removed(self):
		p = pair_objects({"Cube": _obj("id-1")}, {})
		assert p.removed == ["Cube"]


class TestDuplicateIds:
	"""
	Shift+D copies custom properties, so two objects can share an id. An
	ambiguous id must never be used to pair, or one object inherits another's
	history.
	"""

	def test_duplicate_id_falls_back_to_name(self):
		a = {"Cube": _obj("id-1")}
		b = {"Cube": _obj("id-1"), "Cube.001": _obj("id-1")}
		p = pair_objects(a, b)
		assert p.matched == [("Cube", "Cube")]
		assert p.added == ["Cube.001"]

	def test_duplicate_on_both_sides_uses_names(self):
		a = {"Cube": _obj("dup"), "Cube.001": _obj("dup")}
		b = {"Cube": _obj("dup"), "Cube.001": _obj("dup")}
		p = pair_objects(a, b)
		assert sorted(p.matched) == [("Cube", "Cube"), ("Cube.001", "Cube.001")]

	def test_duplicate_does_not_produce_phantom_rename(self):
		a = {"Cube": _obj("dup"), "Cube.001": _obj("dup")}
		b = {"Cube": _obj("dup"), "Cube.001": _obj("dup")}
		assert pair_objects(a, b).renamed == []

	def test_empty_string_id_is_ignored(self):
		p = pair_objects({"Cube": _obj("")}, {"Body": _obj("")})
		assert p.added == ["Body"] and p.removed == ["Cube"]

	def test_non_string_id_is_ignored(self):
		p = pair_objects({"Cube": {"blendiff_id": 42}}, {"Body": {"blendiff_id": 42}})
		assert p.added == ["Body"] and p.removed == ["Cube"]


class TestResolvePairs:
	def test_none_falls_back_to_name_intersection(self):
		a = {"Cube": {}, "Lamp": {}}
		b = {"Cube": {}, "Sphere": {}}
		assert resolve_pairs(a, b, None) == [("Cube", "Cube")]

	def test_explicit_pairs_are_used(self):
		a = {"Cube": {}}
		b = {"Body": {}}
		assert resolve_pairs(a, b, [("Cube", "Body")]) == [("Cube", "Body")]

	def test_pairs_referencing_missing_objects_are_dropped(self):
		"""A stale pairing must never index into a dict that lacks the key."""
		a = {"Cube": {}}
		b = {"Body": {}}
		assert resolve_pairs(a, b, [("Ghost", "Body"), ("Cube", "Body")]) == [
			("Cube", "Body")
		]


class TestObjectPairingHelpers:
	def test_name_map(self):
		p = ObjectPairing(matched=[("Cube", "Body"), ("Lamp", "Lamp")])
		assert p.name_map_a_to_b() == {"Cube": "Body", "Lamp": "Lamp"}

	def test_renamed_excludes_unchanged(self):
		p = ObjectPairing(matched=[("Cube", "Body"), ("Lamp", "Lamp")])
		assert p.renamed == [("Cube", "Body")]
