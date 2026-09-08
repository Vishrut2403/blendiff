"""
tests/fake_bpy.py
~~~~~~~~~~~~~~~~~~
A minimal stand-in for the parts of ``bpy`` the merge applier touches.

The applier is the only module that writes to a live Blender scene, and it was
previously untested because testing it appeared to require Blender. It does
not: the applier only needs objects with settable attributes, a couple of
collections, and ``bpy.data`` lookups. Faking that surface makes every apply
path — including the failure paths — testable in plain pytest, which is where
the bugs were hiding.

This is deliberately *not* a Blender emulator. It models only what the applier
uses, and raises the way Blender does where that behaviour matters.
"""

from __future__ import annotations

import sys
import types
from typing import Any, Optional


class FakeMatrix:
	"""Stand-in for mathutils.Matrix, only needing copy()."""

	def __init__(self, tag: str = "identity"):
		self.tag = tag

	def copy(self) -> "FakeMatrix":
		return FakeMatrix(self.tag)

	def __eq__(self, other) -> bool:
		return isinstance(other, FakeMatrix) and other.tag == self.tag


class FakeStruct:
	"""Generic settable struct, used for camera DOF and similar sub-structs."""

	def __init__(self, **kwargs):
		self.__dict__.update(kwargs)


class FakeData:
	"""A camera or light datablock."""

	def __init__(self, **kwargs):
		self.__dict__.update(kwargs)


class FakeObject:
	def __init__(
		self,
		name: str,
		obj_type: str = "MESH",
		data: Any = None,
		parent: Optional["FakeObject"] = None,
	):
		self._name = name
		self.type = obj_type
		self.data = data
		self.location = (0.0, 0.0, 0.0)
		self.rotation_euler = (0.0, 0.0, 0.0)
		self.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
		self.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
		self.rotation_mode = "XYZ"
		self.scale = (1.0, 1.0, 1.0)
		self.hide_viewport = False
		self.hide_render = False
		self.parent = parent
		self.parent_type = "OBJECT"
		self.parent_bone = ""
		self.matrix_world = FakeMatrix(name)
		self.material_slots: list[FakeSlot] = []
		self.library = None
		self.override_library = None
		self._props: dict[str, Any] = {}
		self._collections: list[FakeCollection] = []

	# Blender renames through the `name` property and keeps bpy.data in sync.
	@property
	def name(self) -> str:
		return self._name

	@name.setter
	def name(self, value: str) -> None:
		_DATA.objects._rename(self._name, value)
		self._name = value

	@property
	def users_collection(self):
		return tuple(self._collections)

	# Custom property protocol
	def __getitem__(self, key):
		return self._props[key]

	def __setitem__(self, key, value):
		self._props[key] = value

	def __delitem__(self, key):
		del self._props[key]

	def __contains__(self, key):
		return key in self._props

	def get(self, key, default=None):
		return self._props.get(key, default)

	def keys(self):
		return list(self._props.keys())

	def visible_get(self) -> bool:
		return not self.hide_viewport

	def __repr__(self) -> str:
		return f"<FakeObject {self._name!r}>"


class FakeSlot:
	def __init__(self, material=None):
		self.material = material


class FakeMaterial:
	def __init__(self, name: str):
		self.name = name


class FakeCollectionObjects:
	def __init__(self, collection: "FakeCollection"):
		self._collection = collection
		self._items: list[FakeObject] = []

	def link(self, obj: FakeObject) -> None:
		if obj not in self._items:
			self._items.append(obj)
		if self._collection not in obj._collections:
			obj._collections.append(self._collection)

	def unlink(self, obj: FakeObject) -> None:
		if obj in self._items:
			self._items.remove(obj)
		if self._collection in obj._collections:
			obj._collections.remove(self._collection)

	def __iter__(self):
		return iter(self._items)

	def __len__(self):
		return len(self._items)


class FakeCollection:
	def __init__(self, name: str):
		self.name = name
		self.objects = FakeCollectionObjects(self)
		self.children: list[FakeCollection] = []


class FakeIDMap:
	"""Mimics bpy.data.objects / .materials / .collections."""

	def __init__(self):
		self._items: dict[str, Any] = {}

	def get(self, name, default=None):
		return self._items.get(name, default)

	def add(self, item):
		self._items[item.name] = item
		return item

	def remove(self, item, do_unlink: bool = False):
		for collection in list(getattr(item, "_collections", [])):
			collection.objects.unlink(item)
		self._items.pop(item.name, None)

	def _rename(self, old: str, new: str) -> None:
		if old in self._items:
			self._items[new] = self._items.pop(old)

	def __contains__(self, name):
		return name in self._items

	def __iter__(self):
		return iter(self._items.values())

	def __len__(self):
		return len(self._items)


class FakeScene:
	def __init__(self, name="Scene"):
		self.name = name
		self.collection = FakeCollection("Scene Collection")
		self.objects: list[FakeObject] = []


class FakeBpyData:
	def __init__(self):
		self.objects = FakeIDMap()
		self.materials = FakeIDMap()
		self.collections = FakeIDMap()
		self.filepath = ""


class FakeContext:
	def __init__(self, scene: FakeScene):
		self.scene = scene


_DATA = FakeBpyData()


def install(scene: Optional[FakeScene] = None) -> types.ModuleType:
	"""
	Install a fake ``bpy`` module and return it.

	Resets all state, so each test starts from an empty scene.
	"""
	global _DATA
	_DATA = FakeBpyData()

	scene = scene or FakeScene()
	module = types.ModuleType("bpy")
	module.data = _DATA
	module.context = FakeContext(scene)
	module.app = types.SimpleNamespace(version_string="4.1.0", version=(4, 1, 0))

	sys.modules["bpy"] = module
	return module


def uninstall() -> None:
	sys.modules.pop("bpy", None)
