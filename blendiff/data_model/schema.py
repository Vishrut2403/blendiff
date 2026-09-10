"""
blendiff.data_model.schema
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Snapshot schema versioning and domain-capture tracking.

Why this exists
---------------
BlenDiff's snapshot schema grows every release: 0.2 captured objects and
materials, 0.3 added render/world/camera/light/mesh, 0.4 added parenting and
constraints, 0.5 added custom properties, F-curves, drivers and NLA.

Without version tracking, diffing an old snapshot against a new one produces
*phantom changes*: the old snapshot has no ``fcurves`` key, so every F-curve in
the new snapshot reads as "added" and gets attributed to a user who never
touched the animation.

The fix is to record, per snapshot, which **domains** were actually captured.
A domain is only diffed when *both* sides captured it; otherwise it is reported
as skipped so the UI can say "not captured in this snapshot" instead of
inventing changes.

Legacy snapshots (written before ``schema_version`` existed) have their captured
domains *inferred* from which keys are physically present, which reproduces the
correct answer for every snapshot BlenDiff has ever written.
"""

from __future__ import annotations

from typing import Iterable

# Bump whenever the serialized scene shape changes in a way that affects diffing.
#   1 — implicit, pre-versioning (0.2 through 0.5)
#   2 — adds schema_version, captured_domains, blendiff_id, local transforms
SCHEMA_VERSION = 2

# Scene-level domains
DOMAIN_OBJECTS = "objects"
DOMAIN_COLLECTIONS = "collections"
DOMAIN_RENDER = "render"
DOMAIN_WORLD = "world"
DOMAIN_SCENE_CUSTOM_PROPS = "scene_custom_props"

# Per-object domains
DOMAIN_MATERIALS = "material_slots"
DOMAIN_CAMERA = "camera_data"
DOMAIN_LIGHT = "light_data"
DOMAIN_MESH = "mesh_data"
DOMAIN_ARMATURE = "armature_data"
DOMAIN_POSE = "pose_bones"
DOMAIN_MODIFIERS = "modifier_stack"
DOMAIN_PARENT = "parent"
DOMAIN_CONSTRAINTS = "constraint_stack"
DOMAIN_CUSTOM_PROPS = "custom_props"
DOMAIN_FCURVES = "fcurves"
DOMAIN_DRIVERS = "drivers"
DOMAIN_NLA = "nla_tracks"

SCENE_DOMAINS = (
	DOMAIN_OBJECTS,
	DOMAIN_COLLECTIONS,
	DOMAIN_RENDER,
	DOMAIN_WORLD,
	DOMAIN_SCENE_CUSTOM_PROPS,
)

OBJECT_DOMAINS = (
	DOMAIN_MATERIALS,
	DOMAIN_CAMERA,
	DOMAIN_LIGHT,
	DOMAIN_MESH,
	DOMAIN_ARMATURE,
	DOMAIN_POSE,
	DOMAIN_MODIFIERS,
	DOMAIN_PARENT,
	DOMAIN_CONSTRAINTS,
	DOMAIN_CUSTOM_PROPS,
	DOMAIN_FCURVES,
	DOMAIN_DRIVERS,
	DOMAIN_NLA,
)

ALL_DOMAINS = SCENE_DOMAINS + OBJECT_DOMAINS

# Human-readable names for UI and report output.
DOMAIN_LABELS = {
	DOMAIN_OBJECTS: "Objects",
	DOMAIN_COLLECTIONS: "Collections",
	DOMAIN_RENDER: "Render settings",
	DOMAIN_WORLD: "World",
	DOMAIN_SCENE_CUSTOM_PROPS: "Scene custom properties",
	DOMAIN_MATERIALS: "Materials",
	DOMAIN_CAMERA: "Camera data",
	DOMAIN_LIGHT: "Light data",
	DOMAIN_MESH: "Mesh data",
	DOMAIN_ARMATURE: "Armature rest data",
	DOMAIN_POSE: "Pose",
	DOMAIN_MODIFIERS: "Modifiers",
	DOMAIN_PARENT: "Parenting",
	DOMAIN_CONSTRAINTS: "Constraints",
	DOMAIN_CUSTOM_PROPS: "Custom properties",
	DOMAIN_FCURVES: "F-curves",
	DOMAIN_DRIVERS: "Drivers",
	DOMAIN_NLA: "NLA tracks",
}


def domain_label(domain: str) -> str:
	"""Human-readable name for a domain key."""
	return DOMAIN_LABELS.get(domain, domain)


def schema_version_of(scene: dict) -> int:
	"""
    Return the schema version of a serialized scene dict.

    Snapshots written before versioning existed report 1.
    """
	try:
		return int(scene.get("schema_version", 1))
	except (TypeError, ValueError):
		return 1


def captured_domains(scene: dict) -> set[str]:
	"""
    Return the set of domains this snapshot actually captured.

    For schema v2+ this is read straight from the snapshot. For legacy
    snapshots it is inferred from which keys are physically present, which
    is exactly what "was this captured?" means for pre-versioning data.
    """
	if not isinstance(scene, dict):
		return set()

	declared = scene.get("captured_domains")
	if isinstance(declared, (list, tuple, set)):
		return {str(d) for d in declared}

	return _infer_captured_domains(scene)


def _infer_captured_domains(scene: dict) -> set[str]:
	"""Infer captured domains for a legacy (pre-v2) snapshot."""
	found: set[str] = set()

	for domain in SCENE_DOMAINS:
		if domain in scene:
			found.add(domain)

	# A per-object domain counts as captured when any object carries the key.
	objects = scene.get("objects")
	if isinstance(objects, dict):
		for obj in objects.values():
			if not isinstance(obj, dict):
				continue
			for domain in OBJECT_DOMAINS:
				if domain in obj:
					found.add(domain)
			if len(found) >= len(ALL_DOMAINS):
				break

	return found


def comparable_domains(scene_a: dict, scene_b: dict) -> set[str]:
	"""Domains captured on both sides, and therefore safe to diff."""
	return captured_domains(scene_a) & captured_domains(scene_b)


def skipped_domains(scene_a: dict, scene_b: dict) -> set[str]:
	"""
    Domains captured on exactly one side.

    These cannot be diffed honestly: every value would read as added or
    removed purely because the older snapshot predates the feature.
    """
	a = captured_domains(scene_a)
	b = captured_domains(scene_b)
	return a ^ b


def describe_skipped(scene_a: dict, scene_b: dict) -> list[str]:
	"""Human-readable explanation of each skipped domain, for UI and reports."""
	a = captured_domains(scene_a)
	b = captured_domains(scene_b)
	messages = []
	for domain in ALL_DOMAINS:
		in_a, in_b = domain in a, domain in b
		if in_a == in_b:
			continue
		missing = "A" if in_b else "B"
		messages.append(
			f"{domain_label(domain)}: not captured in snapshot {missing} "
			f"— skipped to avoid reporting phantom changes"
		)
	return messages


# Transform space
#
# Schema v1 recorded transforms decomposed from ``matrix_world``; v2 records the
# object's own local location/rotation/scale. The two are not comparable — a
# parented object has completely different values in each space — so a snapshot
# pair that mixes them must skip transform diffing rather than report garbage.

TRANSFORM_SPACE_WORLD = "world"
TRANSFORM_SPACE_LOCAL = "local"


def transform_space(scene: dict) -> str:
	"""Return the space object transforms were recorded in."""
	if not isinstance(scene, dict):
		return TRANSFORM_SPACE_WORLD
	return str(scene.get("transform_space", TRANSFORM_SPACE_WORLD))


def transforms_comparable(scene_a: dict, scene_b: dict) -> bool:
	"""True when both snapshots recorded transforms in the same space."""
	return transform_space(scene_a) == transform_space(scene_b)


def stamp(scene: dict, domains: Iterable[str]) -> dict:
	"""Stamp a serialized scene with its schema version and captured domains."""
	scene["schema_version"] = SCHEMA_VERSION
	scene["captured_domains"] = sorted(set(domains))
	scene.setdefault("transform_space", TRANSFORM_SPACE_LOCAL)
	return scene
