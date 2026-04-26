from __future__ import annotations


def extract_world_data(scene) -> dict | None:
    """
    Parameters
    ----------
    scene : bpy.types.Scene
        The Blender scene object.

    Returns
    -------
    dict | None
        Plain Python dict safe to JSON-serialise.
        Returns None if no world is assigned to the scene.
    """
    world = scene.world
    if world is None:
        return None

    data: dict = {
        "name":              world.name,
        "use_nodes":         world.use_nodes,

        # Flat color fallback (used when use_nodes is False)
        "color":             list(world.color),

        # Ambient occlusion — attribute name changed across Blender versions
        "use_ao":            getattr(world.light_settings, "use_ambient_occlusion",
                                     getattr(world.light_settings, "use_ao", False)),
        "ao_factor":         getattr(world.light_settings, "ao_factor", 1.0),
        "ao_distance":       getattr(world.light_settings, "distance", 10.0),

        # Node-based background — populated below
        "background_color":    None,
        "background_strength": None, 
        "hdri_filepath":       None,
        "hdri_strength":       None,
    }

    if world.use_nodes and world.node_tree is not None:
        nodes = world.node_tree.nodes

        # Find the Background node
        bg_node = next(
            (n for n in nodes if n.type == "BACKGROUND"), None
        )
        if bg_node is not None:
            color_input    = bg_node.inputs.get("Color")
            strength_input = bg_node.inputs.get("Strength")

            if color_input is not None:
                data["background_color"] = list(color_input.default_value)
            if strength_input is not None:
                data["background_strength"] = float(strength_input.default_value)

            # Check if Color input is driven by an Environment Texture node
            if color_input is not None:
                for link in world.node_tree.links:
                    if link.to_socket == color_input:
                        from_node = link.from_node
                        if from_node.type == "TEX_ENVIRONMENT":
                            image = from_node.image
                            data["hdri_filepath"] = (
                                image.filepath if image else None
                            )
                            data["hdri_strength"] = data["background_strength"]
                        break

    return data