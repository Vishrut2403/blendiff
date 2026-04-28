from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def extract_parent_info(obj: Any) -> dict:
	parent = obj.parent

	if parent is None:
		return {
			"parent_name": None,
			"parent_type": None,
			"parent_bone": None,
		}

	parent_type = getattr(obj, "parent_type", "OBJECT")
	parent_bone = getattr(obj, "parent_bone", "") or None

	# parent_bone is only meaningful for BONE parenting
	if parent_type != "BONE":
		parent_bone = None

	return {
		"parent_name": parent.name,
		"parent_type": parent_type,
		"parent_bone": parent_bone,
	}