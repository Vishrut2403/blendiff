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


class FakeKeyBlock:
	"""One shape key."""

	def __init__(self, name, value=0.0, mute=False, slider_min=0.0, slider_max=1.0,
	             interpolation="KEY_LINEAR"):
		self.name = name
		self._value = value
		self.mute = mute
		self.slider_min = slider_min
		self.slider_max = slider_max
		self.interpolation = interpolation

	# Blender clamps a value write to the slider range rather than refusing
	# it, which the applier has to notice and report.
	@property
	def value(self):
		return self._value

	@value.setter
	def value(self, new):
		self._value = min(max(float(new), self.slider_min), self.slider_max)


class FakeShapeKeys:
	"""obj.data.shape_keys, whose key_blocks is looked up by name."""

	def __init__(self, blocks=(), use_relative=True):
		self.key_blocks = FakeIDMapView(blocks)
		self.use_relative = use_relative


class FakeIDMapView(list):
	"""A list that also answers .get(name), as bpy collections do."""

	def get(self, name, default=None):
		for item in self:
			if item.name == name:
				return item
		return default


class FakeSocket:
	"""One entry on a node group's interface."""

	def __init__(self, name: str, identifier: str, socket_type: str = "NodeSocketFloat",
	             in_out: str = "INPUT"):
		self.name = name
		self.identifier = identifier
		self.socket_type = socket_type
		self.in_out = in_out


class FakeNodeGroup:
	"""
	A node group, as far as a Geometry Nodes modifier is concerned.

	Only the interface matters here: it is what maps the visible socket name a
	snapshot records back to the opaque identifier the value is stored under.
	"""

	def __init__(self, name: str, sockets=()):
		self.name = name
		self.interface = FakeStruct(items_tree=list(sockets))


class FakeModifierStack(list):
	"""
	obj.modifiers, which is a bpy_prop_collection and not a list.

	Indexing and iteration work the same, and it also offers move(from, to),
	which is how Blender reorders a stack and therefore what the merge applier
	calls.
	"""

	def move(self, from_index: int, to_index: int) -> None:
		self.insert(to_index, self.pop(from_index))


class FakeModifier:
	"""
	One entry in obj.modifiers.

	Only the fields the merge applier writes: the common ones every modifier
	has, plus whichever type-specific attributes a test sets up. Attributes are
	plain, so setattr behaves as it does on a real modifier, and a write to an
	attribute the type does not have is caught by the applier before it gets
	here.
	"""

	def __init__(self, name: str, mod_type: str = "SUBSURF", **params):
		self.name = name
		self.type = mod_type
		self.show_viewport = True
		self.show_render = True
		self.is_active = True
		self.object = None
		self.node_group = None
		#: IDProperty storage, which is how a Geometry Nodes modifier holds
		#: its input values. Keyed by socket identifier, not by name.
		self._id_props: dict = {}
		for key, value in params.items():
			setattr(self, key, value)

	def __setitem__(self, key, value):
		self._id_props[key] = value

	def __getitem__(self, key):
		return self._id_props[key]

	def get(self, key, default=None):
		return self._id_props.get(key, default)

	def keys(self):
		return self._id_props.keys()


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
		self.modifiers: "FakeModifierStack" = FakeModifierStack()
		self.constraints: list["FakeConstraint"] = []
		self.library = None
		self.override_library = None
		#: None until a test gives the object drivers, matching bpy, where
		#: animation_data only exists once something is animated.
		self.animation_data = None
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


class FakeVertices(list):
	"""
	mesh.vertices, which the applier reads and writes through foreach_set.

	Only the flat buffer behaviour matters here: three floats per vertex, in
	vertex order, which is what Blender gives and takes.
	"""

	def __init__(self, count=0):
		super().__init__(range(count))
		self.coordinates = [0.0] * (count * 3)

	def foreach_set(self, attr, values):
		if attr != "co":
			raise AttributeError(attr)
		if len(values) != len(self.coordinates):
			raise RuntimeError("foreach_set: wrong buffer length")
		self.coordinates = list(values)

	def foreach_get(self, attr, buffer):
		if attr != "co":
			raise AttributeError(attr)
		buffer[:] = self.coordinates


class FakeMesh:
	"""A mesh datablock with just enough for the positions applier."""

	def __init__(self, vertex_count=0, name="Mesh"):
		self.name = name
		self.vertices = FakeVertices(vertex_count)
		self.updated = False

	def update(self):
		self.updated = True


class FakeConstraint:
	"""
	One entry in a constraint stack, on an object or on a pose bone.

	`mute` rather than `enabled`, matching bpy: the snapshot stores the
	inverse because "enabled" reads better in a report, and the applier is
	what flips it back.
	"""

	def __init__(self, name, con_type="COPY_LOCATION", **params):
		self.name = name
		self.type = con_type
		self.mute = False
		self.influence = 1.0
		self.target = None
		self.subtarget = ""
		for key, value in params.items():
			setattr(self, key, value)


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
		self.constraints: list["FakeConstraint"] = []


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


class FakeNodeSocket:
	"""
	One input socket on a material node.

	Unlike a node group's interface item, this one carries a value, so the
	applier's coercion and its refusal to write a linked socket are both
	exercised here.
	"""

	def __init__(self, name: str, socket_type: str = "VALUE", default_value: Any = 0.0,
	             is_linked: bool = False):
		self.name = name
		self.type = socket_type
		self.default_value = default_value
		self.is_linked = is_linked


class FakeNode:
	"""One node of a material's node tree."""

	def __init__(self, name: str, node_type: str = "BSDF_PRINCIPLED", inputs=(),
	             image: Any = None):
		self.name = name
		self.type = node_type
		#: A bpy_prop_collection: iterated by the material applier, which has
		#: to spot duplicate socket names, and .get() by the world one.
		self.inputs = FakeIDMapView(inputs)
		if image is not None or node_type == "TEX_IMAGE":
			self.image = image


class FakeNodeTree:
	def __init__(self, nodes=()):
		self.nodes = FakeIDMapView(nodes)


class FakeMaterial:
	def __init__(self, name: str, use_nodes: bool = False, nodes=None):
		self.name = name
		self.use_nodes = use_nodes
		self.node_tree = FakeNodeTree(nodes or ()) if use_nodes else None


class FakeImage:
	def __init__(self, name: str):
		self.name = name


class FakeDriver:
	"""bpy.types.Driver: what a driven FCurve evaluates."""

	def __init__(self, driver_type: str = "SCRIPTED", expression: str = "",
	             use_self: bool = False):
		self.type = driver_type
		self.expression = expression
		self.use_self = use_self


class FakeDrivenCurve:
	def __init__(self, data_path: str, array_index: int = 0, driver=None):
		self.data_path = data_path
		self.array_index = array_index
		self.driver = driver or FakeDriver()


class FakeDrivers(list):
	"""obj.animation_data.drivers, which answers find(data_path, index=)."""

	def find(self, data_path: str, index: int = 0):
		for curve in self:
			if curve.data_path == data_path and curve.array_index == index:
				return curve
		return None


class FakeAnimData:
	def __init__(self, drivers=()):
		self.drivers = FakeDrivers(drivers)


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

	def __init__(self, scene_objects=None):
		self._items: dict[str, Any] = {}
		#: When set, adding also places the item in the scene, so that
		#: bpy.data and scene membership agree by default.
		self._scene_objects = scene_objects

	def get(self, name, default=None):
		return self._items.get(name, default)

	def add(self, item, in_scene: bool = True):
		"""
		Register the item. Pass in_scene=False for something that exists in the
		file but is not in the scene, such as an object linked from a library
		or one belonging to another scene.
		"""
		self._items[item.name] = item
		if in_scene and self._scene_objects is not None and item not in self._scene_objects:
			self._scene_objects.append(item)
		return item

	def remove(self, item, do_unlink: bool = False):
		for collection in list(getattr(item, "_collections", [])):
			collection.objects.unlink(item)
		self._items.pop(item.name, None)
		if self._scene_objects is not None and item in self._scene_objects:
			self._scene_objects.remove(item)

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


class FakeSceneObjects(list):
	"""
	scene.objects, which is a bpy_prop_collection rather than a list.

	It is subscripted and iterated like a list, and it also answers .get(name).
	The list behaviour is what the tests use; the .get is what the merge
	applier uses to resolve a target to the scene rather than to the whole
	file, so the fake has to offer both or the applier cannot be tested.
	"""

	def get(self, name, default=None):
		for obj in self:
			if obj.name == name:
				return obj
		return default


class FakeMarker:
	def __init__(self, name: str, frame: int = 0, camera: Any = None):
		self.name = name
		self.frame = frame
		self.camera = camera


class FakeTimelineMarkers(list):
	"""scene.timeline_markers, which creates and removes by name."""

	def get(self, name, default=None):
		for marker in self:
			if marker.name == name:
				return marker
		return default

	def __getitem__(self, key):
		if isinstance(key, str):
			marker = self.get(key)
			if marker is None:
				raise KeyError(key)
			return marker
		return list.__getitem__(self, key)

	def new(self, name: str, frame: int = 0) -> FakeMarker:
		marker = FakeMarker(name, frame)
		self.append(marker)
		return marker

	def remove(self, marker: FakeMarker) -> None:
		list.remove(self, marker)


class FakeWorld:
	def __init__(self, name="World", use_nodes=False, nodes=(), color=(0.05, 0.05, 0.05)):
		self.name = name
		self.use_nodes = use_nodes
		self.node_tree = FakeNodeTree(nodes) if use_nodes else None
		self.color = color
		self.light_settings = FakeStruct(
			use_ambient_occlusion=False, ao_factor=1.0, distance=10.0,
		)


class FakeScene:
	"""
	A scene, as far as the merge applier is concerned.

	The sub-structs are flattened into one dict by the extractor, so the
	applier has to find its way back to render.image_settings.file_format and
	view_settings.exposure. Modelling them separately here is what makes a
	wrong target visible as an AttributeError instead of silently writing the
	right value in the wrong place.
	"""

	def __init__(self, name="Scene"):
		self.name = name
		self.collection = FakeCollection("Scene Collection")
		self.objects: FakeSceneObjects = FakeSceneObjects()
		self.frame_start = 1
		self.frame_end = 250
		self.frame_step = 1
		self.render = FakeStruct(
			engine="CYCLES",
			resolution_x=1920,
			resolution_y=1080,
			resolution_percentage=100,
			filepath="/tmp/",
			fps=24,
			fps_base=1.0,
			image_settings=FakeStruct(
				file_format="PNG", color_mode="RGBA", color_depth="8",
			),
		)
		self.display_settings = FakeStruct(display_device="sRGB")
		self.view_settings = FakeStruct(
			view_transform="Filmic", look="None", exposure=0.0, gamma=1.0,
		)
		self.cycles = FakeStruct(
			samples=128, preview_samples=32, use_denoising=False,
			denoiser="OPENIMAGEDENOISE", device="CPU",
		)
		self.eevee = FakeStruct(taa_render_samples=64)
		self.unit_settings = FakeStruct(
			system="METRIC", system_rotation="DEGREES", scale_length=1.0,
			use_separate=False, length_unit="METERS",
		)
		self.timeline_markers = FakeTimelineMarkers()
		self.world = None
		self._props: dict[str, Any] = {}

	# Custom properties, which are item access on the scene in bpy.

	def __getitem__(self, key):
		return self._props[key]

	def __setitem__(self, key, value):
		self._props[key] = value

	def __delitem__(self, key):
		del self._props[key]

	def __contains__(self, key):
		return key in self._props

	def keys(self):
		return self._props.keys()


class FakeBpyData:
	def __init__(self, scene_objects=None):
		self.objects = FakeIDMap(scene_objects)
		self.materials = FakeIDMap()
		self.collections = FakeIDMap()
		self.images = FakeIDMap()
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
	scene = scene or FakeScene()

	global _DATA
	_DATA = FakeBpyData(scene.objects)
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
