"""
blendiff.storage.migrate
~~~~~~~~~~~~~~~~~~~~~~~~~
Forward migration of serialized scene snapshots.

Snapshots live on disk for as long as the artist keeps their project, so
BlenDiff must keep reading snapshots written by every earlier release. Rather
than teaching the diff engine about every historical shape, snapshots are
migrated to the current schema as they are loaded.

Migration is *lossless and honest*: it never invents data. A v1 snapshot has no
F-curve information, so migration marks the F-curve domain as "not captured"
rather than filling in empty lists that would later read as deletions.

Migration happens in memory on read. The file on disk is only rewritten when
the caller explicitly asks (see ``SidecarManager.migrate_file``), so an older
BlenDiff can still open the sidecar until the user decides otherwise.
"""

from __future__ import annotations

import copy

from ..data_model.schema import (
	SCHEMA_VERSION,
	TRANSFORM_SPACE_WORLD,
	captured_domains,
	schema_version_of,
)


def migrate_scene(scene: dict, in_place: bool = False) -> dict:
	"""
    Bring a serialized scene dict up to the current schema version.

    Parameters
    ----------
    scene:
        A serialized scene as stored in a snapshot's ``data`` field.
    in_place:
        Mutate and return the input instead of a copy. Callers that own the
        dict (the sidecar loader) use this to avoid copying large snapshots.

    Returns
    -------
    The migrated scene dict. Unknown/newer versions are returned untouched so a
    downgrade never silently mangles data written by a future release.
    """
	if not isinstance(scene, dict):
		return scene

	version = schema_version_of(scene)
	if version >= SCHEMA_VERSION:
		return scene

	target = scene if in_place else copy.deepcopy(scene)

	if version < 2:
		_migrate_v1_to_v2(target)

	return target


def _migrate_v1_to_v2(scene: dict) -> None:
	"""
    v1 → v2.

    v1 snapshots predate schema versioning entirely. Two facts must be
    recovered and recorded explicitly:

    * which domains were captured — inferred from the keys actually present,
      which is exactly what those keys meant in v1;
    * that transforms were stored in **world** space, decomposed from
      ``matrix_world``. v2 stores local transforms, and the two spaces are not
      comparable, so the space is recorded rather than assumed.

    No object gains a ``blendiff_id``: v1 objects were never stamped, and
    inventing ids here would defeat identity matching by pairing unrelated
    objects that happened to be migrated in the same order.
    """
	# Inferred from the v1 keys — must be computed before the stamp is applied.
	domains = captured_domains(scene)

	scene["schema_version"] = 2
	scene["captured_domains"] = sorted(domains)
	scene.setdefault("transform_space", TRANSFORM_SPACE_WORLD)


def needs_migration(scene: dict) -> bool:
	"""True when this scene dict predates the current schema version."""
	return schema_version_of(scene) < SCHEMA_VERSION
