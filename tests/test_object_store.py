"""
tests/test_object_store.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Content-addressed deduplication of snapshot payloads.

Every snapshot used to store the whole scene again, even when one object moved:
24.6 MB and a 280 ms parse for 80 objects across 50 snapshots, paid every time
the snapshot list was drawn. Storing each distinct object once brings that to
1.6 MB and 17 ms.

Two invariants carry the feature. Packing then unpacking must return exactly
what went in, or history is silently corrupted; and objects no snapshot
references any more must be reclaimed, or deleting a snapshot frees nothing.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.storage.object_store import (
	collect_garbage,
	digest_object,
	is_packed,
	pack_scene,
	pool_stats,
	referenced_digests,
	unpack_scene,
)


def _obj(name="Cube", **extra):
	data = {"name": name, "type": "MESH", "transform": {"location": [0, 0, 0]}}
	data.update(extra)
	return data


def _scene(objects, **extra):
	scene = {"objects": objects, "collections": {}, "scene_name": "Scene"}
	scene.update(extra)
	return scene


class TestDigest:
	def test_is_deterministic(self):
		assert digest_object(_obj()) == digest_object(_obj())

	def test_differs_for_different_content(self):
		assert digest_object(_obj("A")) != digest_object(_obj("B"))

	def test_key_order_does_not_matter(self):
		"""
		Dicts built in different orders describe the same object. Without a
		stable key order, deduplication would silently stop working whenever
		construction order shifted.
		"""
		a = {"name": "Cube", "type": "MESH"}
		b = {"type": "MESH", "name": "Cube"}
		assert digest_object(a) == digest_object(b)

	def test_nested_content_is_covered(self):
		a = _obj(transform={"location": [0, 0, 0]})
		b = _obj(transform={"location": [1, 0, 0]})
		assert digest_object(a) != digest_object(b)

	def test_digest_is_short_hex(self):
		digest = digest_object(_obj())
		assert len(digest) == 32
		int(digest, 16)


class TestPacking:
	def test_pack_replaces_objects_with_references(self):
		pool = {}
		packed = pack_scene(_scene({"Cube": _obj()}), pool)
		assert isinstance(packed["objects"]["Cube"], str)

	def test_pack_fills_the_pool(self):
		pool = {}
		pack_scene(_scene({"Cube": _obj()}), pool)
		assert len(pool) == 1

	def test_identical_objects_are_stored_once(self):
		"""The entire point: the same object across snapshots costs one copy."""
		pool = {}
		for _ in range(10):
			pack_scene(_scene({"Cube": _obj()}), pool)
		assert len(pool) == 1

	def test_distinct_objects_are_stored_separately(self):
		pool = {}
		pack_scene(_scene({"A": _obj("A"), "B": _obj("B")}), pool)
		assert len(pool) == 2

	def test_pack_does_not_mutate_the_input(self):
		"""Callers keep the live scene dict and must not see it change."""
		scene = _scene({"Cube": _obj()})
		pack_scene(scene, {})
		assert isinstance(scene["objects"]["Cube"], dict)

	def test_pack_preserves_other_scene_keys(self):
		packed = pack_scene(_scene({"Cube": _obj()}, render={"engine": "CYCLES"}), {})
		assert packed["render"] == {"engine": "CYCLES"}
		assert packed["collections"] == {}

	def test_packing_twice_is_stable(self):
		pool = {}
		once = pack_scene(_scene({"Cube": _obj()}), pool)
		twice = pack_scene(once, pool)
		assert once == twice
		assert len(pool) == 1

	def test_scene_without_objects_is_untouched(self):
		scene = {"collections": {}}
		assert pack_scene(scene, {}) == scene


class TestUnpacking:
	def test_round_trip_returns_the_original(self):
		"""If this ever fails, stored history is silently corrupted."""
		pool = {}
		scene = _scene({"A": _obj("A"), "B": _obj("B")})
		assert unpack_scene(pack_scene(scene, pool), pool) == scene

	def test_round_trip_survives_many_snapshots(self):
		pool = {}
		scenes = [_scene({f"Obj{i}": _obj(f"Obj{i}", tag=n)}) for n in range(5) for i in range(3)]
		packed = [pack_scene(s, pool) for s in scenes]
		assert [unpack_scene(p, pool) for p in packed] == scenes

	def test_legacy_inline_objects_pass_through(self):
		"""A pre-0.3 sidecar stores objects inline and must still open."""
		scene = _scene({"Cube": _obj()})
		assert unpack_scene(scene, {}) == scene

	def test_missing_reference_is_dropped_not_raised(self):
		"""
		A hand-edited or damaged sidecar loses one object rather than refusing
		to open the entire snapshot history.
		"""
		scene = _scene({"Cube": "deadbeef", "Lamp": _obj("Lamp")})
		result = unpack_scene(scene, {})
		assert "Cube" not in result["objects"]
		assert "Lamp" in result["objects"]

	def test_unpack_does_not_mutate_the_input(self):
		pool = {}
		packed = pack_scene(_scene({"Cube": _obj()}), pool)
		unpack_scene(packed, pool)
		assert isinstance(packed["objects"]["Cube"], str)

	def test_scene_without_objects_is_untouched(self):
		scene = {"collections": {}}
		assert unpack_scene(scene, {}) == scene


class TestIsPacked:
	def test_packed_scene_detected(self):
		assert is_packed(pack_scene(_scene({"Cube": _obj()}), {}))

	def test_inline_scene_not_packed(self):
		assert not is_packed(_scene({"Cube": _obj()}))

	def test_empty_objects_not_packed(self):
		assert not is_packed(_scene({}))

	def test_missing_objects_key_not_packed(self):
		assert not is_packed({"collections": {}})


class TestGarbageCollection:
	def test_unreferenced_objects_are_reclaimed(self):
		"""Without this, deleting a snapshot would free nothing."""
		pool = {}
		kept = pack_scene(_scene({"Cube": _obj("Cube")}), pool)
		pack_scene(_scene({"Gone": _obj("Gone")}), pool)
		assert len(pool) == 2

		removed = collect_garbage(pool, [kept])
		assert removed == 1
		assert len(pool) == 1

	def test_referenced_objects_survive(self):
		pool = {}
		scene = pack_scene(_scene({"Cube": _obj()}), pool)
		collect_garbage(pool, [scene])
		assert unpack_scene(scene, pool)["objects"]["Cube"]["name"] == "Cube"

	def test_object_shared_by_two_snapshots_survives_one_deletion(self):
		pool = {}
		a = pack_scene(_scene({"Cube": _obj()}), pool)
		b = pack_scene(_scene({"Cube": _obj()}), pool)
		collect_garbage(pool, [b])          # snapshot A deleted
		assert unpack_scene(a, pool)["objects"]["Cube"]["name"] == "Cube"

	def test_collecting_with_no_snapshots_empties_the_pool(self):
		pool = {}
		pack_scene(_scene({"Cube": _obj()}), pool)
		assert collect_garbage(pool, []) == 1
		assert pool == {}

	def test_collect_is_idempotent(self):
		pool = {}
		scene = pack_scene(_scene({"Cube": _obj()}), pool)
		collect_garbage(pool, [scene])
		assert collect_garbage(pool, [scene]) == 0

	def test_referenced_digests_ignores_inline_objects(self):
		assert referenced_digests([_scene({"Cube": _obj()})]) == set()


class TestPoolStats:
	def test_reports_savings(self):
		pool = {}
		scenes = [pack_scene(_scene({"Cube": _obj()}), pool) for _ in range(10)]
		stats = pool_stats(pool, scenes)
		assert stats["stored"] == 1
		assert stats["references"] == 10
		assert stats["saved"] == 9

	def test_no_savings_when_everything_differs(self):
		pool = {}
		scenes = [pack_scene(_scene({f"O{i}": _obj(f"O{i}")}), pool) for i in range(5)]
		stats = pool_stats(pool, scenes)
		assert stats["stored"] == 5 and stats["saved"] == 0

	def test_empty_history(self):
		assert pool_stats({}, [])["stored"] == 0
