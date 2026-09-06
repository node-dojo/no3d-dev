"""Declarative catalog and searchable launcher for Feature Tools."""

from __future__ import annotations

from dataclasses import dataclass

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from . import ids


@dataclass(frozen=True)
class FeatureToolSpec:
    """Stable catalog identity for one action-style Feature Tool."""

    id: str
    label: str
    description: str
    operator: str
    icon: str = "NODETREE"
    order: int = 100


_registry: dict[str, FeatureToolSpec] = {}


def register_feature_tool(spec: FeatureToolSpec):
    if not isinstance(spec, FeatureToolSpec):
        raise TypeError("Feature Tools must register a FeatureToolSpec")
    if not all((spec.id, spec.label, spec.operator)) or "." not in spec.operator:
        raise ValueError(f"Invalid Feature Tool specification: {spec!r}")
    existing = _registry.get(spec.id)
    if existing is not None and existing != spec:
        raise ValueError(f'Feature Tool ID "{spec.id}" is already registered')
    if any(item.operator == spec.operator and item.id != spec.id for item in _registry.values()):
        raise ValueError(f'Feature Tool operator "{spec.operator}" is already registered')
    _registry[spec.id] = spec


def unregister_feature_tool(tool_id: str):
    _registry.pop(tool_id, None)


def registered_feature_tools():
    return tuple(sorted(_registry.values(), key=lambda spec: (spec.order, spec.label.lower(), spec.id)))


def feature_tool(tool_id: str):
    return _registry.get(tool_id)


def _tool_items(self, context):
    return [
        (spec.id, spec.label, spec.description, spec.icon, index)
        for index, spec in enumerate(registered_feature_tools())
    ]


def _operator_callable(identifier):
    namespace, name = identifier.split(".", 1)
    return getattr(getattr(bpy.ops, namespace), name)


def invoke_search_popup(operator, context):
    """Open Blender's search UI and satisfy the operator invoke contract."""
    context.window_manager.invoke_search_popup(operator)
    return {"RUNNING_MODAL"}


def draw_feature_tools(layout):
    column = layout.column(align=True)
    column.scale_y = 1.25
    for spec in registered_feature_tools():
        column.operator(spec.operator, text=spec.label, icon=spec.icon)


class NO3D_CAD_OT_feature_tool_search(Operator):
    """Search and run a Feature Tool from the shared catalog"""

    bl_idname = ids.FEATURE_TOOL_SEARCH_OT
    bl_label = "Add Feature Tool"
    bl_description = "Search the configured No3d CAD Feature Tools"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "feature_tool"

    feature_tool: EnumProperty(name="Feature Tool", items=_tool_items)

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return (
            space is not None
            and space.type == "NODE_EDITOR"
            and getattr(space, "tree_type", None) == "GeometryNodeTree"
        )

    def invoke(self, context, event):
        return invoke_search_popup(self, context)

    def execute(self, context):
        spec = feature_tool(self.feature_tool)
        if spec is None:
            self.report({"ERROR"}, "Feature Tool is no longer configured")
            return {"CANCELLED"}
        operator = _operator_callable(spec.operator)
        if not operator.poll():
            self.report({"WARNING"}, f"{spec.label} is not available in the current context")
            return {"CANCELLED"}
        return operator("INVOKE_DEFAULT")


CLASSES = (NO3D_CAD_OT_feature_tool_search,)
