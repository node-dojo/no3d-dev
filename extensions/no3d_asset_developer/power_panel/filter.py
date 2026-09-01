"""Live in-place filtering of actual 3D View sidebar category tabs."""

from difflib import SequenceMatcher
import re

import bpy
from bpy.props import StringProperty

from . import activation, config, discovery, slots


FILTER_PROPERTY = "no3d_sidebar_tab_filter"
_hidden_panels = set()
_latest_query = ""

CATEGORY_ALIASES = config.CATEGORY_ALIASES


def _panel_types(registered_only=True):
    return discovery.panel_types(registered_only)


def _depth(panel_type, by_idname):
    return discovery.depth(panel_type, by_idname)


def _tag_view3d_redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                # Redraw only the sidebar so live filtering does not rebuild
                # the Tool Settings header and interrupt its active text edit.
                for region in area.regions:
                    if region.type == "UI":
                        region.tag_redraw()


def _restore_hidden():
    if not _hidden_panels:
        return
    panels = list(_hidden_panels)
    by_idname = {
        getattr(panel, "bl_idname", panel.__name__): panel for panel in panels
    }
    pending = set(panels)
    for panel in sorted(panels, key=lambda item: _depth(item, by_idname)):
        try:
            bpy.utils.register_class(panel)
            pending.discard(panel)
        except (RuntimeError, ValueError):
            pass
    for panel in list(pending):
        try:
            bpy.utils.register_class(panel)
            pending.discard(panel)
        except (RuntimeError, ValueError) as exc:
            print(f"[NO3D Tab Filter] Could not restore {panel.__name__}: {exc}")
    _hidden_panels.difference_update(set(panels) - pending)


def _tokens(value):
    return re.findall(r"[a-z0-9]+", value.casefold())


def _fuzzy_token_matches(query_token, candidate_token):
    if query_token in candidate_token or candidate_token.startswith(query_token):
        return True
    if len(query_token) < 3:
        return False
    return SequenceMatcher(None, query_token, candidate_token).ratio() >= 0.72


def _category_matches(category, labels, query):
    query_tokens = _tokens(query)
    if not query_tokens:
        return True
    aliases = CATEGORY_ALIASES.get(slots.canonical_category(category), ())
    candidate_tokens = _tokens(" ".join((category, *aliases, *labels)))
    compact_query = "".join(query_tokens)
    compact_candidates = "".join(candidate_tokens)
    if compact_query and compact_query in compact_candidates:
        return True
    return all(
        any(_fuzzy_token_matches(query_token, candidate) for candidate in candidate_tokens)
        for query_token in query_tokens
    )


def apply_filter(query):
    """Show only matching actual tabs; empty query restores every panel."""
    _restore_hidden()
    normalized = query.casefold().strip()
    if not normalized:
        _tag_view3d_redraw()
        return True

    panels = _panel_types()
    by_idname = {
        getattr(panel, "bl_idname", panel.__name__): panel for panel in panels
    }
    grouped = {}
    for panel in panels:
        grouped.setdefault(getattr(panel, "bl_category", ""), []).append(panel)
    matching_categories = {
        category
        for category, category_panels in grouped.items()
        if _category_matches(
            category,
            [getattr(panel, "bl_label", "") for panel in category_panels],
            normalized,
        )
    }
    keep = {
        panel
        for category, category_panels in grouped.items()
        if category in matching_categories
        for panel in category_panels
    }

    # Preserve required ancestors. This may retain a dependency category for a
    # malformed cross-category parent relationship rather than breaking a
    # third-party panel during experimental filtering.
    for panel in list(keep):
        parent_id = getattr(panel, "bl_parent_id", "")
        while parent_id and parent_id in by_idname:
            parent = by_idname[parent_id]
            if parent in keep:
                break
            keep.add(parent)
            parent_id = getattr(parent, "bl_parent_id", "")

    hide = [panel for panel in panels if panel not in keep]
    for panel in sorted(hide, key=lambda item: _depth(item, by_idname), reverse=True):
        try:
            bpy.utils.unregister_class(panel)
            _hidden_panels.add(panel)
        except (RuntimeError, ValueError) as exc:
            print(f"[NO3D Tab Filter] Could not hide {panel.__name__}: {exc}")

    visible_matching_categories = sorted(
        {getattr(panel, "bl_category", "") for panel in keep if panel.is_registered},
        key=str.casefold,
    )
    if visible_matching_categories:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != "VIEW_3D":
                    continue
                region = next((item for item in area.regions if item.type == "UI"), None)
                if region is None:
                    continue
                activation.activate_area(area, visible_matching_categories[0])
    _tag_view3d_redraw()
    print(f"NO3D_TAB_FILTER_OK query={query!r} tabs={visible_matching_categories}")
    return True


def _apply_pending_filter():
    apply_filter(_latest_query)
    return None


def _filter_updated(window_manager, _context):
    global _latest_query
    _latest_query = getattr(window_manager, FILTER_PROPERTY, "")
    if not bpy.app.timers.is_registered(_apply_pending_filter):
        bpy.app.timers.register(_apply_pending_filter, first_interval=0.15)


class NO3D_AD_OT_clear_sidebar_tab_filter(bpy.types.Operator):
    bl_idname = "view3d.no3d_clear_sidebar_tab_filter"
    bl_label = "Clear Sidebar Tab Filter"
    bl_description = "Restore all sidebar tabs"

    def execute(self, context):
        setattr(context.window_manager, FILTER_PROPERTY, "")
        apply_filter("")
        return {"FINISHED"}


class NO3D_AD_OT_type_sidebar_tab_filter(bpy.types.Operator):
    """Type directly into the persistent N-panel filter from the 3D View."""

    bl_idname = "view3d.no3d_type_sidebar_tab_filter"
    bl_label = "Type N-Panel Tab Filter"
    bl_description = "Type to filter actual N-panel tabs; Enter keeps, Esc clears"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def _finish(self, context):
        context.workspace.status_text_set(None)
        context.area.tag_redraw()
        return {"FINISHED"}

    def invoke(self, context, _event):
        context.space_data.show_region_ui = True
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(
            "N-Panel Filter: type to filter tabs | Backspace edits | Enter keeps | Esc clears"
        )
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.value != "PRESS":
            return {"RUNNING_MODAL"}

        if event.type in {"RET", "NUMPAD_ENTER", "F5"}:
            return self._finish(context)

        if event.type == "ESC":
            setattr(context.window_manager, FILTER_PROPERTY, "")
            apply_filter("")
            return self._finish(context)

        query = getattr(context.window_manager, FILTER_PROPERTY, "")
        if event.type == "BACK_SPACE":
            setattr(context.window_manager, FILTER_PROPERTY, query[:-1])
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type in {"DEL", "X"} and event.ctrl:
            setattr(context.window_manager, FILTER_PROPERTY, "")
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "V" and event.oskey:
            pasted = context.window_manager.clipboard.replace("\n", " ").strip()
            if pasted:
                setattr(context.window_manager, FILTER_PROPERTY, query + pasted)
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.ascii and event.ascii.isprintable() and not any(
            (event.ctrl, event.alt, event.oskey)
        ):
            setattr(context.window_manager, FILTER_PROPERTY, query + event.ascii)
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}


_CLASSES = (
    NO3D_AD_OT_clear_sidebar_tab_filter,
    NO3D_AD_OT_type_sidebar_tab_filter,
)


def _draw_tool_header(self, context):
    layout = self.layout
    row = layout.row(align=True)
    row.prop(context.window_manager, FILTER_PROPERTY, text="", icon="VIEWZOOM")
    row.operator(
        NO3D_AD_OT_clear_sidebar_tab_filter.bl_idname,
        text="",
        icon="X",
    )
    row.operator(
        "view3d.no3d_search_sidebar_tabs",
        text="",
        icon="DOWNARROW_HLT",
    )


def _remove_tool_header_callbacks():
    """Remove current and stale copies left behind by live module reloads."""
    header = bpy.types.VIEW3D_HT_tool_header
    draw_funcs = tuple(getattr(getattr(header, "draw", None), "_draw_funcs", ()))
    for callback in draw_funcs:
        if (
            getattr(callback, "__name__", "") == _draw_tool_header.__name__
            and getattr(callback, "__module__", "") == __name__
        ):
            try:
                header.remove(callback)
            except (RuntimeError, ValueError):
                pass


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if not hasattr(bpy.types.WindowManager, FILTER_PROPERTY):
        setattr(
            bpy.types.WindowManager,
            FILTER_PROPERTY,
            StringProperty(
                name="Filter N-Panel Tabs",
                description="Type to leave only matching actual N-panel tabs visible",
                default="",
                options={"SKIP_SAVE", "TEXTEDIT_UPDATE"},
                update=_filter_updated,
            ),
        )
    _remove_tool_header_callbacks()
    bpy.types.VIEW3D_HT_tool_header.append(_draw_tool_header)


def unregister():
    if bpy.app.timers.is_registered(_apply_pending_filter):
        bpy.app.timers.unregister(_apply_pending_filter)
    _restore_hidden()
    _remove_tool_header_callbacks()
    if hasattr(bpy.types.WindowManager, FILTER_PROPERTY):
        delattr(bpy.types.WindowManager, FILTER_PROPERTY)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
