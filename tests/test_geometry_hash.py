"""
tests/test_geometry_hash.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Mesh geometry digests.

The gap these close: mesh capture was counts plus a bounding box, so moving a
vertex inside the existing bounds changed nothing BlenDiff recorded and the
edit was reported as no change at all.

The two properties that matter are opposites, and both are load-bearing:
identical geometry must always produce an identical digest (or every diff fills
with phantom edits), and any real change must produce a different one (or the
feature does nothing).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.extractor import geometry_hash as gh


class FakeCollection:
	"""
	Stands in for a bpy collection that supports len() and foreach_get.

	foreach_get fills a caller-supplied buffer in place, which is the fast
	C-side path the extractor relies on, so the fake must behave the same way.
	"""

	def __init__(self, flat_values, width):
		self._values = list(flat_values)
		self._width = width

	def __len__(self):
		return len(self._values) // self._width

	def foreach_get(self, attr, buffer):
		buffer[:] = self._values


class FakeUVLayer:
	def __init__(self, name, uvs):
		self.name = name
		self.data = FakeCollection(uvs, 2)


class FakeMesh:
	def __init__(self, verts=(), loops=(), totals=(), edges=(), uv_layers=()):
		self.vertices = FakeCollection(verts, 3)
		self.loops = FakeCollection(loops, 1)
		self.polygons = FakeCollection(totals, 1)
		self.edges = FakeCollection(edges, 2)
		self.uv_layers = list(uv_layers)


def _cube_verts():
	return [
		0.0, 0.0, 0.0,  1.0, 0.0, 0.0,
		1.0, 1.0, 0.0,  0.0, 1.0, 0.0,
	]


class TestQuantize:
	def test_rounds_to_grid(self):
		assert gh.quantize(1.0) == 10 ** gh.PRECISION

	def test_negative_values(self):
		assert gh.quantize(-1.0) == -(10 ** gh.PRECISION)

	def test_zero(self):
		assert gh.quantize(0.0) == 0

	def test_sub_precision_noise_collapses(self):
		"""
		Below the grid, two coordinates are the same coordinate.

		Without this, any operation that round-trips a float through a slightly
		different code path would register as a geometry edit.
		"""
		assert gh.quantize(1.0) == gh.quantize(1.0 + 1e-9)

	def test_above_precision_is_distinct(self):
		assert gh.quantize(1.0) != gh.quantize(1.001)


class TestHashFloats:
	def test_is_deterministic(self):
		assert gh.hash_floats([1.0, 2.0]) == gh.hash_floats([1.0, 2.0])

	def test_differs_for_different_values(self):
		assert gh.hash_floats([1.0, 2.0]) != gh.hash_floats([1.0, 2.5])

	def test_order_matters(self):
		"""Vertex order is part of the mesh; swapping two is a real change."""
		assert gh.hash_floats([1.0, 2.0]) != gh.hash_floats([2.0, 1.0])

	def test_noise_below_precision_is_ignored(self):
		assert gh.hash_floats([1.0, 2.0]) == gh.hash_floats([1.0 + 1e-9, 2.0])

	def test_empty_is_sentinel(self):
		assert gh.hash_floats([]) == gh.EMPTY

	def test_length_matters(self):
		assert gh.hash_floats([1.0]) != gh.hash_floats([1.0, 0.0])

	def test_digest_is_versioned_hex(self):
		"""
		Digests carry the format version, so a snapshot from before the hash
		changed is treated as not comparable rather than as a scene where
		every mesh was edited.
		"""
		digest = gh.hash_floats([1.0])
		version, _, body = digest.partition(":")
		assert int(version) == gh.HASH_VERSION
		assert len(body) == 32
		int(body, 16)  # raises if not hex


class TestHashInts:
	def test_is_deterministic(self):
		assert gh.hash_ints([0, 1, 2]) == gh.hash_ints([0, 1, 2])

	def test_differs_for_different_indices(self):
		assert gh.hash_ints([0, 1, 2]) != gh.hash_ints([0, 1, 3])

	def test_empty_is_sentinel(self):
		assert gh.hash_ints([]) == gh.EMPTY

	def test_does_not_collide_with_float_hash_of_same_digits(self):
		"""Indices and coordinates are different data and must not alias."""
		assert gh.hash_ints([1, 2]) != gh.hash_floats([1.0, 2.0])


class TestCombine:
	def test_is_deterministic(self):
		assert gh.combine(["a", "b"]) == gh.combine(["a", "b"])

	def test_order_matters(self):
		assert gh.combine(["a", "b"]) != gh.combine(["b", "a"])

	def test_empty_list_is_sentinel(self):
		assert gh.combine([]) == gh.EMPTY

	def test_all_empty_parts_is_sentinel(self):
		assert gh.combine([gh.EMPTY, gh.EMPTY]) == gh.EMPTY

	def test_one_real_part_produces_a_digest(self):
		assert gh.combine([gh.EMPTY, "abc"]) not in (gh.EMPTY, "abc")


class TestVertexPositions:
	def test_identical_meshes_match(self):
		a = FakeMesh(verts=_cube_verts())
		b = FakeMesh(verts=_cube_verts())
		assert gh.hash_vertex_positions(a) == gh.hash_vertex_positions(b)

	def test_moved_vertex_is_detected(self):
		"""The whole point: an edit that changes no count and no bound."""
		moved = _cube_verts()
		moved[0] = 0.5
		assert gh.hash_vertex_positions(FakeMesh(verts=_cube_verts())) != \
			gh.hash_vertex_positions(FakeMesh(verts=moved))

	def test_sub_precision_move_is_not_detected(self):
		nudged = _cube_verts()
		nudged[0] += 1e-9
		assert gh.hash_vertex_positions(FakeMesh(verts=_cube_verts())) == \
			gh.hash_vertex_positions(FakeMesh(verts=nudged))

	def test_empty_mesh(self):
		assert gh.hash_vertex_positions(FakeMesh()) == gh.EMPTY


class TestTopology:
	def test_identical_topology_matches(self):
		kwargs = dict(loops=[0, 1, 2, 3], totals=[4], edges=[0, 1, 1, 2, 2, 3, 3, 0])
		assert gh.hash_topology(FakeMesh(**kwargs)) == gh.hash_topology(FakeMesh(**kwargs))

	def test_changed_face_winding_is_detected(self):
		a = FakeMesh(loops=[0, 1, 2, 3], totals=[4])
		b = FakeMesh(loops=[0, 1, 3, 2], totals=[4])
		assert gh.hash_topology(a) != gh.hash_topology(b)

	def test_face_split_is_detected(self):
		"""One quad versus two triangles over the same corners."""
		a = FakeMesh(loops=[0, 1, 2, 3], totals=[4])
		b = FakeMesh(loops=[0, 1, 2, 0, 2, 3], totals=[3, 3])
		assert gh.hash_topology(a) != gh.hash_topology(b)

	def test_loose_edge_change_is_detected(self):
		a = FakeMesh(loops=[0, 1, 2], totals=[3], edges=[0, 1])
		b = FakeMesh(loops=[0, 1, 2], totals=[3], edges=[0, 2])
		assert gh.hash_topology(a) != gh.hash_topology(b)

	def test_topology_ignores_vertex_positions(self):
		"""Moving a vertex must not disturb the topology digest."""
		moved = _cube_verts()
		moved[0] = 9.0
		a = FakeMesh(verts=_cube_verts(), loops=[0, 1, 2, 3], totals=[4])
		b = FakeMesh(verts=moved, loops=[0, 1, 2, 3], totals=[4])
		assert gh.hash_topology(a) == gh.hash_topology(b)

	def test_empty_mesh(self):
		assert gh.hash_topology(FakeMesh()) == gh.EMPTY


class TestUVs:
	def test_identical_uvs_match(self):
		layers = [FakeUVLayer("UVMap", [0.0, 0.0, 1.0, 0.0])]
		assert gh.hash_uvs(FakeMesh(uv_layers=layers)) == \
			gh.hash_uvs(FakeMesh(uv_layers=list(layers)))

	def test_moved_uv_is_detected(self):
		a = FakeMesh(uv_layers=[FakeUVLayer("UVMap", [0.0, 0.0, 1.0, 0.0])])
		b = FakeMesh(uv_layers=[FakeUVLayer("UVMap", [0.0, 0.0, 0.5, 0.0])])
		assert gh.hash_uvs(a) != gh.hash_uvs(b)

	def test_renamed_layer_is_detected(self):
		"""Shaders reference UV maps by name, so a rename is a real change."""
		a = FakeMesh(uv_layers=[FakeUVLayer("UVMap", [0.0, 0.0])])
		b = FakeMesh(uv_layers=[FakeUVLayer("Lightmap", [0.0, 0.0])])
		assert gh.hash_uvs(a) != gh.hash_uvs(b)

	def test_added_layer_is_detected(self):
		a = FakeMesh(uv_layers=[FakeUVLayer("UVMap", [0.0, 0.0])])
		b = FakeMesh(uv_layers=[
			FakeUVLayer("UVMap", [0.0, 0.0]),
			FakeUVLayer("Lightmap", [0.0, 0.0]),
		])
		assert gh.hash_uvs(a) != gh.hash_uvs(b)

	def test_no_layers(self):
		assert gh.hash_uvs(FakeMesh()) == gh.EMPTY


class TestExtractGeometryHashes:
	def test_returns_all_three_digests(self):
		hashes = gh.extract_geometry_hashes(FakeMesh(verts=_cube_verts()))
		assert set(hashes) == {"vertex_hash", "topology_hash", "uv_hash"}

	def test_digests_are_independent(self):
		"""A position change must move one digest and leave the others alone."""
		moved = _cube_verts()
		moved[0] = 5.0
		base = gh.extract_geometry_hashes(
			FakeMesh(verts=_cube_verts(), loops=[0, 1, 2], totals=[3]))
		after = gh.extract_geometry_hashes(
			FakeMesh(verts=moved, loops=[0, 1, 2], totals=[3]))

		assert base["vertex_hash"] != after["vertex_hash"]
		assert base["topology_hash"] == after["topology_hash"]
		assert base["uv_hash"] == after["uv_hash"]

	def test_failure_degrades_to_sentinel(self):
		"""
		One unreadable attribute must not cost the whole snapshot, matching how
		the rest of extraction handles partial failure.
		"""
		class Exploding:
			"""Readable topology and UVs, but vertex access raises."""

			loops = FakeCollection([0, 1, 2], 1)
			polygons = FakeCollection([3], 1)
			edges = FakeCollection([], 2)
			uv_layers = []

			@property
			def vertices(self):
				raise RuntimeError("boom")

		hashes = gh.extract_geometry_hashes(Exploding())
		assert hashes["vertex_hash"] == gh.EMPTY
		# The digests that could be read are still present and real.
		assert hashes["topology_hash"] != gh.EMPTY

	def test_never_raises(self):
		class Nothing:
			pass

		hashes = gh.extract_geometry_hashes(Nothing())
		assert all(v == gh.EMPTY for v in hashes.values())


class TestHashVersioning:
	"""
	The digest format changed when hashing was vectorised: version 1 built a
	comma-joined decimal string in Python at about 3.5 microseconds per float,
	which put a two-million-vertex sculpt near twenty seconds per snapshot.

	Comparing a v1 digest against a v2 one is meaningless, and reporting it as
	a difference would fill the first diff after an upgrade with geometry edits
	nobody made.
	"""

	def test_unprefixed_digest_reads_as_version_1(self):
		assert gh.hash_version("abcdef0123456789") == 1

	def test_current_digests_carry_the_version(self):
		assert gh.hash_version(gh.hash_floats([1.0])) == gh.HASH_VERSION

	def test_same_version_is_comparable(self):
		assert gh.comparable(gh.hash_floats([1.0]), gh.hash_floats([2.0]))

	def test_across_versions_is_not_comparable(self):
		assert not gh.comparable(gh.hash_floats([1.0]), "abcdef0123456789")

	def test_malformed_digest_reads_as_version_1(self):
		assert gh.hash_version("notaversion:abc") == 1

	def test_non_string_reads_as_version_1(self):
		assert gh.hash_version(None) == 1


class TestVectorisedPacking:
	"""
	Hashing runs through numpy when available and pure Python otherwise. Both
	must produce identical bytes, or a machine without numpy would disagree
	with one that has it about whether a mesh changed.
	"""

	def _values(self):
		return [0.0, 1.0, -2.5, 1e-9, 123.456789, -0.0000005, 1e6]

	def test_numpy_and_fallback_agree(self):
		values = self._values()
		fast = gh._pack_quantised(values)
		slow = gh._pack_quantised_python(values)
		assert fast is not None, "numpy should be available here"
		assert fast == slow

	def test_empty_input_agrees(self):
		assert gh._pack_quantised([]) == gh._pack_quantised_python([]) == b""

	def test_digest_matches_whichever_path_ran(self):
		values = self._values()
		from hashlib import blake2b
        # Recompute the expected digest from the fallback bytes directly.
		expected = blake2b(gh._pack_quantised_python(values), digest_size=16).hexdigest()
		assert gh.hash_floats(values) == f"{gh.HASH_VERSION}:{expected}"

	def test_indices_do_not_alias_coordinates(self):
		"""Index data is tagged, so 1,2 as indices differs from 1.0,2.0 as coords."""
		assert gh.hash_ints([1, 2]) != gh.hash_floats([1.0, 2.0])
