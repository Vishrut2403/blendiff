"""
blendiff.data_model.scene
~~~~~~~~~~~~~~~~~~~~~~~~~
Dataclasses that define the canonical shape of a serialised Blender scene.

Rules:
  - No bpy imports here.  This module must be importable outside Blender.
  - All field types must be JSON-serialisable primitives or other dataclasses.
  - Optional fields default to None; list fields default to [].

Adding a new tracked property:
  1. Add a field here.
  2. Teach the extractor to populate it.
  3. Teach the serializer to normalise it (if needed).
  4. Teach the diff engine to compare it.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# Transform

@dataclass
class Transform:
	"""Object world-space transform, normalised to plain float lists."""
	location: list[float]           # [x, y, z]
	rotation_euler: list[float]     # [x, y, z]  radians
	scale: list[float]              # [x, y, z]


# Material

@dataclass
class MaterialSlot:
	"""One material slot on an object."""
	index: int
	name: Optional[str]             # None when slot is empty
	use_nodes: Optional[bool]


# Object

@dataclass
class SceneObject:
	"""Lightweight representation of a bpy.types.Object."""
	name: str
	type: str                       # 'MESH', 'LIGHT', 'CAMERA', …
	collection_path: str            # e.g. "Scene Collection/Props"
	transform: Transform
	material_slots: list[MaterialSlot] = field(default_factory=list)
	visible: bool = True
	# Future fields (not yet extracted, present for schema completeness):
	# data_block_type: Optional[str] = None
	# modifiers: list[str] = field(default_factory=list)
	# shape_keys: list[str] = field(default_factory=list)


# Collection

@dataclass
class CollectionNode:
	"""One node in the collection hierarchy."""
	name: str
	path: str                       # full path, "/" separated
	children: list[str] = field(default_factory=list)   # child collection names
	objects: list[str] = field(default_factory=list)    # object names directly in this collection


# Full scene snapshot

@dataclass
class SerializedScene:
	"""
	Complete, JSON-safe snapshot of a Blender scene.
	Produced by Serializer.serialize().
	"""
	blender_version: str            # e.g. "4.1.0"
	scene_name: str
	objects: dict[str, dict]        # keyed by object name
	collections: dict[str, dict]    # keyed by collection path
	# Future: animations, node_groups, world, …
