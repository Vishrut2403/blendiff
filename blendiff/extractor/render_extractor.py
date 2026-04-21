"""
Reads bpy.scene.render (and cycles/eevee sub-objects) into a plain dict.
This is the ONLY module that touches bpy for render settings.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import bpy as _bpy


def extract_render_settings(scene) -> dict:
    """
    Parameters
    ----------
    scene : bpy.types.Scene
        The Blender scene object (passed in, never imported at module level).

    Returns
    -------
    dict
        Plain Python dict — safe to JSON-serialise with no mathutils types.
    """
    render = scene.render

    data: dict = {
        # Engine
        "engine": render.engine,

        # Resolution
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,

        # Output
        "filepath": render.filepath,
        "file_format": render.image_settings.file_format,
        "color_mode": render.image_settings.color_mode,
        "color_depth": render.image_settings.color_depth,

        # Frame range
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_step": scene.frame_step,
        "fps": render.fps,
        "fps_base": render.fps_base,

        # Color management
        "display_device": scene.display_settings.display_device,
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": scene.view_settings.exposure,
        "gamma": scene.view_settings.gamma,

        # Engine-specific — populated below
        "cycles": {},
        "eevee": {},
    }

    # Cycles settings (only available when Cycles is installed)
    cycles = getattr(scene, "cycles", None)
    if cycles is not None:
        data["cycles"] = {
            "samples": getattr(cycles, "samples", 128),
            "preview_samples": getattr(cycles, "preview_samples", 32),
            "use_denoising": getattr(cycles, "use_denoising", False),
            "denoiser": getattr(cycles, "denoiser", ""),
            "device": getattr(cycles, "device", "CPU"),
        }

    # EEVEE settings
    eevee = getattr(scene, "eevee", None)
    if eevee is not None:
        data["eevee"] = {
            "taa_render_samples": getattr(eevee, "taa_render_samples", 64),
            "use_bloom": getattr(eevee, "use_bloom", False),
            "use_ssr": getattr(eevee, "use_ssr", False),
            "shadow_cube_size": getattr(eevee, "shadow_cube_size", "512"),
            "shadow_cascade_size": getattr(eevee, "shadow_cascade_size", "1024"),
        }

    return data