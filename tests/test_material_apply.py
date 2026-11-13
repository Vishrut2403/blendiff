"""
tests/test_material_apply.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Writing material node changes back to a scene.

Node graphs were diffed in detail from the start and could not be applied at
all, so every material conflict was read-only. Input values and a texture
node's image are the two parts that are a plain write; the rest stays
unapplicable *with a reason*, which is what these tests pin down. A merge that
claimed to rewire a graph and did not would be worse than one that says it
cannot.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import fake_bpy
from fake_bpy import (
	FakeImage,
	FakeMaterial,
	FakeNode,
	FakeNodeSocket,
	FakeObject,
	FakeSlot,
)

from blendiff.data_model.paths import escape_name
from blendiff.diff_engine.material_diff import compare_materials
from blendiff.merge_engine.property_appliers import (
	apply_property,
	can_apply,
	unsupported_reason,
)


@pytest.fixture
def bpy():
	module = fake_bpy.install()
	yield module
	fake_bpy.uninstall()


def _cube(bpy, *nodes, material="Mat"):
	mat = FakeMaterial(material, use_nodes=True, nodes=nodes)
	bpy.data.materials.add(mat)
	obj = FakeObject("Cube")
	obj.material_slots.append(FakeSlot(mat))
	bpy.data.objects.add(obj)
	return obj


def _input_path(material, node, socket):
	return (
		f'materials["{escape_name(material)}"]'
		f'.nodes["{escape_name(node)}"]'
		f'.inputs["{escape_name(socket)}"]'
	)


# Input values

class TestNodeInput:
	def test_writes_a_float(self, bpy):
		socket = FakeNodeSocket("Roughness", "VALUE", 0.2)
		obj = _cube(bpy, FakeNode("Principled BSDF", inputs=[socket]))

		assert apply_property(
			obj, _input_path("Mat", "Principled BSDF", "Roughness"), 0.9, bpy.context)
		assert socket.default_value == pytest.approx(0.9)

	def test_writes_a_colour(self, bpy):
		socket = FakeNodeSocket("Base Color", "RGBA", [0.8, 0.8, 0.8, 1.0])
		obj = _cube(bpy, FakeNode("Principled BSDF", inputs=[socket]))

		apply_property(
			obj, _input_path("Mat", "Principled BSDF", "Base Color"),
			[1.0, 0.0, 0.0, 1.0], bpy.context)
		assert socket.default_value == [1.0, 0.0, 0.0, 1.0]

	def test_wrong_component_count_is_refused(self, bpy):
		socket = FakeNodeSocket("Base Color", "RGBA", [0.8, 0.8, 0.8, 1.0])
		obj = _cube(bpy, FakeNode("Principled BSDF", inputs=[socket]))

		with pytest.raises(ValueError, match="4 components"):
			apply_property(
				obj, _input_path("Mat", "Principled BSDF", "Base Color"),
				[1.0, 0.0, 0.0], bpy.context)
		assert socket.default_value == [0.8, 0.8, 0.8, 1.0]

	def test_names_with_quotes_survive_the_round_trip(self, bpy):
		socket = FakeNodeSocket('say "hi"', "VALUE", 0.0)
		obj = _cube(bpy, FakeNode('node "x"', inputs=[socket]), material='Mat"y')

		path = _input_path('Mat"y', 'node "x"', 'say "hi"')
		assert can_apply(path)
		apply_property(obj, path, 1.0, bpy.context)
		assert socket.default_value == pytest.approx(1.0)

	def test_linked_socket_is_refused(self, bpy):
		socket = FakeNodeSocket("Roughness", "VALUE", 0.2, is_linked=True)
		obj = _cube(bpy, FakeNode("Principled BSDF", inputs=[socket]))

		with pytest.raises(ValueError, match="linked"):
			apply_property(
				obj, _input_path("Mat", "Principled BSDF", "Roughness"), 0.9, bpy.context)
		assert socket.default_value == pytest.approx(0.2)

	def test_duplicate_socket_names_are_refused(self, bpy):
		# A Math node has three inputs all called "Value". The extractor keeps
		# only the last, so writing by name would be a guess.
		first = FakeNodeSocket("Value", "VALUE", 0.0)
		second = FakeNodeSocket("Value", "VALUE", 0.0)
		obj = _cube(bpy, FakeNode("Math", "MATH", inputs=[first, second]))

		with pytest.raises(ValueError, match="2 inputs named"):
			apply_property(obj, _input_path("Mat", "Math", "Value"), 1.0, bpy.context)
		assert first.default_value == 0.0
		assert second.default_value == 0.0

	def test_missing_socket_is_refused(self, bpy):
		obj = _cube(bpy, FakeNode("Principled BSDF", inputs=[]))

		with pytest.raises(ValueError, match="no input named"):
			apply_property(
				obj, _input_path("Mat", "Principled BSDF", "Roughness"), 0.9, bpy.context)

	def test_missing_node_is_refused(self, bpy):
		obj = _cube(bpy, FakeNode("Principled BSDF", inputs=[]))

		with pytest.raises(ValueError, match="no node named"):
			apply_property(obj, _input_path("Mat", "Emission", "Strength"), 1.0, bpy.context)

	def test_material_not_on_this_object_is_refused(self, bpy):
		# Another material of the same shape exists in the file; writing to it
		# would change a different object's look and report success here.
		other = FakeMaterial("Other", use_nodes=True,
		                     nodes=[FakeNode("Principled BSDF",
		                                     inputs=[FakeNodeSocket("Roughness")])])
		bpy.data.materials.add(other)
		obj = _cube(bpy, FakeNode("Principled BSDF", inputs=[FakeNodeSocket("Roughness")]))

		with pytest.raises(ValueError, match="no material named"):
			apply_property(
				obj, _input_path("Other", "Principled BSDF", "Roughness"), 0.9, bpy.context)
		assert other.node_tree.nodes.get("Principled BSDF").inputs[0].default_value == 0.0

	def test_material_without_nodes_is_refused(self, bpy):
		mat = FakeMaterial("Mat")
		bpy.data.materials.add(mat)
		obj = FakeObject("Cube")
		obj.material_slots.append(FakeSlot(mat))
		bpy.data.objects.add(obj)

		with pytest.raises(ValueError, match="no node tree"):
			apply_property(
				obj, _input_path("Mat", "Principled BSDF", "Roughness"), 0.9, bpy.context)


# Texture images

class TestNodeImage:
	def _path(self, node="Image Texture"):
		return f'materials["Mat"].nodes["{node}"].image'

	def test_assigns_an_existing_image(self, bpy):
		image = FakeImage("bark.png")
		bpy.data.images.add(image)
		node = FakeNode("Image Texture", "TEX_IMAGE")
		obj = _cube(bpy, node)

		assert apply_property(obj, self._path(), "bark.png", bpy.context)
		assert node.image is image

	def test_clears_the_image(self, bpy):
		node = FakeNode("Image Texture", "TEX_IMAGE", image=FakeImage("bark.png"))
		obj = _cube(bpy, node)

		apply_property(obj, self._path(), None, bpy.context)
		assert node.image is None

	def test_unknown_image_is_refused(self, bpy):
		node = FakeNode("Image Texture", "TEX_IMAGE")
		obj = _cube(bpy, node)

		with pytest.raises(ValueError, match="No image named"):
			apply_property(obj, self._path(), "missing.png", bpy.context)
		assert node.image is None

	def test_node_without_an_image_is_refused(self, bpy):
		obj = _cube(bpy, FakeNode("Principled BSDF"))

		with pytest.raises(ValueError, match="holds no image"):
			apply_property(obj, self._path("Principled BSDF"), "bark.png", bpy.context)


# What stays unapplicable, and why

class TestUnapplicable:
	@pytest.mark.parametrize("path, expected", [
		('materials["Mat"].use_nodes', "replaces the whole graph"),
		('materials["Mat"].links', "Rewiring"),
		('materials["Mat"].nodes["Emission"]', "Adding or removing a node"),
		('materials["Mat"].nodes["Emission"].type', "replaces it"),
	])
	def test_reason_is_specific(self, path, expected):
		assert not can_apply(path)
		assert expected in unsupported_reason(path)

	def test_no_generic_fallback_for_material_paths(self):
		# Anything material-shaped that slips past the specific patterns must
		# still read as a material limit, not as "cannot apply this property".
		reason = unsupported_reason('materials["Mat"].something_new')
		assert "material" in reason.lower()


# The diff and the applier must agree on the path shape

def test_every_input_change_the_diff_reports_is_applicable():
	def mat(roughness):
		return {
			"name": "Mat",
			"use_nodes": True,
			"nodes": {"Principled BSDF": {
				"name": "Principled BSDF",
				"type": "BSDF_PRINCIPLED",
				"inputs": {"Roughness": {
					"name": "Roughness", "type": "VALUE", "value": roughness}},
				"image_name": None,
			}},
			"links": [],
		}

	changes = compare_materials(mat(0.2), mat(0.9), "Mat.001")
	assert changes
	assert all(can_apply(change.property_path) for change in changes)
