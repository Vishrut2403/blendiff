"""
tests/test_serializer.py
~~~~~~~~~~~~~~~~~~~~~~~~
Tests for SceneSerializer.  No bpy required.

We simulate mathutils-like objects with simple namedtuples/classes so
that the serializer's type-normalisation logic is thoroughly exercised.
"""

import sys
import os
import math

# Allow importing blendiff from the repo root without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.serializer import SceneSerializer


# ---------------------------------------------------------------------------
# Minimal mathutils stubs (real mathutils is only available inside Blender)
# ---------------------------------------------------------------------------

class _Vec3:
    """Stub for mathutils.Vector / Euler."""
    def __init__(self, x, y, z):
        self._data = (x, y, z)
    def __iter__(self):
        return iter(self._data)
    def __len__(self):
        return 3


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_raw_scene(
    location=(0.0, 0.0, 0.0),
    rotation=(0.0, 0.0, 0.0),
    scale=(1.0, 1.0, 1.0),
    material_name="Material",
):
    """Build a minimal raw scene dict as the extractor would produce it."""
    return {
        "blender_version": "4.1.0",
        "scene_name": "TestScene",
        "objects": {
            "Cube": {
                "name": "Cube",
                "type": "MESH",
                "collection_path": "Scene Collection",
                "transform": {
                    "location":       _Vec3(*location),
                    "rotation_euler": _Vec3(*rotation),
                    "scale":          _Vec3(*scale),
                },
                "material_slots": [
                    {"index": 0, "name": material_name, "use_nodes": True},
                ],
                "visible": True,
            }
        },
        "collections": {
            "Scene Collection": {
                "name":     "Scene Collection",
                "path":     "Scene Collection",
                "children": [],
                "objects":  ["Cube"],
            }
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSceneSerializer:

    def setup_method(self):
        self.s = SceneSerializer()

    def test_basic_structure(self):
        raw = _make_raw_scene()
        result = self.s.serialize(raw)
        assert result["blender_version"] == "4.1.0"
        assert result["scene_name"] == "TestScene"
        assert "Cube" in result["objects"]
        assert "Scene Collection" in result["collections"]

    def test_mathutils_vector_converted_to_list(self):
        raw = _make_raw_scene(location=(1.0, 2.0, 3.0))
        result = self.s.serialize(raw)
        loc = result["objects"]["Cube"]["transform"]["location"]
        assert isinstance(loc, list)
        assert loc == [1.0, 2.0, 3.0]

    def test_float_rounding(self):
        raw = _make_raw_scene(location=(1.123456789, 0.0, 0.0))
        result = self.s.serialize(raw)
        loc = result["objects"]["Cube"]["transform"]["location"]
        # Default precision is 6 decimal places
        assert loc[0] == round(1.123456789, 6)

    def test_nan_becomes_zero(self):
        raw = _make_raw_scene(location=(float("nan"), 0.0, 0.0))
        result = self.s.serialize(raw)
        loc = result["objects"]["Cube"]["transform"]["location"]
        assert loc[0] == 0.0

    def test_inf_becomes_zero(self):
        raw = _make_raw_scene(location=(float("inf"), 0.0, 0.0))
        result = self.s.serialize(raw)
        loc = result["objects"]["Cube"]["transform"]["location"]
        assert loc[0] == 0.0

    def test_material_slot_preserved(self):
        raw = _make_raw_scene(material_name="Gold")
        result = self.s.serialize(raw)
        slots = result["objects"]["Cube"]["material_slots"]
        assert len(slots) == 1
        assert slots[0]["name"] == "Gold"
        assert slots[0]["index"] == 0
        assert slots[0]["use_nodes"] is True

    def test_empty_material_slot(self):
        raw = _make_raw_scene()
        raw["objects"]["Cube"]["material_slots"] = [
            {"index": 0, "name": None, "use_nodes": None}
        ]
        result = self.s.serialize(raw)
        slot = result["objects"]["Cube"]["material_slots"][0]
        assert slot["name"] is None
        assert slot["use_nodes"] is None

    def test_collection_structure(self):
        raw = _make_raw_scene()
        result = self.s.serialize(raw)
        col = result["collections"]["Scene Collection"]
        assert col["name"] == "Scene Collection"
        assert col["objects"] == ["Cube"]
        assert col["children"] == []

    def test_custom_float_precision(self):
        s = SceneSerializer(float_precision=2)
        raw = _make_raw_scene(location=(1.999, 0.0, 0.0))
        result = s.serialize(raw)
        loc = result["objects"]["Cube"]["transform"]["location"]
        assert loc[0] == 2.0   # rounded to 2 decimal places

    def test_visible_flag(self):
        raw = _make_raw_scene()
        raw["objects"]["Cube"]["visible"] = False
        result = self.s.serialize(raw)
        assert result["objects"]["Cube"]["visible"] is False

    def test_multiple_objects(self):
        raw = _make_raw_scene()
        raw["objects"]["Sphere"] = {
            "name": "Sphere",
            "type": "MESH",
            "collection_path": "Scene Collection",
            "transform": {
                "location":       _Vec3(5, 0, 0),
                "rotation_euler": _Vec3(0, 0, 0),
                "scale":          _Vec3(1, 1, 1),
            },
            "material_slots": [],
            "visible": True,
        }
        result = self.s.serialize(raw)
        assert len(result["objects"]) == 2
        assert "Sphere" in result["objects"]