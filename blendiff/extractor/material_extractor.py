"""
blendiff.extractor.material_extractor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Reads a bpy material's node tree and returns a plain dict matching
the MaterialSnapshot schema.

Design decisions
----------------
* Only bpy-touching module for materials — everything downstream is pure Python.
* Catches exceptions per-node and per-socket so one bad node never
  crashes the whole extraction.
* Float values are rounded to 6 decimal places here to avoid noise.
* Image texture nodes store image.name, not image data.
* Socket types that can't be serialised (e.g. SHADER sockets whose
  default_value is None) are stored as None — the diff engine handles this.
"""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger(__name__)

# Socket value types that need special normalisation
_VECTOR_TYPES = {"VECTOR", "RGBA", "RGB"}
_FLOAT_PRECISION = 6

# Socket types where default_value is meaningless (e.g. shader sockets)
_SKIP_VALUE_TYPES = {"SHADER", "GEOMETRY"}


class MaterialExtractor:
	"""Extract a material node tree into a plain JSON-safe dict."""

	@classmethod
	def extract(cls, material: Any) -> dict:
		"""
		Extract a single bpy.types.Material.

		Parameters
		----------
		material:
			A bpy.types.Material instance.

		Returns
		-------
		dict matching MaterialSnapshot schema.
		"""
		if material is None:
			return {
				"name": None,
				"use_nodes": False,
				"nodes": {},
				"links": [],
			}

		if not material.use_nodes or material.node_tree is None:
			return {
				"name": material.name,
				"use_nodes": False,
				"nodes": {},
				"links": [],
			}

		node_tree = material.node_tree

		nodes = {}
		for node in node_tree.nodes:
			try:
				nodes[node.name] = cls._extract_node(node)
			except Exception as exc:
				log.warning("Failed to extract node %r in material %r: %s",
							node.name, material.name, exc)

		links = []
		for link in node_tree.links:
			try:
				links.append(cls._extract_link(link))
			except Exception as exc:
				log.warning("Failed to extract link in material %r: %s",
							material.name, exc)

		return {
			"name": material.name,
			"use_nodes": True,
			"nodes": nodes,
			"links": links,
		}

	@classmethod
	def _extract_node(cls, node: Any) -> dict:
		"""Extract a single bpy.types.Node."""
		inputs = {}
		for socket in node.inputs:
			try:
				inp = cls._extract_socket(socket)
				if inp is not None:
					inputs[socket.name] = inp
			except Exception as exc:
				log.warning("Failed to extract socket %r: %s", socket.name, exc)

		# Image texture special case
		image_name = None
		if node.type == "TEX_IMAGE" and hasattr(node, "image") and node.image:
			image_name = node.image.name

		return {
			"name": node.name,
			"type": node.type,
			"location": [round(node.location.x, _FLOAT_PRECISION),
						 round(node.location.y, _FLOAT_PRECISION)],
			"inputs": inputs,
			"image_name": image_name,
		}

	@classmethod
	def _extract_socket(cls, socket: Any) -> dict | None:
		"""
		Extract one input socket.
		Returns None for socket types where default_value is meaningless.
		"""
		socket_type = socket.type  # 'VALUE', 'RGBA', 'VECTOR', 'SHADER', etc.

		if socket_type in _SKIP_VALUE_TYPES:
			return None

		value = cls._normalise_socket_value(socket)

		return {
			"name": socket.name,
			"type": socket_type,
			"value": value,
		}

	@classmethod
	def _normalise_socket_value(cls, socket: Any) -> Any:
		"""Convert socket default_value to a JSON-safe type."""
		try:
			val = socket.default_value
		except AttributeError:
			return None

		socket_type = socket.type

		if socket_type == "VALUE":
			v = float(val)
			return None if (math.isnan(v) or math.isinf(v)) else round(v, _FLOAT_PRECISION)

		if socket_type in _VECTOR_TYPES:
			try:
				result = []
				for component in val:
					c = float(component)
					result.append(None if (math.isnan(c) or math.isinf(c))
								  else round(c, _FLOAT_PRECISION))
				return result
			except TypeError:
				return None

		if socket_type == "INT":
			return int(val)

		if socket_type == "BOOLEAN":
			return bool(val)

		if socket_type == "STRING":
			return str(val)

		# Fallback — try to convert, give up gracefully
		try:
			return str(val)
		except Exception:
			return None

	@classmethod
	def _extract_link(cls, link: Any) -> dict:
		"""Extract a single bpy.types.NodeLink."""
		return {
			"from_node": link.from_node.name,
			"from_socket": link.from_socket.name,
			"to_node": link.to_node.name,
			"to_socket": link.to_socket.name,
		}
