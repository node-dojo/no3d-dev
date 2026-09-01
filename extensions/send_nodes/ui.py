import bpy
from bpy.props import StringProperty


class SENDNODES_Properties(bpy.types.PropertyGroup):
    receive_url: StringProperty(
        name="Git URL",
        description="Public URL to a Send Nodes .blend bundle",
        subtype="NONE",
    )
    replace_existing: bpy.props.BoolProperty(
        name="Replace Existing",
        description="Replace a previously published bundle with the same name",
        default=False,
    )


class SENDNODES_PT_panel(bpy.types.Panel):
    bl_label = "Send Nodes"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Send Nodes"

    def draw(self, context):
        layout = self.layout
        state = context.window_manager.send_nodes

        send = layout.box()
        send.label(text="Send")
        send.prop(state, "replace_existing")
        operator = send.operator("send_nodes.export_group", icon="EXPORT")
        operator.replace_existing = state.replace_existing

        receive = layout.box()
        receive.label(text="Receive")
        receive.prop(state, "receive_url", text="")
        operator = receive.operator("send_nodes.receive_group", icon="IMPORT")
        operator.url = state.receive_url


classes = (
    SENDNODES_Properties,
    SENDNODES_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.send_nodes = bpy.props.PointerProperty(type=SENDNODES_Properties)


def unregister():
    del bpy.types.WindowManager.send_nodes
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
