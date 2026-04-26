from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional



# Transform

@dataclass
class Transform:
	"""Object world-space transform, normalised to plain float lists."""
	location: list[float]
	rotation_euler: list[float]
	scale: list[float]       


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
	# Future: animations, node_groups, world

@dataclass
class RenderSettings:
	"""Flat snapshot of the scene render settings relevant for diffing."""

	# Core engine
	engine: str = ""                    # CYCLES, BLENDER_EEVEE, BLENDER_WORKBENCH

	# Resolution
	resolution_x: int = 1920
	resolution_y: int = 1080
	resolution_percentage: int = 100

	# Sampling
	# Cycles
	cycles_samples: int = 128
	cycles_preview_samples: int = 32
	cycles_use_denoising: bool = False
	cycles_denoiser: str = ""           # OPTIX, OPENIMAGEDENOISE
	cycles_device: str = "CPU"          # CPU / GPU

	# EEVEE
	eevee_taa_render_samples: int = 64
	eevee_use_bloom: bool = False
	eevee_use_ssr: bool = False         # screen-space reflections
	eevee_shadow_cube_size: str = "512"
	eevee_shadow_cascade_size: str = "1024"

	# Output
	filepath: str = ""
	file_format: str = "PNG"           # PNG, JPEG, OPEN_EXR
	color_mode: str = "RGBA"
	color_depth: str = "8"

	# Frame range
	frame_start: int = 1
	frame_end: int = 250
	frame_step: int = 1
	fps: int = 24
	fps_base: float = 1.0

	# Color management
	display_device: str = "sRGB"
	view_transform: str = "Filmic"
	look: str = "None"
	exposure: float = 0.0
	gamma: float = 1.0
