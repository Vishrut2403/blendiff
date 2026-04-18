from . import panels, operators, merge_panel

def register():
    operators.register()
    panels.register()
    merge_panel.register()

def unregister():
    merge_panel.unregister()
    panels.unregister()
    operators.unregister()