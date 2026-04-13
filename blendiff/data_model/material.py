"""
blendiff.data_model.material
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Dataclasses for material node graph snapshots.

Rules:
  - No bpy imports.  Must be importable outside Blender.
  - All fields are JSON-serialisable primitives or nested dataclasses.
  - Node inputs store only default_value, not the full socket object.
  - Links are compared as sets — order is irrelevant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class NodeInputSnapshot:
	"""
	One input socket on a node.

	Only the default_value is stored — the connected/unconnected state
	is captured via LinkSnapshot instead.
	"""
	name: str
	type: str           # 'VALUE', 'RGBA', 'VECTOR', 'SHADER', etc.
	value: Any          # default_value, already normalised to JSON-safe types


@dataclass
class NodeSnapshot:
	"""
	One node in a material node tree.

	Keyed by node.name inside MaterialSnapshot.nodes.
	"""
	name: str
	type: str           # 'BSDF_PRINCIPLED', 'TEX_IMAGE', 'EMISSION', etc.
	location: list[float]           # [x, y] — node editor position
	inputs: dict[str, NodeInputSnapshot] = field(default_factory=dict)
	# Image texture nodes: store image name, not image data
	image_name: Optional[str] = None

	def to_dict(self) -> dict:
		return {
			"name": self.name,
			"type": self.type,
			"location": self.location,
			"inputs": {
				k: {"name": v.name, "type": v.type, "value": v.value}
				for k, v in self.inputs.items()
			},
			"image_name": self.image_name,
		}

	@staticmethod
	def from_dict(d: dict) -> "NodeSnapshot":
		inputs = {
			k: NodeInputSnapshot(
				name=v["name"],
				type=v["type"],
				value=v["value"],
			)
			for k, v in d.get("inputs", {}).items()
		}
		return NodeSnapshot(
			name=d["name"],
			type=d["type"],
			location=d.get("location", [0.0, 0.0]),
			inputs=inputs,
			image_name=d.get("image_name"),
		)


@dataclass
class LinkSnapshot:
	"""
	One node link (connection between two sockets).

	Stored as a tuple-like object so links can be compared as sets.
	"""
	from_node: str
	from_socket: str
	to_node: str
	to_socket: str

	def to_tuple(self) -> tuple:
		return (self.from_node, self.from_socket, self.to_node, self.to_socket)

	def to_dict(self) -> dict:
		return {
			"from_node": self.from_node,
			"from_socket": self.from_socket,
			"to_node": self.to_node,
			"to_socket": self.to_socket,
		}

	@staticmethod
	def from_dict(d: dict) -> "LinkSnapshot":
		return LinkSnapshot(
			from_node=d["from_node"],
			from_socket=d["from_socket"],
			to_node=d["to_node"],
			to_socket=d["to_socket"],
		)


@dataclass
class MaterialSnapshot:
	"""
	Complete snapshot of one Blender material's node tree.

	Stored per material name inside a SceneObject's material_slots.
	"""
	name: str
	use_nodes: bool
	nodes: dict[str, NodeSnapshot] = field(default_factory=dict)   # keyed by node.name
	links: list[LinkSnapshot] = field(default_factory=list)

	def to_dict(self) -> dict:
		return {
			"name": self.name,
			"use_nodes": self.use_nodes,
			"nodes": {k: v.to_dict() for k, v in self.nodes.items()},
			"links": [lnk.to_dict() for lnk in self.links],
		}

	@staticmethod
	def from_dict(d: dict) -> "MaterialSnapshot":
		nodes = {k: NodeSnapshot.from_dict(v) for k, v in d.get("nodes", {}).items()}
		links = [LinkSnapshot.from_dict(lnk) for lnk in d.get("links", [])]
		return MaterialSnapshot(
			name=d["name"],
			use_nodes=d.get("use_nodes", False),
			nodes=nodes,
			links=links,
		)
