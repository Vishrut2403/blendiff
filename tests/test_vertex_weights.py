"""
tests/test_vertex_weights.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Vertex group weights, hashed per group.

Weights have no bulk read. Coordinates come out of foreach_get in one C-side
call; every vertex's group memberships have to be walked in Python. Measured
on a 32k vertex character with 40 groups and 100k assignments: 35 ms to walk,
101 ms to walk and collect, against 23 ms for the whole snapshot as it stood.

So they are hashed rather than stored, the bargain mesh geometry already
makes. A digest per group answers "did the weights on this group change",
which is the question a rigger asks, and costs 32 characters to keep.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.diff_engine.mesh_diff import diff_mesh_data
from blendiff.extractor.geometry_hash import EMPTY
from blendiff.extractor.mesh_extractor import extract_vertex_group_weights


class Entry:
	def __init__(self, group, weight):
		self.group = group
		self.weight = weight


class Vertex:
	def __init__(self, index, groups=()):
		self.index = index
		self.groups = list(groups)


class Mesh:
	def __init__(self, vertices):
		self.vertices = vertices


class Group:
	def __init__(self, index, name):
		self.index = index
		self.name = name


class Obj:
	def __init__(self, groups=(), name="Body"):
		self.name = name
		self.vertex_groups = list(groups)


class TestExtraction:

	def _rig(self, assignments):
		"""assignments: {vertex index: [(group index, weight), ...]}"""
		groups = [Group(0, "Spine"), Group(1, "Head")]
		vertices = [
			Vertex(i, [Entry(g, w) for g, w in assignments.get(i, [])])
			for i in range(4)
		]
		return Obj(groups), Mesh(vertices)

	def test_each_group_gets_its_own_digest(self):
		obj, mesh = self._rig({0: [(0, 0.5)], 1: [(1, 0.25)]})
		weights = extract_vertex_group_weights(obj, mesh)

		assert set(weights) == {"Spine", "Head"}
		assert weights["Spine"] != weights["Head"]

	def test_an_object_with_no_groups_costs_nothing(self):
		# Most objects have none, and the walk is skipped entirely rather
		# than run and thrown away.
		assert extract_vertex_group_weights(Obj(), Mesh([])) == {}

	def test_a_group_with_no_assignments_is_empty_not_missing(self):
		obj, mesh = self._rig({0: [(0, 0.5)]})
		weights = extract_vertex_group_weights(obj, mesh)

		assert weights["Head"] == EMPTY

	def test_the_same_weights_hash_the_same(self):
		first = extract_vertex_group_weights(*self._rig({0: [(0, 0.5)]}))
		second = extract_vertex_group_weights(*self._rig({0: [(0, 0.5)]}))
		assert first == second

	def test_a_changed_weight_changes_the_digest(self):
		before = extract_vertex_group_weights(*self._rig({0: [(0, 0.5)]}))
		after = extract_vertex_group_weights(*self._rig({0: [(0, 0.9)]}))
		assert before["Spine"] != after["Spine"]

	def test_moving_a_weight_to_another_vertex_changes_the_digest(self):
		"""
		The vertex index is hashed alongside the weight.

		The same value on a different vertex deforms the mesh differently, so
		hashing weights alone would miss a real change.
		"""
		before = extract_vertex_group_weights(*self._rig({0: [(0, 0.5)]}))
		after = extract_vertex_group_weights(*self._rig({1: [(0, 0.5)]}))
		assert before["Spine"] != after["Spine"]

	def test_a_mesh_that_cannot_be_walked_degrades_to_nothing(self):
		class Hostile:
			@property
			def vertices(self):
				raise RuntimeError("no")

		assert extract_vertex_group_weights(Obj([Group(0, "Spine")]), Hostile()) == {}


class TestDiffing:

	def _mesh(self, weights):
		return {"vertex_count": 4, "vertex_group_weights": weights}

	def test_a_changed_group_is_named_in_the_path(self):
		before = self._mesh({"Spine": "2:aaa", "Head": "2:bbb"})
		after = self._mesh({"Spine": "2:aaa", "Head": "2:ccc"})

		paths = [c.property_path for c in diff_mesh_data(before, after)]
		assert paths == ['mesh.vertex_groups["Head"].weights']

	def test_unchanged_weights_report_nothing(self):
		same = self._mesh({"Spine": "2:aaa"})
		assert diff_mesh_data(same, dict(same)) == []

	def test_a_group_on_only_one_side_is_not_reported_here(self):
		# Adding or removing a group is already reported by the name list.
		before = self._mesh({"Spine": "2:aaa"})
		after = self._mesh({"Spine": "2:aaa", "Head": "2:bbb"})

		assert diff_mesh_data(before, after) == []

	def test_a_snapshot_from_before_weights_were_hashed_invents_nothing(self):
		before = {"vertex_count": 4}
		after = self._mesh({"Spine": "2:aaa"})

		assert diff_mesh_data(before, after) == []

	def test_digests_from_different_formats_are_not_compared(self):
		before = self._mesh({"Spine": "aaa"})      # pre-versioned digest
		after = self._mesh({"Spine": "2:bbb"})

		assert diff_mesh_data(before, after) == []

	def test_a_group_name_with_a_quote_survives_the_path(self):
		before = self._mesh({'say "hi"': "2:aaa"})
		after = self._mesh({'say "hi"': "2:bbb"})

		paths = [c.property_path for c in diff_mesh_data(before, after)]
		assert paths == ['mesh.vertex_groups["say \\"hi\\""].weights']
