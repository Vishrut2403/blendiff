"""
blendiff.ui.registration
~~~~~~~~~~~~~~~~~~~~~~~~~
Fault-tolerant class registration helpers.

Why this exists
---------------
``bpy.utils.unregister_class`` raises when handed a class that is not currently
registered::

    RuntimeError: unregister_class(...): missing bl_rna attribute from
    '_RNAMeta' instance (may not be registered)

The teardown loops used to call it unguarded, so a single unregistered class
raised and **aborted the rest of unregister** — leaving the addon half torn
down, with the remaining classes still registered and the WindowManager
properties never deleted. Blender then reports "Exception in module
unregister()" and the addon is stuck in a broken state until a restart.

This is not hypothetical. It fires whenever registration partially failed, and
in the case that is about to become common: installing the Extensions build
while the legacy addon zip is still enabled makes Blender disable the old copy,
whose teardown hits exactly this path.

Teardown must therefore be best-effort. Every class gets its chance to
unregister regardless of what happened to the ones before it, and a failure is
logged rather than raised — there is nothing useful a user can do with a
traceback thrown while an addon is being disabled.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

log = logging.getLogger(__name__)


def register_classes(classes: Iterable[Any]) -> list[Any]:
	"""
	Register each class, returning those that succeeded.

	Registration failures are raised, unlike teardown failures: a class that
	cannot register means the addon genuinely does not work, and Blender should
	report that to the user rather than silently loading a broken UI.
	"""
	import bpy

	registered = []
	for cls in classes:
		bpy.utils.register_class(cls)
		registered.append(cls)
	return registered


def unregister_classes(classes: Iterable[Any]) -> int:
	"""
	Unregister each class, best-effort, returning how many were removed.

	Classes are taken in reverse so that dependants go before dependencies.
	Each failure is logged and skipped so that one bad class cannot strand the
	rest in a registered state.
	"""
	import bpy

	removed = 0
	for cls in reversed(list(classes)):
		try:
			bpy.utils.unregister_class(cls)
			removed += 1
		except Exception as exc:
			# Almost always "may not be registered", which is benign during
			# teardown — the goal state is exactly what already holds.
			log.debug("Could not unregister %s: %s", getattr(cls, "__name__", cls), exc)
	return removed


def delete_properties(owner: Any, names: Iterable[str]) -> int:
	"""
	Delete RNA properties from a type, best-effort, returning how many went.

	``del bpy.types.WindowManager.foo`` raises AttributeError when the property
	is already gone, which during teardown is the desired state rather than an
	error worth propagating.
	"""
	removed = 0
	for name in names:
		try:
			delattr(owner, name)
			removed += 1
		except Exception as exc:
			log.debug("Could not delete property %r: %s", name, exc)
	return removed
