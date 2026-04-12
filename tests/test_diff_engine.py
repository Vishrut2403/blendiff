"""
tests/test_diff_engine.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for DiffEngine.compare().  No bpy required.

All inputs are plain Python dicts — exactly what SceneSerializer produces.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.diff_engine import DiffEngine
from blendiff.data_model.diff import ChangeKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _obj(
    name="Cube",
    obj_type="MESH",
    collection_path="Scene Collection",
    location=None,
    rotation=None,
    scale=None,
    material_name="Material",
    visible=True,
):
    return {
        "name":            name,
        "type":            obj_type,
        "collection_path": collection_path,
        "transform": {
            "location":       location or [0.0, 0.0, 0.0],
            "rotation_euler": rotation or [0.0, 0.0, 0.0],
            "scale":          scale    or [1.0, 1.0, 1.0],
        },
        "material_slots": [
            {"index": 0, "name": material_name, "use_nodes": True}
        ] if material_name else [],
        "visible": visible,
    }


def _scene(objects: dict, collections: dict = None, name="Scene"):
    return {
        "blender_version": "4.1.0",
        "scene_name":      name,
        "objects":         objects,
        "collections":     collections or {},
    }


def _col(name, path, children=None, objects=None):
    return {
        "name":     name,
        "path":     path,
        "children": children or [],
        "objects":  objects or [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDiffEngineObjects:

    def setup_method(self):
        self.engine = DiffEngine()

    def test_identical_scenes_produce_no_diffs(self):
        o = _obj()
        a = _scene({"Cube": o})
        b = _scene({"Cube": o})
        diff = self.engine.compare(a, b)
        assert not diff.has_changes

    def test_added_object(self):
        a = _scene({})
        b = _scene({"Cube": _obj()})
        diff = self.engine.compare(a, b)
        assert len(diff.added_objects) == 1
        assert diff.added_objects[0].name == "Cube"
        assert diff.added_objects[0].kind == ChangeKind.ADDED

    def test_removed_object(self):
        a = _scene({"Cube": _obj()})
        b = _scene({})
        diff = self.engine.compare(a, b)
        assert len(diff.removed_objects) == 1
        assert diff.removed_objects[0].name == "Cube"

    def test_location_change_detected(self):
        a = _scene({"Cube": _obj(location=[0.0, 0.0, 0.0])})
        b = _scene({"Cube": _obj(location=[1.0, 2.0, 3.0])})
        diff = self.engine.compare(a, b)
        assert len(diff.modified_objects) == 1
        obj_diff = diff.modified_objects[0]
        prop_paths = [c.property_path for c in obj_diff.changes]
        assert "transform.location" in prop_paths

    def test_rotation_change_detected(self):
        a = _scene({"Cube": _obj(rotation=[0.0, 0.0, 0.0])})
        b = _scene({"Cube": _obj(rotation=[0.0, 1.5708, 0.0])})
        diff = self.engine.compare(a, b)
        obj_diff = diff.modified_objects[0]
        prop_paths = [c.property_path for c in obj_diff.changes]
        assert "transform.rotation_euler" in prop_paths

    def test_scale_change_detected(self):
        a = _scene({"Cube": _obj(scale=[1.0, 1.0, 1.0])})
        b = _scene({"Cube": _obj(scale=[2.0, 2.0, 2.0])})
        diff = self.engine.compare(a, b)
        obj_diff = diff.modified_objects[0]
        prop_paths = [c.property_path for c in obj_diff.changes]
        assert "transform.scale" in prop_paths

    def test_epsilon_ignores_float_noise(self):
        """Tiny sub-epsilon differences must not produce false positives."""
        eps = 1e-4
        engine = DiffEngine(epsilon=eps)
        a = _scene({"Cube": _obj(location=[0.0, 0.0, 0.0])})
        b = _scene({"Cube": _obj(location=[eps * 0.1, 0.0, 0.0])})
        diff = engine.compare(a, b)
        assert not diff.has_changes

    def test_above_epsilon_is_detected(self):
        eps = 1e-4
        engine = DiffEngine(epsilon=eps)
        a = _scene({"Cube": _obj(location=[0.0, 0.0, 0.0])})
        b = _scene({"Cube": _obj(location=[eps * 10, 0.0, 0.0])})
        diff = engine.compare(a, b)
        assert diff.has_changes

    def test_material_change_detected(self):
        a = _scene({"Cube": _obj(material_name="Wood")})
        b = _scene({"Cube": _obj(material_name="Metal")})
        diff = self.engine.compare(a, b)
        obj_diff = diff.modified_objects[0]
        prop_paths = [c.property_path for c in obj_diff.changes]
        assert "material_slots[0].name" in prop_paths

    def test_material_old_and_new_values(self):
        a = _scene({"Cube": _obj(material_name="Wood")})
        b = _scene({"Cube": _obj(material_name="Metal")})
        diff = self.engine.compare(a, b)
        change = next(
            c for c in diff.modified_objects[0].changes
            if c.property_path == "material_slots[0].name"
        )
        assert change.old_value == "Wood"
        assert change.new_value == "Metal"

    def test_visibility_change_detected(self):
        a = _scene({"Cube": _obj(visible=True)})
        b = _scene({"Cube": _obj(visible=False)})
        diff = self.engine.compare(a, b)
        obj_diff = diff.modified_objects[0]
        prop_paths = [c.property_path for c in obj_diff.changes]
        assert "visible" in prop_paths

    def test_type_change_detected(self):
        a = _scene({"Empty": _obj(obj_type="EMPTY")})
        b = _scene({"Empty": _obj(obj_type="MESH")})
        diff = self.engine.compare(a, b)
        obj_diff = diff.modified_objects[0]
        prop_paths = [c.property_path for c in obj_diff.changes]
        assert "type" in prop_paths

    def test_collection_path_change_detected(self):
        a = _scene({"Cube": _obj(collection_path="Props")})
        b = _scene({"Cube": _obj(collection_path="Background")})
        diff = self.engine.compare(a, b)
        obj_diff = diff.modified_objects[0]
        prop_paths = [c.property_path for c in obj_diff.changes]
        assert "collection_path" in prop_paths

    def test_multiple_added_removed(self):
        a = _scene({"A": _obj("A"), "B": _obj("B")})
        b = _scene({"B": _obj("B"), "C": _obj("C")})
        diff = self.engine.compare(a, b)
        added_names   = {d.name for d in diff.added_objects}
        removed_names = {d.name for d in diff.removed_objects}
        assert added_names   == {"C"}
        assert removed_names == {"A"}

    def test_summary_counts(self):
        a = _scene({"A": _obj("A"), "B": _obj("B")})
        b = _scene({
            "B": _obj("B", location=[1, 0, 0]),
            "C": _obj("C"),
        })
        diff = self.engine.compare(a, b)
        s = diff.summary()
        assert s["added"]    == 1   # C
        assert s["removed"]  == 1   # A
        assert s["modified"] == 1   # B (location changed)


class TestDiffEngineCollections:

    def setup_method(self):
        self.engine = DiffEngine()

    def test_added_collection(self):
        a = _scene({}, collections={})
        b = _scene({}, collections={
            "Props": _col("Props", "Props", objects=["Cube"])
        })
        diff = self.engine.compare(a, b)
        assert len(diff.collection_diffs) == 1
        assert diff.collection_diffs[0].kind == ChangeKind.ADDED

    def test_removed_collection(self):
        a = _scene({}, collections={
            "Props": _col("Props", "Props")
        })
        b = _scene({}, collections={})
        diff = self.engine.compare(a, b)
        assert diff.collection_diffs[0].kind == ChangeKind.REMOVED

    def test_object_moved_between_collections(self):
        a = _scene({}, collections={
            "Props": _col("Props", "Props", objects=["Cube"]),
            "BG":    _col("BG", "BG", objects=[]),
        })
        b = _scene({}, collections={
            "Props": _col("Props", "Props", objects=[]),
            "BG":    _col("BG", "BG", objects=["Cube"]),
        })
        diff = self.engine.compare(a, b)
        # Both collections modified
        modified_paths = {d.path for d in diff.collection_diffs}
        assert "Props" in modified_paths
        assert "BG"    in modified_paths

    def test_identical_collections_no_diff(self):
        col = _col("Props", "Props", objects=["Cube"])
        a = _scene({}, collections={"Props": col})
        b = _scene({}, collections={"Props": col})
        diff = self.engine.compare(a, b)
        assert not diff.collection_diffs