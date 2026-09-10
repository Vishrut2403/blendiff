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
		# Only armatures have a pose; None everywhere else, matching bpy.
		self.pose = None
		self.mode = "OBJECT"
		self._selected = False

	def select_get(self):
		return self._selected

	def select_set(self, value):
		self._selected = bool(value)

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


class FakePoseBone:
	"""A pose bone: settable transform channels, plus constraints."""

	def __init__(self, name):
		self.name = name
		self.location = (0.0, 0.0, 0.0)
		self.rotation_euler = (0.0, 0.0, 0.0)
		self.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
		self.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
		# Pose bones default to quaternion, unlike objects.
		self.rotation_mode = "QUATERNION"
		self.scale = (1.0, 1.0, 1.0)
		self.custom_shape = None
		self.constraints = []


class FakePoseBones:
	"""bpy exposes pose.bones as a mapping keyed by bone name."""

	def __init__(self, names=()):
		self._bones = {name: FakePoseBone(name) for name in names}

	def get(self, name, default=None):
		return self._bones.get(name, default)

	def __getitem__(self, name):
		return self._bones[name]

	def __contains__(self, name):
		return name in self._bones

	def __iter__(self):
		return iter(self._bones.values())

	def __len__(self):
		return len(self._bones)


class FakePose:
	def __init__(self, bone_names=()):
		self.bones = FakePoseBones(bone_names)


class FakeEditBone:
	"""
	A bone as seen in edit mode.

	parent, head, tail, roll and use_connect exist only here — that is the
	whole reason rest-bone merging needs an edit-mode session.
	"""

	def __init__(self, name, head=(0.0, 0.0, 0.0), tail=(0.0, 0.0, 1.0)):
		self.name = name
		self.parent = None
		self.head = head
		self.tail = tail
		self.roll = 0.0
		self._use_connect = False

	@property
	def use_connect(self):
		return self._use_connect

	@use_connect.setter
	def use_connect(self, value):
		# Blender snaps a connected bone's head onto its parent's tail.
		self._use_connect = bool(value)
		if self._use_connect and self.parent is not None:
			self.head = self.parent.tail


class FakeBone:
	"""A bone in object mode: flags only, no geometry or hierarchy writes."""

	def __init__(self, name):
		self.name = name
		self.use_deform = True
		self.use_inherit_rotation = True
		self.inherit_scale = "FULL"
		self.envelope_distance = 0.25
		self.envelope_weight = 1.0
		self.hide = False


class FakeBoneMap:
	def __init__(self, names=()):
		self._items = {}
		for name in names:
			self._items[name] = self._make(name)

	def _make(self, name):
		return FakeBone(name)

	def get(self, name, default=None):
		return self._items.get(name, default)

	def __getitem__(self, name):
		return self._items[name]

	def __contains__(self, name):
		return name in self._items

	def __iter__(self):
		return iter(self._items.values())

	def __len__(self):
		return len(self._items)


class FakeEditBoneMap(FakeBoneMap):
	def _make(self, name):
		return FakeEditBone(name)

	def new(self, name):
		self._items[name] = FakeEditBone(name)
		return self._items[name]


class FakeArmature:
	def __init__(self, bone_names=()):
		self.bones = FakeBoneMap(bone_names)
		self.edit_bones = FakeEditBoneMap(bone_names)
		self.pose_position = "POSE"
		self.display_type = "OCTAHEDRAL"


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


class FakeViewLayerObjects:
	"""view_layer.objects: iterable, membership-testable, with an active."""

	def __init__(self):
		self.active = None
		self._items: list = []

	def add(self, obj):
		if obj not in self._items:
			self._items.append(obj)
		return obj

	def __iter__(self):
		return iter(self._items)

	def __contains__(self, key):
		if isinstance(key, str):
			return any(o.name == key for o in self._items)
		return key in self._items


class FakeViewLayer:
	def __init__(self):
		self.objects = FakeViewLayerObjects()


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
		self.view_layer = FakeViewLayer()

	@property
	def object(self):
		return self.view_layer.objects.active


class FakeModeSetOp:
	"""
	bpy.ops.object.mode_set, which acts on the *active* object only.

	Recording the sequence lets tests assert that a merge left the user where
	it found them rather than stranded in edit mode on someone else's object.
	"""

	def __init__(self, module):
		self._module = module
		self.calls: list = []

	def __call__(self, mode="OBJECT", **kwargs):
		active = self._module.context.view_layer.objects.active
		self.calls.append(mode)
		if active is None:
			raise RuntimeError("mode_set(): no active object")
		active.mode = mode
		return {"FINISHED"}


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

	mode_set = FakeModeSetOp(module)
	module.ops = types.SimpleNamespace(
		object=types.SimpleNamespace(mode_set=mode_set),
	)
	module.mode_set_calls = mode_set.calls

	sys.modules["bpy"] = module
	return module


def uninstall() -> None:
	sys.modules.pop("bpy", None)
