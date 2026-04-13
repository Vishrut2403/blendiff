"""
tests/test_material_diff.py

Unit tests for diff_engine/material_diff.py and data_model/material.py.
No bpy required — runs with plain pytest.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.diff_engine.material_diff import compare_materials, _values_equal
from blendiff.data_model.material import (
	MaterialSnapshot,
	NodeSnapshot,
	NodeInputSnapshot,
	LinkSnapshot,
)


# ---------------------------------------------------------------------------
# Helpers — build test material dicts
# ---------------------------------------------------------------------------

def make_material(
	name="Material",
	use_nodes=True,
	nodes=None,
	links=None,
) -> dict:
	return {
		"name": name,
		"use_nodes": use_nodes,
		"nodes": nodes or {},
		"links": links or [],
	}


def make_node(
	name="Principled BSDF",
	type="BSDF_PRINCIPLED",
	location=None,
	inputs=None,
	image_name=None,
) -> dict:
	return {
		"name": name,
		"type": type,
		"location": location or [0.0, 0.0],
		"inputs": inputs or {},
		"image_name": image_name,
	}


def make_input(name="Base Color", type="RGBA", value=None) -> dict:
	return {
		"name": name,
		"type": type,
		"value": value if value is not None else [0.8, 0.8, 0.8, 1.0],
	}


def make_link(from_node, from_socket, to_node, to_socket) -> dict:
	return {
		"from_node": from_node,
		"from_socket": from_socket,
		"to_node": to_node,
		"to_socket": to_socket,
	}


# ---------------------------------------------------------------------------
# compare_materials — identical materials
# ---------------------------------------------------------------------------

class TestIdenticalMaterials:
	def test_identical_empty_materials(self):
		mat = make_material(nodes={}, links=[])
		assert compare_materials(mat, mat, "Material") == []

	def test_identical_with_principled_node(self):
		node = make_node(inputs={
			"Base Color": make_input("Base Color", "RGBA", [0.8, 0.2, 0.2, 1.0]),
			"Roughness": make_input("Roughness", "VALUE", 0.5),
		})
		mat = make_material(nodes={"Principled BSDF": node})
		assert compare_materials(mat, mat, "Material") == []

	def test_both_none(self):
		assert compare_materials(None, None, "Material") == []

	def test_both_not_using_nodes(self):
		mat = make_material(use_nodes=False)
		assert compare_materials(mat, mat, "Material") == []

	def test_epsilon_ignores_tiny_float_differences(self):
		node_a = make_node(inputs={"Roughness": make_input("Roughness", "VALUE", 0.5)})
		node_b = make_node(inputs={"Roughness": make_input("Roughness", "VALUE", 0.5 + 1e-5)})
		mat_a = make_material(nodes={"Principled BSDF": node_a})
		mat_b = make_material(nodes={"Principled BSDF": node_b})
		assert compare_materials(mat_a, mat_b, "Material") == []


# ---------------------------------------------------------------------------
# compare_materials — use_nodes change
# ---------------------------------------------------------------------------

class TestUseNodesChange:
	def test_use_nodes_false_to_true(self):
		mat_a = make_material(use_nodes=False)
		mat_b = make_material(use_nodes=True)
		changes = compare_materials(mat_a, mat_b, "Material")
		assert len(changes) == 1
		assert changes[0].property_path == "material[Material].use_nodes"
		assert changes[0].old_value is False
		assert changes[0].new_value is True

	def test_use_nodes_true_to_false(self):
		mat_a = make_material(use_nodes=True)
		mat_b = make_material(use_nodes=False)
		changes = compare_materials(mat_a, mat_b, "Material")
		assert len(changes) == 1
		assert changes[0].old_value is True
		assert changes[0].new_value is False


# ---------------------------------------------------------------------------
# compare_materials — node added / removed
# ---------------------------------------------------------------------------

class TestNodeAddedRemoved:
	def test_node_added(self):
		mat_a = make_material(nodes={})
		mat_b = make_material(nodes={"Emission": make_node("Emission", "EMISSION")})
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert len(changes) == 1
		assert "nodes.Emission" in changes[0].property_path
		assert changes[0].old_value is None
		assert changes[0].new_value == "EMISSION"

	def test_node_removed(self):
		mat_a = make_material(nodes={"Emission": make_node("Emission", "EMISSION")})
		mat_b = make_material(nodes={})
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert len(changes) == 1
		assert changes[0].old_value == "EMISSION"
		assert changes[0].new_value is None

	def test_multiple_nodes_added(self):
		mat_a = make_material(nodes={})
		mat_b = make_material(nodes={
			"Node A": make_node("Node A", "EMISSION"),
			"Node B": make_node("Node B", "TEX_IMAGE"),
		})
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert len(changes) == 2


# ---------------------------------------------------------------------------
# compare_materials — node type changed
# ---------------------------------------------------------------------------

class TestNodeTypeChanged:
	def test_node_type_change_detected(self):
		mat_a = make_material(nodes={"Shader": make_node("Shader", "BSDF_PRINCIPLED")})
		mat_b = make_material(nodes={"Shader": make_node("Shader", "EMISSION")})
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert len(changes) == 1
		assert "type" in changes[0].property_path
		assert changes[0].old_value == "BSDF_PRINCIPLED"
		assert changes[0].new_value == "EMISSION"

	def test_type_change_does_not_also_diff_inputs(self):
		# When type changes, input diff is skipped — inputs are meaningless
		node_a = make_node("Shader", "BSDF_PRINCIPLED",
						   inputs={"Base Color": make_input("Base Color", "RGBA", [1, 0, 0, 1])})
		node_b = make_node("Shader", "EMISSION",
						   inputs={"Color": make_input("Color", "RGBA", [0, 1, 0, 1])})
		mat_a = make_material(nodes={"Shader": node_a})
		mat_b = make_material(nodes={"Shader": node_b})
		changes = compare_materials(mat_a, mat_b, "Mat")
		# Only 1 change: the type — not the inputs
		type_changes = [c for c in changes if "type" in c.property_path]
		assert len(type_changes) == 1


# ---------------------------------------------------------------------------
# compare_materials — input value changes
# ---------------------------------------------------------------------------

class TestInputValueChanges:
	def test_float_input_change(self):
		node_a = make_node(inputs={"Roughness": make_input("Roughness", "VALUE", 0.2)})
		node_b = make_node(inputs={"Roughness": make_input("Roughness", "VALUE", 0.8)})
		mat_a = make_material(nodes={"Principled BSDF": node_a})
		mat_b = make_material(nodes={"Principled BSDF": node_b})
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert len(changes) == 1
		assert "Roughness" in changes[0].property_path
		assert changes[0].old_value == pytest.approx(0.2)
		assert changes[0].new_value == pytest.approx(0.8)

	def test_rgba_input_change(self):
		node_a = make_node(inputs={"Base Color": make_input("Base Color", "RGBA", [1, 0, 0, 1])})
		node_b = make_node(inputs={"Base Color": make_input("Base Color", "RGBA", [0, 0, 1, 1])})
		mat_a = make_material(nodes={"Principled BSDF": node_a})
		mat_b = make_material(nodes={"Principled BSDF": node_b})
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert len(changes) == 1
		assert changes[0].old_value == [1, 0, 0, 1]
		assert changes[0].new_value == [0, 0, 1, 1]

	def test_multiple_input_changes(self):
		node_a = make_node(inputs={
			"Roughness": make_input("Roughness", "VALUE", 0.2),
			"Metallic": make_input("Metallic", "VALUE", 0.0),
		})
		node_b = make_node(inputs={
			"Roughness": make_input("Roughness", "VALUE", 0.8),
			"Metallic": make_input("Metallic", "VALUE", 1.0),
		})
		mat_a = make_material(nodes={"Principled BSDF": node_a})
		mat_b = make_material(nodes={"Principled BSDF": node_b})
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert len(changes) == 2

	def test_unchanged_inputs_not_reported(self):
		node_a = make_node(inputs={
			"Roughness": make_input("Roughness", "VALUE", 0.5),
			"Metallic": make_input("Metallic", "VALUE", 0.0),
		})
		node_b = make_node(inputs={
			"Roughness": make_input("Roughness", "VALUE", 0.9),  # changed
			"Metallic": make_input("Metallic", "VALUE", 0.0),   # unchanged
		})
		mat_a = make_material(nodes={"Principled BSDF": node_a})
		mat_b = make_material(nodes={"Principled BSDF": node_b})
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert len(changes) == 1
		assert "Roughness" in changes[0].property_path


# ---------------------------------------------------------------------------
# compare_materials — image name changes
# ---------------------------------------------------------------------------

class TestImageNameChanges:
	def test_image_name_change_detected(self):
		node_a = make_node("Tex", "TEX_IMAGE", image_name="old_texture.png")
		node_b = make_node("Tex", "TEX_IMAGE", image_name="new_texture.png")
		mat_a = make_material(nodes={"Tex": node_a})
		mat_b = make_material(nodes={"Tex": node_b})
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert len(changes) == 1
		assert "image" in changes[0].property_path
		assert changes[0].old_value == "old_texture.png"
		assert changes[0].new_value == "new_texture.png"

	def test_same_image_no_change(self):
		node = make_node("Tex", "TEX_IMAGE", image_name="texture.png")
		mat = make_material(nodes={"Tex": node})
		assert compare_materials(mat, mat, "Mat") == []


# ---------------------------------------------------------------------------
# compare_materials — link changes
# ---------------------------------------------------------------------------

class TestLinkChanges:
	def test_link_added(self):
		mat_a = make_material(links=[])
		mat_b = make_material(links=[
			make_link("Tex", "Color", "Principled BSDF", "Base Color")
		])
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert len(changes) == 1
		assert changes[0].old_value is None
		assert "Tex" in changes[0].new_value

	def test_link_removed(self):
		mat_a = make_material(links=[
			make_link("Tex", "Color", "Principled BSDF", "Base Color")
		])
		mat_b = make_material(links=[])
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert len(changes) == 1
		assert changes[0].new_value is None

	def test_link_rewired(self):
		mat_a = make_material(links=[
			make_link("Tex", "Color", "Principled BSDF", "Base Color")
		])
		mat_b = make_material(links=[
			make_link("Tex", "Color", "Principled BSDF", "Emission Color")
		])
		changes = compare_materials(mat_a, mat_b, "Mat")
		# Old link removed + new link added = 2 changes
		assert len(changes) == 2

	def test_identical_links_no_change(self):
		links = [make_link("Tex", "Color", "Principled BSDF", "Base Color")]
		mat_a = make_material(links=links)
		mat_b = make_material(links=links)
		assert compare_materials(mat_a, mat_b, "Mat") == []

	def test_link_order_irrelevant(self):
		link1 = make_link("A", "Out", "B", "In")
		link2 = make_link("C", "Out", "D", "In")
		mat_a = make_material(links=[link1, link2])
		mat_b = make_material(links=[link2, link1])   # reversed order
		assert compare_materials(mat_a, mat_b, "Mat") == []


# ---------------------------------------------------------------------------
# property_path format
# ---------------------------------------------------------------------------

class TestPropertyPathFormat:
	def test_path_contains_material_name(self):
		mat_a = make_material(nodes={})
		mat_b = make_material(nodes={"Emission": make_node("Emission", "EMISSION")})
		changes = compare_materials(mat_a, mat_b, "MyMaterial")
		assert all("MyMaterial" in c.property_path for c in changes)

	def test_node_input_path_format(self):
		node_a = make_node(inputs={"Roughness": make_input("Roughness", "VALUE", 0.2)})
		node_b = make_node(inputs={"Roughness": make_input("Roughness", "VALUE", 0.9)})
		mat_a = make_material(nodes={"Principled BSDF": node_a})
		mat_b = make_material(nodes={"Principled BSDF": node_b})
		changes = compare_materials(mat_a, mat_b, "Mat")
		assert "inputs.Roughness" in changes[0].property_path


# ---------------------------------------------------------------------------
# _values_equal helper
# ---------------------------------------------------------------------------

class TestValuesEqual:
	def test_equal_floats(self):
		assert _values_equal(0.5, 0.5, 1e-4) is True

	def test_close_floats_within_epsilon(self):
		assert _values_equal(0.5, 0.5 + 1e-5, 1e-4) is True

	def test_floats_outside_epsilon(self):
		assert _values_equal(0.5, 0.6, 1e-4) is False

	def test_equal_lists(self):
		assert _values_equal([1.0, 0.0, 0.0], [1.0, 0.0, 0.0], 1e-4) is True

	def test_different_lists(self):
		assert _values_equal([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], 1e-4) is False

	def test_different_length_lists(self):
		assert _values_equal([1.0, 0.0], [1.0, 0.0, 0.0], 1e-4) is False

	def test_none_none(self):
		assert _values_equal(None, None, 1e-4) is True

	def test_none_vs_value(self):
		assert _values_equal(None, 0.5, 1e-4) is False

	def test_equal_ints(self):
		assert _values_equal(1, 1, 1e-4) is True

	def test_equal_bools(self):
		assert _values_equal(True, True, 1e-4) is True

	def test_different_bools(self):
		assert _values_equal(True, False, 1e-4) is False


# ---------------------------------------------------------------------------
# MaterialSnapshot dataclass roundtrip
# ---------------------------------------------------------------------------

class TestMaterialSnapshotRoundtrip:
	def test_roundtrip_empty(self):
		snap = MaterialSnapshot(name="Mat", use_nodes=True)
		d = snap.to_dict()
		restored = MaterialSnapshot.from_dict(d)
		assert restored.name == "Mat"
		assert restored.use_nodes is True
		assert restored.nodes == {}
		assert restored.links == []

	def test_roundtrip_with_node(self):
		inp = NodeInputSnapshot(name="Roughness", type="VALUE", value=0.5)
		node = NodeSnapshot(
			name="Principled BSDF",
			type="BSDF_PRINCIPLED",
			location=[0.0, 300.0],
			inputs={"Roughness": inp},
		)
		snap = MaterialSnapshot(
			name="Mat",
			use_nodes=True,
			nodes={"Principled BSDF": node},
		)
		d = snap.to_dict()
		restored = MaterialSnapshot.from_dict(d)
		assert "Principled BSDF" in restored.nodes
		assert restored.nodes["Principled BSDF"].type == "BSDF_PRINCIPLED"
		assert restored.nodes["Principled BSDF"].inputs["Roughness"].value == 0.5

	def test_roundtrip_with_link(self):
		link = LinkSnapshot("Tex", "Color", "BSDF", "Base Color")
		snap = MaterialSnapshot(name="Mat", use_nodes=True, links=[link])
		d = snap.to_dict()
		restored = MaterialSnapshot.from_dict(d)
		assert len(restored.links) == 1
		assert restored.links[0].from_node == "Tex"
		assert restored.links[0].to_socket == "Base Color"
