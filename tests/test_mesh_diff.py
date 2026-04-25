import pytest
from blendiff.diff_engine.mesh_diff import diff_mesh_data
from blendiff.data_model.diff import PropertyChange


# Fixtures 

def _base_mesh() -> dict:
    return {
        "vertex_count":  8,
        "edge_count":    12,
        "face_count":    6,
        "loop_count":    24,
        "bbox_min":      [-1.0, -1.0, -1.0],
        "bbox_max":      [1.0, 1.0, 1.0],
        "uv_layers":     ["UVMap"],
        "shape_keys":    [],
        "vertex_groups": [],
    }


def _sphere_mesh() -> dict:
    return {
        "vertex_count":  482,
        "edge_count":    960,
        "face_count":    480,
        "loop_count":    1920,
        "bbox_min":      [-1.0, -1.0, -1.0],
        "bbox_max":      [1.0, 1.0, 1.0],
        "uv_layers":     ["UVMap"],
        "shape_keys":    [],
        "vertex_groups": [],
    }


# No changes 

class TestNoChanges:
    def test_identical_returns_empty(self):
        assert diff_mesh_data(_base_mesh(), _base_mesh()) == []

    def test_sphere_identical(self):
        assert diff_mesh_data(_sphere_mesh(), _sphere_mesh()) == []

    def test_bbox_epsilon_no_false_positive(self):
        a = _base_mesh()
        b = _base_mesh()
        b["bbox_max"] = [1.0 + 1e-6, 1.0, 1.0]
        assert diff_mesh_data(a, b) == []

    def test_returns_list(self):
        result = diff_mesh_data(_base_mesh(), _base_mesh())
        assert isinstance(result, list)


# Topology counts 

class TestTopologyCounts:
    def test_vertex_count_change(self):
        a = _base_mesh()
        b = _base_mesh()
        b["vertex_count"] = 16
        changes = diff_mesh_data(a, b)
        paths = [c.property_path for c in changes]
        assert "mesh.vertex_count" in paths

    def test_vertex_count_old_new(self):
        a = _base_mesh()
        b = _base_mesh()
        b["vertex_count"] = 482
        c = next(x for x in diff_mesh_data(a, b) if x.property_path == "mesh.vertex_count")
        assert c.old_value == 8
        assert c.new_value == 482

    def test_edge_count_change(self):
        a = _base_mesh()
        b = _base_mesh()
        b["edge_count"] = 24
        assert "mesh.edge_count" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_face_count_change(self):
        a = _base_mesh()
        b = _base_mesh()
        b["face_count"] = 12
        assert "mesh.face_count" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_loop_count_change(self):
        a = _base_mesh()
        b = _base_mesh()
        b["loop_count"] = 48
        assert "mesh.loop_count" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_multiple_count_changes(self):
        a = _base_mesh()
        b = _sphere_mesh()
        changes = diff_mesh_data(a, b)
        paths = [c.property_path for c in changes]
        assert "mesh.vertex_count" in paths
        assert "mesh.edge_count" in paths
        assert "mesh.face_count" in paths
        assert "mesh.loop_count" in paths


# Bounding box 

class TestBoundingBox:
    def test_bbox_min_change(self):
        a = _base_mesh()
        b = _base_mesh()
        b["bbox_min"] = [-2.0, -2.0, -2.0]
        assert "mesh.bbox_min" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_bbox_max_change(self):
        a = _base_mesh()
        b = _base_mesh()
        b["bbox_max"] = [2.0, 2.0, 2.0]
        assert "mesh.bbox_max" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_bbox_partial_change(self):
        a = _base_mesh()
        b = _base_mesh()
        b["bbox_max"] = [1.0, 1.0, 3.0]  # only Z changed
        assert "mesh.bbox_max" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_bbox_old_new_values(self):
        a = _base_mesh()
        b = _base_mesh()
        b["bbox_max"] = [2.0, 2.0, 2.0]
        c = next(x for x in diff_mesh_data(a, b) if x.property_path == "mesh.bbox_max")
        assert c.old_value == [1.0, 1.0, 1.0]
        assert c.new_value == [2.0, 2.0, 2.0]

    def test_bbox_epsilon_above_threshold(self):
        a = _base_mesh()
        b = _base_mesh()
        b["bbox_max"] = [1.001, 1.0, 1.0]  # above epsilon
        assert "mesh.bbox_max" in [c.property_path for c in diff_mesh_data(a, b)]


# UV layers 

class TestUVLayers:
    def test_uv_layer_added(self):
        a = _base_mesh()
        b = _base_mesh()
        b["uv_layers"] = ["UVMap", "LightMap"]
        assert "mesh.uv_layers" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_uv_layer_removed(self):
        a = _base_mesh()
        b = _base_mesh()
        b["uv_layers"] = []
        assert "mesh.uv_layers" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_uv_layer_renamed(self):
        a = _base_mesh()
        b = _base_mesh()
        b["uv_layers"] = ["DiffuseUV"]
        assert "mesh.uv_layers" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_uv_layer_order_change_no_diff(self):
        """Reordering UV layers is not a meaningful change."""
        a = _base_mesh()
        b = _base_mesh()
        a["uv_layers"] = ["UVMap", "LightMap"]
        b["uv_layers"] = ["LightMap", "UVMap"]
        assert diff_mesh_data(a, b) == []

    def test_uv_old_new_values(self):
        a = _base_mesh()
        b = _base_mesh()
        b["uv_layers"] = ["UVMap", "LightMap"]
        c = next(x for x in diff_mesh_data(a, b) if x.property_path == "mesh.uv_layers")
        assert c.old_value == ["UVMap"]
        assert c.new_value == ["LightMap", "UVMap"]  # sorted


# Shape keys 

class TestShapeKeys:
    def test_shape_key_added(self):
        a = _base_mesh()
        b = _base_mesh()
        b["shape_keys"] = ["Basis", "Smile"]
        assert "mesh.shape_keys" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_shape_key_removed(self):
        a = _base_mesh()
        b = _base_mesh()
        a["shape_keys"] = ["Basis", "Smile"]
        b["shape_keys"] = ["Basis"]
        assert "mesh.shape_keys" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_shape_keys_identical(self):
        a = _base_mesh()
        b = _base_mesh()
        a["shape_keys"] = ["Basis", "Smile", "Frown"]
        b["shape_keys"] = ["Basis", "Smile", "Frown"]
        assert diff_mesh_data(a, b) == []

    def test_shape_key_order_no_diff(self):
        a = _base_mesh()
        b = _base_mesh()
        a["shape_keys"] = ["Basis", "Smile"]
        b["shape_keys"] = ["Smile", "Basis"]
        assert diff_mesh_data(a, b) == []


# Vertex groups 

class TestVertexGroups:
    def test_vertex_group_added(self):
        a = _base_mesh()
        b = _base_mesh()
        b["vertex_groups"] = ["Arm.L", "Arm.R"]
        assert "mesh.vertex_groups" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_vertex_group_removed(self):
        a = _base_mesh()
        b = _base_mesh()
        a["vertex_groups"] = ["Arm.L"]
        b["vertex_groups"] = []
        assert "mesh.vertex_groups" in [c.property_path for c in diff_mesh_data(a, b)]

    def test_vertex_groups_identical(self):
        a = _base_mesh()
        b = _base_mesh()
        a["vertex_groups"] = ["Arm.L", "Arm.R", "Spine"]
        b["vertex_groups"] = ["Arm.L", "Arm.R", "Spine"]
        assert diff_mesh_data(a, b) == []

    def test_vertex_group_order_no_diff(self):
        a = _base_mesh()
        b = _base_mesh()
        a["vertex_groups"] = ["Arm.L", "Arm.R"]
        b["vertex_groups"] = ["Arm.R", "Arm.L"]
        assert diff_mesh_data(a, b) == []


# None handling 

class TestNoneHandling:
    def test_both_none_returns_empty(self):
        assert diff_mesh_data(None, None) == []

    def test_a_none_returns_change(self):
        changes = diff_mesh_data(None, _base_mesh())
        assert len(changes) == 1
        assert changes[0].old_value is None
        assert changes[0].property_path == "mesh"

    def test_b_none_returns_change(self):
        changes = diff_mesh_data(_base_mesh(), None)
        assert len(changes) == 1
        assert changes[0].new_value is None

    def test_returns_property_change_instances(self):
        a = _base_mesh()
        b = _base_mesh()
        b["vertex_count"] = 100
        for c in diff_mesh_data(a, b):
            assert isinstance(c, PropertyChange)


# Custom prefix 

class TestPrefix:
    def test_custom_prefix_in_path(self):
        a = _base_mesh()
        b = _base_mesh()
        b["vertex_count"] = 100
        changes = diff_mesh_data(a, b, prefix="objects.Cube.mesh")
        assert changes[0].property_path == "objects.Cube.mesh.vertex_count"


# Edge cases 

class TestEdgeCases:
    def test_exact_change_count(self):
        a = _base_mesh()
        b = _base_mesh()
        b["vertex_count"] = 100
        b["face_count"] = 50
        assert len(diff_mesh_data(a, b)) == 2

    def test_extra_key_in_b(self):
        a = _base_mesh()
        b = _base_mesh()
        b["custom_prop"] = "new"
        changes = diff_mesh_data(a, b)
        assert "mesh.custom_prop" in [c.property_path for c in changes]

    def test_empty_dicts(self):
        assert diff_mesh_data({}, {}) == []

    def test_all_changes_captured(self):
        a = _base_mesh()
        b = _sphere_mesh()
        b["bbox_max"] = [2.0, 2.0, 2.0]
        b["uv_layers"] = ["UVMap", "LightMap"]
        b["shape_keys"] = ["Basis", "Smile"]
        changes = diff_mesh_data(a, b)
        paths = [c.property_path for c in changes]
        assert "mesh.vertex_count" in paths
        assert "mesh.bbox_max" in paths
        assert "mesh.uv_layers" in paths
        assert "mesh.shape_keys" in paths