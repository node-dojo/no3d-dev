"""Fast one-vertex Geometry Nodes object creation."""

import bpy


class NO3D_AD_OT_add_geonode_object(bpy.types.Operator):
    """Create a one-vertex object with a fresh Geometry Nodes graph."""

    bl_idname = "mesh.no3d_add_geonode_object"
    bl_label = "Add GeoNode Object"
    bl_description = (
        "Add one vertex at the 3D Cursor with a new Geometry Nodes "
        "pass-through graph"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        mesh = bpy.data.meshes.new("GeoNode_obj")
        mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
        mesh.update()

        obj = bpy.data.objects.new("GeoNode_obj", mesh)
        context.collection.objects.link(obj)
        obj.location = context.scene.cursor.location

        for selected in tuple(context.selected_objects):
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

        node_group = bpy.data.node_groups.new(
            f"{obj.name} Geometry Nodes", "GeometryNodeTree"
        )
        node_group.interface.new_socket(
            name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
        )
        node_group.interface.new_socket(
            name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
        )
        group_input = node_group.nodes.new("NodeGroupInput")
        group_input.location = (-200.0, 0.0)
        group_output = node_group.nodes.new("NodeGroupOutput")
        group_output.location = (200.0, 0.0)
        node_group.links.new(group_input.outputs["Geometry"], group_output.inputs["Geometry"])

        modifier = obj.modifiers.new(name="GeometryNodes", type="NODES")
        modifier.node_group = node_group
        return {"FINISHED"}


_CLASSES = (NO3D_AD_OT_add_geonode_object,)
_addon_keymaps = []


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return
    keymap = keyconfig.keymaps.new(name="3D View", space_type="VIEW_3D")
    item = keymap.keymap_items.new(
        NO3D_AD_OT_add_geonode_object.bl_idname,
        "ONE",
        "PRESS",
        shift=True,
    )
    _addon_keymaps.append((keymap, item))


def unregister():
    for keymap, item in _addon_keymaps:
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            pass
    _addon_keymaps.clear()

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)

