"""
scripts/example_output.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Demonstrates the full BlenDiff pipeline (extractor → serializer → diff)
using hand-crafted scene dicts that simulate what bpy would produce.

Run with:
	python scripts/example_output.py

No Blender installation required.
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.serializer import SceneSerializer
from blendiff.diff_engine import DiffEngine


# Simulated "raw" scene output (as if SceneExtractor had run inside Blender)
# We use plain lists instead of mathutils.Vector so this runs anywhere.

RAW_SCENE_A = {
	"blender_version": "4.1.0",
	"scene_name": "SceneA",
	"objects": {
		"Cube": {
			"name": "Cube",
			"type": "MESH",
			"collection_path": "Props",
			"transform": {
				"location":       [0.0, 0.0, 0.0],
				"rotation_euler": [0.0, 0.0, 0.0],
				"scale":          [1.0, 1.0, 1.0],
			},
			"material_slots": [
				{"index": 0, "name": "Wood", "use_nodes": True}
			],
			"visible": True,
		},
		"Suzanne": {
			"name": "Suzanne",
			"type": "MESH",
			"collection_path": "Props",
			"transform": {
				"location":       [3.0, 0.0, 0.0],
				"rotation_euler": [0.0, 0.0, 0.0],
				"scale":          [1.0, 1.0, 1.0],
			},
			"material_slots": [
				{"index": 0, "name": "Skin", "use_nodes": True}
			],
			"visible": True,
		},
		"Sun": {
			"name": "Sun",
			"type": "LIGHT",
			"collection_path": "Lighting",
			"transform": {
				"location":       [0.0, 0.0, 5.0],
				"rotation_euler": [0.0, 0.0, 0.0],
				"scale":          [1.0, 1.0, 1.0],
			},
			"material_slots": [],
			"visible": True,
		},
	},
	"collections": {
		"Scene Collection": {
			"name": "Scene Collection",
			"path": "Scene Collection",
			"children": ["Props", "Lighting"],
			"objects": [],
		},
		"Scene Collection/Props": {
			"name": "Props",
			"path": "Scene Collection/Props",
			"children": [],
			"objects": ["Cube", "Suzanne"],
		},
		"Scene Collection/Lighting": {
			"name": "Lighting",
			"path": "Scene Collection/Lighting",
			"children": [],
			"objects": ["Sun"],
		},
	},
}

# Scene B: Cube moved + material changed, Suzanne hidden,
# Camera added, Sun removed, new collection "FX"
RAW_SCENE_B = {
	"blender_version": "4.1.0",
	"scene_name": "SceneB",
	"objects": {
		"Cube": {
			"name": "Cube",
			"type": "MESH",
			"collection_path": "Props",
			"transform": {
				"location":       [2.5, 0.0, 1.0],   # MOVED
				"rotation_euler": [0.0, 0.785398, 0.0],  # ROTATED 45°
				"scale":          [1.0, 1.0, 1.0],
			},
			"material_slots": [
				{"index": 0, "name": "Metal", "use_nodes": True}  # MATERIAL CHANGED
			],
			"visible": True,
		},
		"Suzanne": {
			"name": "Suzanne",
			"type": "MESH",
			"collection_path": "Props",
			"transform": {
				"location":       [3.0, 0.0, 0.0],
				"rotation_euler": [0.0, 0.0, 0.0],
				"scale":          [1.0, 1.0, 1.0],
			},
			"material_slots": [
				{"index": 0, "name": "Skin", "use_nodes": True}
			],
			"visible": False,   # HIDDEN
		},
		"Camera": {            # ADDED
			"name": "Camera",
			"type": "CAMERA",
			"collection_path": "Scene Collection",
			"transform": {
				"location":       [7.36, -6.93, 4.96],
				"rotation_euler": [1.109, 0.0, 0.814],
				"scale":          [1.0, 1.0, 1.0],
			},
			"material_slots": [],
			"visible": True,
		},
		# Sun: REMOVED
	},
	"collections": {
		"Scene Collection": {
			"name": "Scene Collection",
			"path": "Scene Collection",
			"children": ["Props", "Lighting", "FX"],   # FX added
			"objects": ["Camera"],
		},
		"Scene Collection/Props": {
			"name": "Props",
			"path": "Scene Collection/Props",
			"children": [],
			"objects": ["Cube", "Suzanne"],
		},
		"Scene Collection/Lighting": {
			"name": "Lighting",
			"path": "Scene Collection/Lighting",
			"children": [],
			"objects": [],   # Sun removed from here
		},
		"Scene Collection/FX": {   # NEW COLLECTION
			"name": "FX",
			"path": "Scene Collection/FX",
			"children": [],
			"objects": [],
		},
	},
}


# Pipeline

def main():
	serializer = SceneSerializer()
	engine     = DiffEngine()

	print("=" * 60)
	print("BlenDiff — Example Output")
	print("=" * 60)

	# Serialise both scenes
	scene_a = serializer.serialize(RAW_SCENE_A)
	scene_b = serializer.serialize(RAW_SCENE_B)

	print("\n── Serialized Scene A (objects only) ──")
	print(json.dumps(scene_a["objects"], indent=2))

	# Run diff
	diff = engine.compare(scene_a, scene_b)

	print("\n── Diff Summary ──")
	print(json.dumps(diff.summary(), indent=2))

	print("\n── Added Objects ──")
	for d in diff.added_objects:
		print(f"  [+] {d.name}")

	print("\n── Removed Objects ──")
	for d in diff.removed_objects:
		print(f"  [-] {d.name}")

	print("\n── Modified Objects ──")
	for d in diff.modified_objects:
		print(f"  [~] {d.name}")
		for c in d.changes:
			print(f"       {c.property_path}")
			print(f"         before: {c.old_value}")
			print(f"         after:  {c.new_value}")

	print("\n── Collection Diffs ──")
	for d in diff.collection_diffs:
		print(f"  [{d.kind.value[0]}] {d.path}")
		for c in d.changes:
			print(f"       {c.property_path}: {c.old_value} → {c.new_value}")

	print("\n── Full Diff as JSON ──")
	diff_json = {
		"summary": diff.summary(),
		"object_diffs": [
			{
				"name": d.name,
				"kind": d.kind.value,
				"changes": [
					{"path": c.property_path, "from": c.old_value, "to": c.new_value}
					for c in d.changes
				],
			}
			for d in diff.object_diffs
		],
		"collection_diffs": [
			{
				"path": d.path,
				"kind": d.kind.value,
				"changes": [
					{"path": c.property_path, "from": c.old_value, "to": c.new_value}
					for c in d.changes
				],
			}
			for d in diff.collection_diffs
		],
	}
	print(json.dumps(diff_json, indent=2))


if __name__ == "__main__":
	main()