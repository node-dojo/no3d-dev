bl_info = {
    "name": "No3d Camera Utilities",
    "author": "Hanuman + Cursor",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > No3d Cam",
    "description": "2D/3D mesh camera tools, framing, and render utilities",
    "category": "3D View",
}

import bpy
import datetime
import math
import os
import platform
import re
import shutil
import subprocess
from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


PAIR_TAG = "make_mesh_camera_target"
PAIR_CAM_NAME = "make_mesh_camera_name"
PAIR_RES_X = "make_mesh_camera_res_x"
PAIR_RES_Y = "make_mesh_camera_res_y"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_RENDER_PATH = "//mesh_camera_render.png"
SCENE_OUTPUT_PATH = "make_mesh_camera_output_path"
SCENE_COPY_CLIPBOARD = "make_mesh_camera_copy_to_clipboard"
SCENE_COPY_OBSIDIAN = "make_mesh_camera_copy_to_obsidian"
SCENE_USE_FILENAME_MACRO = "make_mesh_camera_use_filename_macro"
SCENE_FILENAME_TEMPLATE = "make_mesh_camera_filename_template"
SCENE_KEEP_CAMERA = "make_mesh_camera_keep_camera"
SCENE_HIDE_ALL_ELSE = "make_mesh_camera_hide_all_else"
SCENE_3D_BUFFER_PCT = "make_mesh_camera_3d_buffer_pct"
SCENE_3D_USE_CONVEX_HULL = "make_mesh_camera_3d_use_convex_hull"
DEFAULT_OBSIDIAN_ASSETS_PATH = "~/Vault_001/The Well Notebook/assets"
ADDON_ID = (__package__ or os.path.splitext(os.path.basename(__file__))[0])
MAX_3D_FIT_POINTS = 8000
HULL_3D_FIT_SAMPLE_POINTS = 2500
FRAMING_PLANE_CAMERA_TAG = "mesh_camera_framing_plane_camera"
DEFAULT_LONG_EDGE_PX = 2048

PIE_DIRECTIONS = (
    ("WEST", "West", "Left slot"),
    ("EAST", "East", "Right slot"),
    ("SOUTH", "South", "Bottom slot"),
    ("NORTH", "North", "Top slot"),
    ("NORTH_WEST", "North West", "Top-left slot"),
    ("NORTH_EAST", "North East", "Top-right slot"),
    ("SOUTH_WEST", "South West", "Bottom-left slot"),
    ("SOUTH_EAST", "South East", "Bottom-right slot"),
    ("HIDDEN", "Hidden", "Do not show in pie menu"),
)

HOTKEY_TYPES = (
    ("Q", "Q", ""),
    ("W", "W", ""),
    ("E", "E", ""),
    ("R", "R", ""),
    ("F", "F", ""),
    ("G", "G", ""),
    ("Z", "Z", ""),
    ("X", "X", ""),
    ("C", "C", ""),
    ("V", "V", ""),
    ("SPACE", "Space", ""),
    ("TAB", "Tab", ""),
    ("ACCENT_GRAVE", "`", ""),
)

PIE_ACTIONS = (
    ("make_2d", "Make 2D Mesh Camera", "object.make_mesh_camera", "CAMERA_DATA"),
    ("refresh_2d", "Refresh 2D Mesh Camera", "object.refresh_mesh_camera", "FILE_REFRESH"),
    ("make_3d", "Make 3D Mesh Camera", "object.make_3d_mesh_camera", "VIEW_CAMERA"),
    ("make_3d_marquee", "Make 3D Mesh Camera (Marquee)", "object.make_3d_mesh_camera_marquee", "VIEWZOOM"),
    ("draw_3d_plane", "Draw 3D Framing Plane", "object.make_3d_framing_plane_marquee", "SELECT_SET"),
    ("refresh_3d_plane", "Refresh 3D Camera From Plane", "object.refresh_3d_camera_from_plane", "FILE_REFRESH"),
    ("one_shot", "One-Shot Selected Mesh(es)", "object.one_shot_selected_mesh", "PLAY"),
    ("render_2d", "Render Mesh Camera", "object.render_mesh_camera", "RENDER_STILL"),
    ("render_3d", "Render Active 3D Camera", "object.render_active_3d_camera", "RENDER_ANIMATION"),
)

PIE_ACTION_PROP_MAP = {aid: f"pie_pos_{aid}" for aid, _lbl, _op, _ic in PIE_ACTIONS}
_addon_keymaps = []


def find_paired_cameras(obj):
    cameras = []
    for candidate in bpy.data.objects:
        if candidate.type != "CAMERA":
            continue
        tagged = candidate.get(PAIR_TAG) == obj.name
        legacy = candidate.parent == obj and candidate.name.startswith("MakeMeshCam_")
        if tagged or legacy:
            cameras.append(candidate)
    return cameras


def choose_paired_camera(scene, obj):
    candidates = find_paired_cameras(obj)
    if not candidates:
        return None
    if scene.camera in candidates:
        return scene.camera
    preferred_name = obj.get(PAIR_CAM_NAME)
    if preferred_name and preferred_name in bpy.data.objects:
        preferred = bpy.data.objects[preferred_name]
        if preferred in candidates:
            return preferred
    return sorted(candidates, key=lambda c: c.name)[0]


def apply_scene_resolution_from_camera(scene, cam_obj):
    res_x = int(cam_obj.get(PAIR_RES_X, 0) or 0)
    res_y = int(cam_obj.get(PAIR_RES_Y, 0) or 0)
    if res_x > 0 and res_y > 0:
        scene.render.resolution_x = res_x
        scene.render.resolution_y = res_y
        scene.render.resolution_percentage = 100
        return res_x, res_y
    return scene.render.resolution_x, scene.render.resolution_y


def get_addon_prefs(context):
    addon = context.preferences.addons.get(ADDON_ID)
    if addon:
        return addon.preferences
    for mod_name, mod in context.preferences.addons.items():
        if mod_name.endswith(ADDON_ID) and hasattr(mod.preferences, "obsidian_assets_path"):
            return mod.preferences
    return None


def build_pie_direction_map(prefs):
    direction_to_action = {}
    for action_id, _label, op_id, icon in PIE_ACTIONS:
        prop_name = PIE_ACTION_PROP_MAP[action_id]
        direction = getattr(prefs, prop_name, "HIDDEN") if prefs else "HIDDEN"
        if direction and direction != "HIDDEN":
            direction_to_action[direction] = (action_id, op_id, icon)
    return direction_to_action


def unregister_pie_keymap():
    global _addon_keymaps
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps = []
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    for km in kc.keymaps:
        to_remove = []
        for kmi in km.keymap_items:
            if (
                kmi.idname == "wm.call_menu_pie"
                and getattr(kmi.properties, "name", "") == "VIEW3D_MT_hanuman_mesh_camera_pie"
            ):
                to_remove.append(kmi)
        for kmi in to_remove:
            try:
                km.keymap_items.remove(kmi)
            except Exception:
                pass


def register_pie_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return

    prefs = get_addon_prefs(bpy.context)
    hotkey = getattr(prefs, "pie_hotkey", "E") if prefs else "E"
    ctrl = bool(getattr(prefs, "pie_ctrl", True)) if prefs else True
    shift = bool(getattr(prefs, "pie_shift", True)) if prefs else True
    alt = bool(getattr(prefs, "pie_alt", False)) if prefs else False

    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
    kmi = km.keymap_items.new(
        "wm.call_menu_pie",
        type=hotkey,
        value="PRESS",
        ctrl=ctrl,
        shift=shift,
        alt=alt,
    )
    kmi.properties.name = "VIEW3D_MT_hanuman_mesh_camera_pie"
    _addon_keymaps.append((km, kmi))


def get_obsidian_assets_dir(context):
    prefs = get_addon_prefs(context)
    raw_path = prefs.obsidian_assets_path if prefs else DEFAULT_OBSIDIAN_ASSETS_PATH
    return bpy.path.abspath(os.path.expanduser(raw_path))


def get_selected_mesh_target(context):
    def is_framing_plane(obj):
        return obj is not None and obj.type == "MESH" and obj.get(FRAMING_PLANE_CAMERA_TAG) is not None

    active = context.active_object
    if active is not None and active.type == "MESH" and not is_framing_plane(active):
        return active
    for obj in context.selected_objects:
        if obj.type == "MESH" and not is_framing_plane(obj):
            return obj
    return None


def snapshot_hide_render(scene):
    return {obj.name: obj.hide_render for obj in scene.objects}


def restore_hide_render(scene, snapshot):
    for name, hidden in snapshot.items():
        if name in bpy.data.objects:
            bpy.data.objects[name].hide_render = hidden


def hide_all_else_for_mesh(scene, mesh_obj):
    for obj in scene.objects:
        if obj == mesh_obj:
            obj.hide_render = False
            continue
        if obj.type in {"CAMERA", "LIGHT"}:
            continue
        obj.hide_render = True


def get_evaluated_world_vertices(context, obj):
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    if eval_obj.type != "MESH":
        raise ValueError(f"Selected object '{obj.name}' does not evaluate to a mesh.")

    temp_mesh = eval_obj.to_mesh()
    try:
        if temp_mesh is None or len(temp_mesh.vertices) == 0:
            raise ValueError(
                f"Selected object '{obj.name}' has no evaluated mesh output to fit camera bounds."
            )
        world_m = eval_obj.matrix_world.copy()
        return [world_m @ v.co for v in temp_mesh.vertices]
    finally:
        eval_obj.to_mesh_clear()


def copy_png_to_clipboard(path):
    if platform.system() != "Darwin":
        return False, "Clipboard image copy is currently implemented for macOS only."
    if not os.path.exists(path):
        return False, f"Rendered file not found: {path}"
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'set the clipboard to (read (POSIX file "{escaped}") as «class PNGf»)'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return True, ""
    except Exception as exc:
        return False, str(exc)


def safe_filename_part(value):
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    clean = clean.strip("._")
    return clean or "untitled"


def sample_points_for_fit(points, max_points=MAX_3D_FIT_POINTS):
    n = len(points)
    if n <= max_points:
        return points
    # Preserve geometric extremes so sampled set still captures rough bounds.
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    zs = [p.z for p in points]
    extreme_idx = {
        xs.index(min(xs)), xs.index(max(xs)),
        ys.index(min(ys)), ys.index(max(ys)),
        zs.index(min(zs)), zs.index(max(zs)),
    }

    keep = [points[i] for i in sorted(extreme_idx)]
    remaining = max(0, max_points - len(keep))
    if remaining == 0:
        return keep

    step = n / float(remaining)
    sampled = []
    for i in range(remaining):
        idx = int(i * step)
        if idx >= n:
            idx = n - 1
        sampled.append(points[idx])
    return keep + sampled


def convex_hull_points(points):
    # Compute a 3D convex hull from world-space points using bmesh.
    # Fall back to original points if hull generation fails.
    if len(points) <= 8:
        return points
    try:
        import bmesh

        bm = bmesh.new()
        for p in points:
            bm.verts.new(p)
        bm.verts.ensure_lookup_table()
        result = bmesh.ops.convex_hull(bm, input=bm.verts, use_existing_faces=False)
        for geom_key in ("geom_interior", "geom_unused"):
            for g in result.get(geom_key, []):
                try:
                    bm.verts.remove(g)
                except Exception:
                    pass
        hull = [v.co.copy() for v in bm.verts]
        bm.free()
        return hull if hull else points
    except Exception:
        return points


def resolve_render_output_path(scene, mesh_name, camera_name):
    base_path = bpy.path.abspath(getattr(scene, SCENE_OUTPUT_PATH, DEFAULT_RENDER_PATH))
    if not base_path:
        base_path = DEFAULT_RENDER_PATH

    use_macro = bool(getattr(scene, SCENE_USE_FILENAME_MACRO, False))
    if not use_macro:
        if not base_path.lower().endswith(".png"):
            base_path += ".png"
        return base_path

    template = str(getattr(scene, SCENE_FILENAME_TEMPLATE, "{mesh}_{camera}_{timestamp}.png")).strip()
    if not template:
        template = "{mesh}_{camera}_{timestamp}.png"

    if os.path.isdir(base_path) or base_path.endswith(os.sep):
        out_dir = base_path
    else:
        out_dir = os.path.dirname(base_path) or PROJECT_ROOT
    os.makedirs(out_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    tokens = {
        "mesh": safe_filename_part(mesh_name),
        "camera": safe_filename_part(camera_name),
        "timestamp": timestamp,
    }
    try:
        filename = template.format(**tokens)
    except Exception:
        filename = f"{tokens['mesh']}_{tokens['camera']}_{tokens['timestamp']}.png"

    filename = safe_filename_part(filename.replace(os.sep, "_"))
    if not filename.lower().endswith(".png"):
        filename += ".png"
    return os.path.join(out_dir, filename)


def build_obsidian_filename(mesh_name, camera_name):
    blend_stem = os.path.splitext(os.path.basename(bpy.data.filepath))[0] if bpy.data.filepath else "untitled_blend"
    blend_stem = safe_filename_part(blend_stem)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    return (
        f"{blend_stem}_{safe_filename_part(mesh_name)}_"
        f"{safe_filename_part(camera_name)}_{timestamp}.png"
    )


def copy_render_to_obsidian(context, source_path, mesh_name, camera_name):
    if not os.path.exists(source_path):
        return False, f"Rendered file not found: {source_path}", ""

    target_dir = get_obsidian_assets_dir(context)
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as exc:
        return False, f"Cannot create Obsidian assets directory: {exc}", ""

    out_name = build_obsidian_filename(mesh_name, camera_name)
    destination = os.path.join(target_dir, out_name)
    try:
        shutil.copy2(source_path, destination)
        return True, "", destination
    except Exception as exc:
        return False, str(exc), ""


def fit_camera_to_mesh(context, obj, cam_obj, long_edge_px, padding_pct):
    world_verts = get_evaluated_world_vertices(context, obj)
    cam_inv = cam_obj.matrix_world.inverted()
    cam_verts = [cam_inv @ v for v in world_verts]

    # Keep orientation and ensure mesh is in front of camera.
    max_z = max(v.z for v in cam_verts)
    if max_z >= -1e-4:
        span_guess = max(
            max(v.x for v in cam_verts) - min(v.x for v in cam_verts),
            max(v.y for v in cam_verts) - min(v.y for v in cam_verts),
        )
        depth_margin = max(0.01, span_guess * 0.25)
        delta_world = cam_obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, max_z + depth_margin))
        world_m = cam_obj.matrix_world.copy()
        world_m.translation = world_m.translation + delta_world
        cam_obj.matrix_world = world_m
        cam_inv = cam_obj.matrix_world.inverted()
        cam_verts = [cam_inv @ v for v in world_verts]

    min_x = min(v.x for v in cam_verts)
    max_x = max(v.x for v in cam_verts)
    min_y = min(v.y for v in cam_verts)
    max_y = max(v.y for v in cam_verts)
    span_x = max_x - min_x
    span_y = max_y - min_y

    if span_x <= 1e-9 or span_y <= 1e-9:
        raise ValueError(
            "Mesh is edge-on to camera. Rotate camera/view and retry "
            f"(projected spans x={span_x:.6g}, y={span_y:.6g})."
        )

    center_x = 0.5 * (min_x + max_x)
    center_y = 0.5 * (min_y + max_y)
    delta_world = cam_obj.matrix_world.to_3x3() @ Vector((center_x, center_y, 0.0))
    world_m = cam_obj.matrix_world.copy()
    world_m.translation = world_m.translation + delta_world
    cam_obj.matrix_world = world_m

    if span_x >= span_y:
        res_x = long_edge_px
        res_y = max(1, int(round(long_edge_px * (span_y / span_x))))
    else:
        res_y = long_edge_px
        res_x = max(1, int(round(long_edge_px * (span_x / span_y))))

    cam_data = cam_obj.data
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = span_x * (1.0 + padding_pct / 100.0)
    cam_data.clip_start = 0.001
    cam_data.clip_end = 100000.0

    return span_x, span_y, res_x, res_y


def project_bbox(scene, cam_obj, points):
    vals = [world_to_camera_view(scene, cam_obj, co) for co in points]
    min_x = min(v.x for v in vals)
    max_x = max(v.x for v in vals)
    min_y = min(v.y for v in vals)
    max_y = max(v.y for v in vals)
    return min_x, max_x, min_y, max_y


def set_resolution_for_aspect(scene, target_aspect):
    long_edge = max(1, scene.render.resolution_x, scene.render.resolution_y)
    if target_aspect >= 1.0:
        res_x = long_edge
        res_y = max(1, int(round(long_edge / target_aspect)))
    else:
        res_y = long_edge
        res_x = max(1, int(round(long_edge * target_aspect)))
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100


def resolution_from_aspect(target_aspect, long_edge_px=DEFAULT_LONG_EDGE_PX):
    aspect = max(1e-6, float(target_aspect))
    long_edge = max(1, int(long_edge_px))
    if aspect >= 1.0:
        res_x = long_edge
        res_y = max(1, int(round(long_edge / aspect)))
    else:
        res_y = long_edge
        res_x = max(1, int(round(long_edge * aspect)))
    return res_x, res_y


def set_camera_resolution_from_aspect(cam_obj, target_aspect, long_edge_px=DEFAULT_LONG_EDGE_PX):
    res_x, res_y = resolution_from_aspect(target_aspect, long_edge_px)
    cam_obj[PAIR_RES_X] = int(res_x)
    cam_obj[PAIR_RES_Y] = int(res_y)
    return res_x, res_y


def camera_local_aspect_from_points(cam_obj, points):
    if not points:
        return 1.0
    cam_inv = cam_obj.matrix_world.inverted()
    cam_points = [cam_inv @ co for co in points]
    span_x = max(1e-6, max(p.x for p in cam_points) - min(p.x for p in cam_points))
    span_y = max(1e-6, max(p.y for p in cam_points) - min(p.y for p in cam_points))
    return span_x / span_y


def fit_perspective_camera_to_points(
    context,
    scene,
    cam_obj,
    points,
    buffer_pct,
    rect_ndc=None,
    set_aspect=True,
):
    if rect_ndc is None:
        rect_ndc = (0.0, 0.0, 1.0, 1.0)
    rx0, ry0, rx1, ry1 = rect_ndc
    rect_span_x = max(1e-6, rx1 - rx0)
    rect_span_y = max(1e-6, ry1 - ry0)
    rect_center_x = (rx0 + rx1) * 0.5
    rect_center_y = (ry0 + ry1) * 0.5
    target_span_x = rect_span_x / (1.0 + buffer_pct / 100.0)
    target_span_y = rect_span_y / (1.0 + buffer_pct / 100.0)

    # Match output frame aspect to drawn boundary aspect when desired.
    if set_aspect:
        set_resolution_for_aspect(scene, rect_span_x / rect_span_y)

    center = Vector((0.0, 0.0, 0.0))
    for co in points:
        center += co
    center /= len(points)
    base_vec = cam_obj.location - center
    if base_vec.length < 1e-8:
        base_vec = cam_obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, 10.0))

    def ratio_for_k(k):
        cam_obj.location = center + base_vec * k
        context.view_layer.update()
        min_x, max_x, min_y, max_y = project_bbox(scene, cam_obj, points)
        span_x = max_x - min_x
        span_y = max_y - min_y
        ratio = max(span_x / target_span_x, span_y / target_span_y)
        return ratio, (min_x, max_x, min_y, max_y)

    # Solve camera distance for target bounds.
    r0, _ = ratio_for_k(1.0)
    lo = 1.0
    hi = 1.0
    if r0 > 1.0:
        while hi < 1e6:
            hi *= 1.5
            r, _ = ratio_for_k(hi)
            if r <= 1.0:
                break
        lo = hi / 1.5
    else:
        while lo > 1e-6:
            lo *= 0.67
            r, _ = ratio_for_k(lo)
            if r >= 1.0:
                break
        hi = lo / 0.67

    bbox = None
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        r, b = ratio_for_k(mid)
        bbox = b
        if r > 1.0:
            lo = mid
        else:
            hi = mid
    _r, bbox = ratio_for_k(hi)
    min_x, max_x, min_y, max_y = bbox

    # Shift camera in local XY to align projected center to marquee center.
    for _ in range(6):
        min_x, max_x, min_y, max_y = project_bbox(scene, cam_obj, points)
        cx = 0.5 * (min_x + max_x)
        cy = 0.5 * (min_y + max_y)
        dx = rect_center_x - cx
        dy = rect_center_y - cy
        if abs(dx) < 0.001 and abs(dy) < 0.001:
            break

        axes = cam_obj.matrix_world.to_3x3()
        x_axis = axes @ Vector((1.0, 0.0, 0.0))
        y_axis = axes @ Vector((0.0, 1.0, 0.0))
        eps = max(base_vec.length * 1e-4, 1e-4)

        base_loc = cam_obj.location.copy()
        cam_obj.location = base_loc + x_axis * eps
        context.view_layer.update()
        min_x1, max_x1, min_y1, max_y1 = project_bbox(scene, cam_obj, points)
        cx1 = 0.5 * (min_x1 + max_x1)
        cy1 = 0.5 * (min_y1 + max_y1)

        cam_obj.location = base_loc + y_axis * eps
        context.view_layer.update()
        min_x2, max_x2, min_y2, max_y2 = project_bbox(scene, cam_obj, points)
        cx2 = 0.5 * (min_x2 + max_x2)
        cy2 = 0.5 * (min_y2 + max_y2)

        cam_obj.location = base_loc
        context.view_layer.update()

        a = (cx1 - cx) / eps
        b = (cx2 - cx) / eps
        c = (cy1 - cy) / eps
        d = (cy2 - cy) / eps
        det = a * d - b * c
        if abs(det) < 1e-9:
            break
        tx = (dx * d - b * dy) / det
        ty = (a * dy - dx * c) / det
        cam_obj.location = cam_obj.location + x_axis * tx + y_axis * ty
        context.view_layer.update()

    min_x, max_x, min_y, max_y = project_bbox(scene, cam_obj, points)
    return max_x - min_x, max_y - min_y


def create_3d_camera_from_view(context, rect_ndc=None):
    scene = context.scene
    region_3d = context.region_data
    space = context.space_data
    target = get_selected_mesh_target(context)
    buffer_pct = max(0.0, float(getattr(scene, SCENE_3D_BUFFER_PCT, 5.0)))
    use_convex_hull = bool(getattr(scene, SCENE_3D_USE_CONVEX_HULL, False))

    cam_data = bpy.data.cameras.new(name=f"Make3DCamData_{target.name if target else 'Scene'}")
    cam_obj = bpy.data.objects.new(name=f"Make3DCam_{target.name if target else 'Scene'}", object_data=cam_data)
    scene.collection.objects.link(cam_obj)
    try:
        cam_obj.matrix_world = region_3d.view_matrix.inverted()
        cam_data.type = "PERSP"
        cam_data.lens_unit = "MILLIMETERS"
        cam_data.lens = float(space.lens)
        cam_data.clip_start = float(space.clip_start)
        cam_data.clip_end = float(space.clip_end)

        fit_msg = "scene view settings"
        if target is not None:
            coords_all = get_evaluated_world_vertices(context, target)
            if use_convex_hull:
                coords_sampled = sample_points_for_fit(coords_all, HULL_3D_FIT_SAMPLE_POINTS)
                coords = convex_hull_points(coords_sampled)
                fit_mode = "hull"
            else:
                coords_sampled = sample_points_for_fit(coords_all, MAX_3D_FIT_POINTS)
                coords = coords_sampled
                fit_mode = "sample"

            old_scene_camera = scene.camera
            scene.camera = cam_obj
            try:
                final_span_x, final_span_y = fit_perspective_camera_to_points(
                    context,
                    scene,
                    cam_obj,
                    coords,
                    buffer_pct,
                    rect_ndc=rect_ndc,
                )
            finally:
                scene.camera = old_scene_camera

            world_m = cam_obj.matrix_world.copy()
            cam_obj.parent = target
            cam_obj.matrix_parent_inverse = target.matrix_world.inverted()
            cam_obj.matrix_world = world_m
            fit_msg = (
                f"fitted to {target.name} ({fit_mode} {len(coords)}/{len(coords_all)} pts, buffer {buffer_pct:.2f}%, "
                f"frame span {final_span_x:.3f}x{final_span_y:.3f})"
            )

        scene.camera = cam_obj
        return cam_obj, fit_msg, target
    except Exception:
        if cam_obj and cam_obj.name in bpy.data.objects:
            data = cam_obj.data
            bpy.data.objects.remove(cam_obj, do_unlink=True)
            if data and data.name in bpy.data.cameras:
                bpy.data.cameras.remove(data, do_unlink=True)
        raise


def create_or_update_framing_plane(context, cam_obj, rect_ndc, mesh_parent=None):
    scene = context.scene
    rx0, ry0, rx1, ry1 = rect_ndc
    left, right = min(rx0, rx1), max(rx0, rx1)
    bottom, top = min(ry0, ry1), max(ry0, ry1)

    plane_name = f"FramingPlane_{cam_obj.name}"
    plane = bpy.data.objects.get(plane_name)
    if plane is None or plane.type != "MESH":
        mesh = bpy.data.meshes.new(f"{plane_name}_Mesh")
        plane = bpy.data.objects.new(plane_name, mesh)
        scene.collection.objects.link(plane)

    # Derive plane depth in camera local space. Keep existing depth on updates,
    # then fall back to DoF focus distance or camera view-frame depth.
    dist = 0.0
    try:
        if plane.data is not None and len(plane.data.vertices) > 0:
            v_world = plane.matrix_world @ plane.data.vertices[0].co
            v_cam = cam_obj.matrix_world.inverted() @ v_world
            if v_cam.z < -1e-6:
                dist = -float(v_cam.z)
    except Exception:
        dist = 0.0
    if dist <= 1e-6:
        focus_dist = float(getattr(cam_obj.data.dof, "focus_distance", 0.0) or 0.0)
        if focus_dist > 1e-6:
            dist = focus_dist
    if dist <= 1e-6:
        frame = cam_obj.data.view_frame(scene=scene)
        z_frame = sum(v.z for v in frame) / max(1, len(frame))
        dist = abs(float(z_frame)) if abs(float(z_frame)) > 1e-6 else 1.0
    dist = max(0.001, dist)

    frame = cam_obj.data.view_frame(scene=scene)
    z_frame = sum(v.z for v in frame) / max(1, len(frame))
    if abs(float(z_frame)) < 1e-9:
        z_frame = -1.0
    scale = (-dist) / float(z_frame)
    fx = [v.x * scale for v in frame]
    fy = [v.y * scale for v in frame]
    fmin_x, fmax_x = min(fx), max(fx)
    fmin_y, fmax_y = min(fy), max(fy)
    full_w = max(1e-6, fmax_x - fmin_x)
    full_h = max(1e-6, fmax_y - fmin_y)

    x0 = fmin_x + left * full_w
    x1 = fmin_x + right * full_w
    y0 = fmin_y + bottom * full_h
    y1 = fmin_y + top * full_h
    z = -dist
    local_verts = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]

    mesh = plane.data
    mesh.clear_geometry()
    mesh.from_pydata(local_verts, [(0, 1), (1, 2), (2, 3), (3, 0)], [(0, 1, 2, 3)])
    mesh.update()

    plane.matrix_world = cam_obj.matrix_world.copy()
    plane.hide_render = True
    plane.display_type = "WIRE"
    plane.show_in_front = True
    plane[FRAMING_PLANE_CAMERA_TAG] = cam_obj.name

    plane_world = plane.matrix_world.copy()
    if mesh_parent is not None and mesh_parent.type == "MESH":
        plane.parent = mesh_parent
        plane.matrix_parent_inverse = mesh_parent.matrix_world.inverted()
    else:
        plane.parent = None
    plane.matrix_world = plane_world

    cam_world = cam_obj.matrix_world.copy()
    cam_obj.parent = plane
    cam_obj.matrix_parent_inverse = plane.matrix_world.inverted()
    cam_obj.matrix_world = cam_world

    return plane


class OBJECT_OT_make_mesh_camera(bpy.types.Operator):
    bl_idname = "object.make_mesh_camera"
    bl_label = "Make 2D Mesh Camera"
    bl_description = "Create an ortho camera aligned to the current viewport and fit to active mesh bounds"
    bl_options = {"REGISTER", "UNDO"}

    parent_to_mesh: BoolProperty(
        name="Parent To Mesh",
        default=True,
    )
    padding_pct: FloatProperty(
        name="Padding %",
        default=0.0,
        min=0.0,
        max=100.0,
    )
    long_edge_px: IntProperty(
        name="Long Edge (px)",
        default=2048,
        min=16,
    )

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and context.region_data is not None
            and context.active_object is not None
            and context.active_object.type == "MESH"
        )

    def execute(self, context):
        obj = context.active_object
        region = context.region
        region_3d = context.region_data

        if region is None or region.width <= 0 or region.height <= 0:
            self.report({"ERROR"}, "Invalid 3D viewport region.")
            return {"CANCELLED"}

        cam_obj = choose_paired_camera(context.scene, obj)
        created_new = cam_obj is None
        if created_new:
            cam_data = bpy.data.cameras.new(name=f"MakeMeshCamData_{obj.name}")
            cam_obj = bpy.data.objects.new(name=f"MakeMeshCam_{obj.name}", object_data=cam_data)
            context.scene.collection.objects.link(cam_obj)
        else:
            cam_data = cam_obj.data
        base_matrix = region_3d.view_matrix.inverted()

        cam_obj.matrix_world = base_matrix
        chosen_label = "viewport"

        try:
            span_x, span_y, res_x, res_y = fit_camera_to_mesh(
                context,
                obj,
                cam_obj,
                self.long_edge_px,
                self.padding_pct,
            )
        except ValueError as exc:
            if created_new:
                bpy.data.objects.remove(cam_obj, do_unlink=True)
                bpy.data.cameras.remove(cam_data, do_unlink=True)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        if self.parent_to_mesh:
            world_m = cam_obj.matrix_world.copy()
            cam_obj.parent = obj
            cam_obj.matrix_parent_inverse = obj.matrix_world.inverted()
            cam_obj.matrix_world = world_m

        cam_obj[PAIR_TAG] = obj.name
        cam_obj[PAIR_RES_X] = int(res_x)
        cam_obj[PAIR_RES_Y] = int(res_y)
        obj[PAIR_CAM_NAME] = cam_obj.name
        context.scene.camera = cam_obj
        apply_scene_resolution_from_camera(context.scene, cam_obj)
        print(
            "MAKE_MESH_CAMERA_OK",
            cam_obj.name,
            f"created_new={created_new}",
            f"orientation={chosen_label}",
            f"ortho={cam_data.ortho_scale:.4f}",
            f"span=({span_x:.4f},{span_y:.4f})",
            f"res=({res_x}x{res_y})",
        )
        self.report(
            {"INFO"},
            (
                f"{'Created' if created_new else 'Updated'} {cam_obj.name} | orientation={chosen_label} | ortho_scale={cam_data.ortho_scale:.4f} "
                f"| span=({span_x:.4f}, {span_y:.4f}) | res=({res_x}x{res_y})"
            ),
        )
        return {"FINISHED"}


class VIEW3D_PT_make_mesh_camera_2d(bpy.types.Panel):
    bl_label = "2D Mesh Camera"
    bl_idname = "VIEW3D_PT_make_mesh_camera_2d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "No3d Cam"

    def draw(self, context):
        layout = self.layout
        layout.operator("object.make_mesh_camera", icon="CAMERA_DATA")
        layout.operator("object.refresh_mesh_camera", icon="FILE_REFRESH")


class VIEW3D_PT_make_mesh_camera_3d(bpy.types.Panel):
    bl_label = "3D Mesh Camera"
    bl_idname = "VIEW3D_PT_make_mesh_camera_3d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "No3d Cam"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, SCENE_3D_BUFFER_PCT, text="3D Boundary Buffer %")
        layout.prop(scene, SCENE_3D_USE_CONVEX_HULL, text="Use Convex Hull Fast Fit?")
        layout.operator("object.make_3d_mesh_camera", icon="VIEW_CAMERA")
        try:
            layout.operator("object.make_3d_mesh_camera_marquee", icon="VIEWZOOM")
        except Exception:
            pass


class VIEW3D_PT_make_mesh_camera_3d_framing_plane(bpy.types.Panel):
    bl_label = "3D Framing Plane"
    bl_idname = "VIEW3D_PT_make_mesh_camera_3d_framing_plane"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "No3d Cam"

    def draw(self, context):
        layout = self.layout
        layout.operator("object.make_3d_framing_plane_marquee", icon="SELECT_SET")
        layout.operator("object.refresh_3d_camera_from_plane", icon="FILE_REFRESH")


class VIEW3D_PT_make_mesh_camera_render(bpy.types.Panel):
    bl_label = "Mesh Camera Render"
    bl_idname = "VIEW3D_PT_make_mesh_camera_render"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "No3d Cam"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.separator()
        layout.prop(scene, SCENE_OUTPUT_PATH, text="Output Path")
        layout.prop(scene, SCENE_USE_FILENAME_MACRO, text="Use filename macro mode")
        macro_row = layout.row()
        macro_row.active = bool(getattr(scene, SCENE_USE_FILENAME_MACRO, False))
        macro_row.prop(scene, SCENE_FILENAME_TEMPLATE, text="Filename Template")
        layout.prop(scene, SCENE_KEEP_CAMERA, text="Keep Camera?")
        layout.prop(scene, SCENE_HIDE_ALL_ELSE, text="Hide All Else?")
        layout.prop(scene, SCENE_COPY_CLIPBOARD, text="Copy image to clipboard")
        layout.prop(scene, SCENE_COPY_OBSIDIAN, text="Copy image to Obsidian assets")
        layout.operator("object.one_shot_selected_mesh", icon="PLAY")
        layout.operator("object.render_mesh_camera", icon="RENDER_STILL")
        layout.operator("object.render_active_3d_camera", icon="RENDER_ANIMATION")


class VIEW3D_MT_hanuman_mesh_camera_pie(bpy.types.Menu):
    bl_label = "Hanuman Mesh Camera Pie"
    bl_idname = "VIEW3D_MT_hanuman_mesh_camera_pie"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()
        prefs = get_addon_prefs(context)
        direction_map = build_pie_direction_map(prefs)

        draw_order = (
            "WEST",
            "EAST",
            "SOUTH",
            "NORTH",
            "NORTH_WEST",
            "NORTH_EAST",
            "SOUTH_WEST",
            "SOUTH_EAST",
        )
        action_meta = {aid: (label, op, icon) for aid, label, op, icon in PIE_ACTIONS}

        for direction in draw_order:
            info = direction_map.get(direction)
            if not info:
                pie.separator()
                continue
            action_id, op_id, _icon = info
            label, _op_id, icon = action_meta[action_id]
            pie.operator(op_id, text=label, icon=icon)


class WM_OT_hanuman_apply_pie_hotkey(bpy.types.Operator):
    bl_idname = "wm.hanuman_apply_pie_hotkey"
    bl_label = "Apply Pie Hotkey"
    bl_description = "Apply updated pie hotkey and layout settings"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        unregister_pie_keymap()
        register_pie_keymap()
        self.report({"INFO"}, "Updated Hanuman pie menu hotkey")
        return {"FINISHED"}


class OBJECT_OT_refresh_mesh_camera(bpy.types.Operator):
    bl_idname = "object.refresh_mesh_camera"
    bl_label = "Refresh 2D Mesh Camera"
    bl_description = "Refit existing Make 2D Mesh Camera bounds to the active mesh after geometry changes"
    bl_options = {"REGISTER", "UNDO"}

    padding_pct: FloatProperty(
        name="Padding %",
        default=0.0,
        min=0.0,
        max=100.0,
    )
    long_edge_px: IntProperty(
        name="Long Edge (px)",
        default=2048,
        min=16,
    )

    @classmethod
    def poll(cls, context):
        return (
            context.active_object is not None
            and context.active_object.type == "MESH"
        )

    def execute(self, context):
        obj = context.active_object
        scene = context.scene
        cam_obj = choose_paired_camera(scene, obj)

        if cam_obj is None:
            self.report(
                {"ERROR"},
                f"No camera paired to selected mesh '{obj.name}'. Run 'Make 2D Mesh Camera' on this mesh first.",
            )
            return {"CANCELLED"}

        try:
            span_x, span_y, res_x, res_y = fit_camera_to_mesh(
                context,
                obj,
                cam_obj,
                self.long_edge_px,
                self.padding_pct,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        cam_obj[PAIR_TAG] = obj.name
        cam_obj[PAIR_RES_X] = int(res_x)
        cam_obj[PAIR_RES_Y] = int(res_y)
        obj[PAIR_CAM_NAME] = cam_obj.name
        scene.camera = cam_obj
        apply_scene_resolution_from_camera(scene, cam_obj)
        print(
            "REFRESH_MESH_CAMERA_OK",
            cam_obj.name,
            f"ortho={cam_obj.data.ortho_scale:.4f}",
            f"span=({span_x:.4f},{span_y:.4f})",
            f"res=({res_x}x{res_y})",
        )
        self.report(
            {"INFO"},
            (
                f"Refreshed {cam_obj.name} | ortho_scale={cam_obj.data.ortho_scale:.4f} "
                f"| span=({span_x:.4f}, {span_y:.4f}) | res=({res_x}x{res_y})"
            ),
        )
        return {"FINISHED"}


class OBJECT_OT_render_mesh_camera(bpy.types.Operator):
    bl_idname = "object.render_mesh_camera"
    bl_label = "Render Mesh Camera"
    bl_description = "Render from camera paired to selected mesh and save PNG"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return (
            context.active_object is not None
            and context.active_object.type == "MESH"
        )

    def execute(self, context):
        obj = context.active_object
        scene = context.scene
        cam_obj = choose_paired_camera(scene, obj)
        if cam_obj is None:
            self.report(
                {"ERROR"},
                f"No camera paired to selected mesh '{obj.name}'. Run 'Make 2D Mesh Camera' first.",
            )
            return {"CANCELLED"}

        out_path = resolve_render_output_path(scene, obj.name, cam_obj.name)

        copy_to_clipboard = bool(getattr(scene, SCENE_COPY_CLIPBOARD, False))
        copy_to_obsidian = bool(getattr(scene, SCENE_COPY_OBSIDIAN, False))
        hide_all_else = bool(getattr(scene, SCENE_HIDE_ALL_ELSE, True))

        old_camera = scene.camera
        old_hide_render = snapshot_hide_render(scene)
        old_render = {
            "resolution_x": scene.render.resolution_x,
            "resolution_y": scene.render.resolution_y,
            "resolution_percentage": scene.render.resolution_percentage,
            "filepath": scene.render.filepath,
            "image_format": scene.render.image_settings.file_format,
            "color_mode": scene.render.image_settings.color_mode,
            "color_depth": scene.render.image_settings.color_depth,
        }

        try:
            scene.camera = cam_obj
            apply_scene_resolution_from_camera(scene, cam_obj)
            if hide_all_else:
                hide_all_else_for_mesh(scene, obj)
            scene.render.filepath = out_path
            scene.render.image_settings.file_format = "PNG"
            scene.render.image_settings.color_mode = "RGBA"

            bpy.ops.render.render(write_still=True)

            if copy_to_clipboard:
                ok, msg = copy_png_to_clipboard(out_path)
                if not ok:
                    self.report({"WARNING"}, f"Rendered, but clipboard copy failed: {msg}")
                else:
                    self.report({"INFO"}, "Rendered and copied image to clipboard.")

            if copy_to_obsidian:
                ok, msg, obsidian_path = copy_render_to_obsidian(context, out_path, obj.name, cam_obj.name)
                if not ok:
                    self.report({"WARNING"}, f"Rendered, but Obsidian copy failed: {msg}")
                else:
                    print("RENDER_MESH_CAMERA_OBSIDIAN_COPY_OK", obsidian_path)
                    self.report({"INFO"}, f"Copied render to Obsidian assets: {obsidian_path}")

            print(
                "RENDER_MESH_CAMERA_OK",
                f"mesh={obj.name}",
                f"camera={cam_obj.name}",
                f"path={out_path}",
            )
            self.report({"INFO"}, f"Rendered {obj.name} via {cam_obj.name} to {out_path}")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Render failed: {exc}")
            return {"CANCELLED"}
        finally:
            scene.camera = old_camera
            scene.render.resolution_x = old_render["resolution_x"]
            scene.render.resolution_y = old_render["resolution_y"]
            scene.render.resolution_percentage = old_render["resolution_percentage"]
            scene.render.filepath = old_render["filepath"]
            scene.render.image_settings.file_format = old_render["image_format"]
            scene.render.image_settings.color_mode = old_render["color_mode"]
            scene.render.image_settings.color_depth = old_render["color_depth"]
            restore_hide_render(scene, old_hide_render)


class OBJECT_OT_render_active_3d_camera(bpy.types.Operator):
    bl_idname = "object.render_active_3d_camera"
    bl_label = "Render Active 3D Camera"
    bl_description = "Render from scene active camera without requiring mesh selection"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.scene.camera is not None

    def execute(self, context):
        scene = context.scene
        cam_obj = scene.camera
        if cam_obj is None or cam_obj.type != "CAMERA":
            self.report({"ERROR"}, "Scene has no active camera.")
            return {"CANCELLED"}

        mesh_name = "scene"
        mesh_obj = None
        tagged_name = cam_obj.get(PAIR_TAG)
        if tagged_name and tagged_name in bpy.data.objects:
            cand = bpy.data.objects[tagged_name]
            if cand.type == "MESH":
                mesh_obj = cand
                mesh_name = cand.name
        elif cam_obj.parent is not None and cam_obj.parent.type == "MESH":
            mesh_obj = cam_obj.parent
            mesh_name = mesh_obj.name

        out_path = resolve_render_output_path(scene, mesh_name, cam_obj.name)
        copy_to_clipboard = bool(getattr(scene, SCENE_COPY_CLIPBOARD, False))
        copy_to_obsidian = bool(getattr(scene, SCENE_COPY_OBSIDIAN, False))
        hide_all_else = bool(getattr(scene, SCENE_HIDE_ALL_ELSE, True))

        old_camera = scene.camera
        old_hide_render = snapshot_hide_render(scene)
        old_render = {
            "resolution_x": scene.render.resolution_x,
            "resolution_y": scene.render.resolution_y,
            "resolution_percentage": scene.render.resolution_percentage,
            "filepath": scene.render.filepath,
            "image_format": scene.render.image_settings.file_format,
            "color_mode": scene.render.image_settings.color_mode,
            "color_depth": scene.render.image_settings.color_depth,
        }

        try:
            scene.camera = cam_obj
            apply_scene_resolution_from_camera(scene, cam_obj)
            if hide_all_else and mesh_obj is not None:
                hide_all_else_for_mesh(scene, mesh_obj)
            scene.render.filepath = out_path
            scene.render.image_settings.file_format = "PNG"
            scene.render.image_settings.color_mode = "RGBA"

            bpy.ops.render.render(write_still=True)

            if copy_to_clipboard:
                ok, msg = copy_png_to_clipboard(out_path)
                if not ok:
                    self.report({"WARNING"}, f"Rendered, but clipboard copy failed: {msg}")
                else:
                    self.report({"INFO"}, "Rendered and copied image to clipboard.")

            if copy_to_obsidian:
                ok, msg, obsidian_path = copy_render_to_obsidian(context, out_path, mesh_name, cam_obj.name)
                if not ok:
                    self.report({"WARNING"}, f"Rendered, but Obsidian copy failed: {msg}")
                else:
                    print("RENDER_ACTIVE_3D_CAMERA_OBSIDIAN_COPY_OK", obsidian_path)
                    self.report({"INFO"}, f"Copied render to Obsidian assets: {obsidian_path}")

            print(
                "RENDER_ACTIVE_3D_CAMERA_OK",
                f"camera={cam_obj.name}",
                f"mesh_ref={mesh_name}",
                f"path={out_path}",
            )
            self.report({"INFO"}, f"Rendered active camera {cam_obj.name} to {out_path}")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Render active 3D camera failed: {exc}")
            return {"CANCELLED"}
        finally:
            scene.camera = old_camera
            scene.render.resolution_x = old_render["resolution_x"]
            scene.render.resolution_y = old_render["resolution_y"]
            scene.render.resolution_percentage = old_render["resolution_percentage"]
            scene.render.filepath = old_render["filepath"]
            scene.render.image_settings.file_format = old_render["image_format"]
            scene.render.image_settings.color_mode = old_render["color_mode"]
            scene.render.image_settings.color_depth = old_render["color_depth"]
            restore_hide_render(scene, old_hide_render)


class OBJECT_OT_one_shot_selected_mesh(bpy.types.Operator):
    bl_idname = "object.one_shot_selected_mesh"
    bl_label = "One-Shot Selected Mesh(es)"
    bl_description = "Create/fit camera for selected mesh, render once, optionally keep camera"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        has_mesh_selection = any(o.type == "MESH" for o in context.selected_objects)
        has_active_mesh = context.active_object is not None and context.active_object.type == "MESH"
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and context.region_data is not None
            and (has_mesh_selection or has_active_mesh)
        )

    def execute(self, context):
        scene = context.scene
        keep_camera = bool(getattr(scene, SCENE_KEEP_CAMERA, True))
        copy_to_clipboard = bool(getattr(scene, SCENE_COPY_CLIPBOARD, False))
        copy_to_obsidian = bool(getattr(scene, SCENE_COPY_OBSIDIAN, False))
        use_macro = bool(getattr(scene, SCENE_USE_FILENAME_MACRO, False))
        hide_all_else = bool(getattr(scene, SCENE_HIDE_ALL_ELSE, True))

        old_camera = scene.camera
        old_active = context.view_layer.objects.active
        old_selected = [o for o in context.selected_objects]
        old_hide_render = snapshot_hide_render(scene)
        old_render = {
            "resolution_x": scene.render.resolution_x,
            "resolution_y": scene.render.resolution_y,
            "resolution_percentage": scene.render.resolution_percentage,
            "filepath": scene.render.filepath,
            "image_format": scene.render.image_settings.file_format,
            "color_mode": scene.render.image_settings.color_mode,
            "color_depth": scene.render.image_settings.color_depth,
        }

        selected_meshes = [o for o in context.selected_objects if o.type == "MESH"]
        if not selected_meshes and context.active_object and context.active_object.type == "MESH":
            selected_meshes = [context.active_object]
        if not selected_meshes:
            self.report({"ERROR"}, "Select at least one mesh object.")
            return {"CANCELLED"}

        def output_path_for(mesh_name, cam_name, index):
            if use_macro:
                return resolve_render_output_path(scene, mesh_name, cam_name)
            base = bpy.path.abspath(getattr(scene, SCENE_OUTPUT_PATH, DEFAULT_RENDER_PATH)) or DEFAULT_RENDER_PATH
            if not base.lower().endswith(".png"):
                base += ".png"
            if len(selected_meshes) == 1:
                return base
            root, ext = os.path.splitext(base)
            return f"{root}_{index:02d}_{safe_filename_part(mesh_name)}{ext or '.png'}"

        temp_cameras = []
        ok_count = 0
        fail_count = 0

        try:
            base_matrix = context.region_data.view_matrix.inverted()
            for index, obj in enumerate(selected_meshes, start=1):
                cam_obj = None
                cam_data = None
                camera_created = False
                camera_is_temp = False
                out_path = ""
                try:
                    if keep_camera:
                        cam_obj = choose_paired_camera(scene, obj)
                        camera_created = cam_obj is None
                        if camera_created:
                            cam_data = bpy.data.cameras.new(name=f"MakeMeshCamData_{obj.name}")
                            cam_obj = bpy.data.objects.new(name=f"MakeMeshCam_{obj.name}", object_data=cam_data)
                            scene.collection.objects.link(cam_obj)
                        else:
                            cam_data = cam_obj.data
                    else:
                        cam_data = bpy.data.cameras.new(name=f"__TMP_OneShotCamData_{obj.name}")
                        cam_obj = bpy.data.objects.new(name=f"__TMP_OneShotCam_{obj.name}", object_data=cam_data)
                        scene.collection.objects.link(cam_obj)
                        camera_created = True
                        camera_is_temp = True
                        temp_cameras.append(cam_obj)

                    cam_obj.matrix_world = base_matrix
                    span_x, span_y, res_x, res_y = fit_camera_to_mesh(
                        context,
                        obj,
                        cam_obj,
                        2048,
                        0.0,
                    )

                    if keep_camera:
                        world_m = cam_obj.matrix_world.copy()
                        cam_obj.parent = obj
                        cam_obj.matrix_parent_inverse = obj.matrix_world.inverted()
                        cam_obj.matrix_world = world_m
                        cam_obj[PAIR_TAG] = obj.name
                        cam_obj[PAIR_RES_X] = int(res_x)
                        cam_obj[PAIR_RES_Y] = int(res_y)
                        obj[PAIR_CAM_NAME] = cam_obj.name
                    else:
                        cam_obj.parent = None

                    out_path = output_path_for(obj.name, cam_obj.name, index)

                    scene.camera = cam_obj
                    scene.render.resolution_x = int(res_x)
                    scene.render.resolution_y = int(res_y)
                    scene.render.resolution_percentage = 100
                    if hide_all_else:
                        hide_all_else_for_mesh(scene, obj)
                    scene.render.filepath = out_path
                    scene.render.image_settings.file_format = "PNG"
                    scene.render.image_settings.color_mode = "RGBA"

                    bpy.ops.render.render(write_still=True)

                    if copy_to_clipboard:
                        ok, msg = copy_png_to_clipboard(out_path)
                        if not ok:
                            self.report({"WARNING"}, f"[{obj.name}] clipboard copy failed: {msg}")

                    if copy_to_obsidian:
                        ok, msg, obsidian_path = copy_render_to_obsidian(context, out_path, obj.name, cam_obj.name)
                        if not ok:
                            self.report({"WARNING"}, f"[{obj.name}] Obsidian copy failed: {msg}")
                        else:
                            print("ONE_SHOT_OBSIDIAN_COPY_OK", obsidian_path)

                    print(
                        "ONE_SHOT_SELECTED_MESH_OK",
                        f"mesh={obj.name}",
                        f"camera={cam_obj.name}",
                        f"keep_camera={keep_camera}",
                        f"created_new={camera_created}",
                        f"res=({res_x}x{res_y})",
                        f"path={out_path}",
                    )
                    ok_count += 1
                except Exception as exc:
                    fail_count += 1
                    self.report({"WARNING"}, f"One-shot failed for '{obj.name}': {exc}")
                    print("ONE_SHOT_SELECTED_MESH_ERROR", f"mesh={obj.name}", repr(exc))
                finally:
                    if camera_is_temp and cam_obj and cam_obj.name in bpy.data.objects:
                        data = cam_obj.data
                        bpy.data.objects.remove(cam_obj, do_unlink=True)
                        if data and data.name in bpy.data.cameras:
                            bpy.data.cameras.remove(data, do_unlink=True)

            if ok_count == 0:
                self.report({"ERROR"}, "One-shot failed for all selected meshes.")
                return {"CANCELLED"}
            if fail_count > 0:
                self.report({"WARNING"}, f"One-shot complete: {ok_count} succeeded, {fail_count} failed.")
            else:
                self.report({"INFO"}, f"One-shot complete: {ok_count} mesh(es) rendered.")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"One-shot failed: {exc}")
            return {"CANCELLED"}
        finally:
            scene.camera = old_camera
            scene.render.resolution_x = old_render["resolution_x"]
            scene.render.resolution_y = old_render["resolution_y"]
            scene.render.resolution_percentage = old_render["resolution_percentage"]
            scene.render.filepath = old_render["filepath"]
            scene.render.image_settings.file_format = old_render["image_format"]
            scene.render.image_settings.color_mode = old_render["color_mode"]
            scene.render.image_settings.color_depth = old_render["color_depth"]
            restore_hide_render(scene, old_hide_render)
            try:
                bpy.ops.object.select_all(action="DESELECT")
                for o in old_selected:
                    if o and o.name in bpy.data.objects:
                        o.select_set(True)
                if old_active and old_active.name in bpy.data.objects:
                    context.view_layer.objects.active = old_active
            except Exception:
                pass


class OBJECT_OT_make_3d_mesh_camera(bpy.types.Operator):
    bl_idname = "object.make_3d_mesh_camera"
    bl_label = "Make 3D Mesh Camera"
    bl_description = (
        "Create perspective camera from current viewport; if mesh selected, fit frame to it and optionally parent"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and context.region_data is not None
            and context.space_data is not None
            and context.space_data.type == "VIEW_3D"
        )

    def execute(self, context):
        try:
            cam_obj, fit_msg, target = create_3d_camera_from_view(context, rect_ndc=None)
            if context.region_data is not None:
                context.region_data.view_perspective = "CAMERA"
            print(
                "MAKE_3D_MESH_CAMERA_OK",
                cam_obj.name,
                f"target={target.name if target else 'None'}",
                f"lens={cam_obj.data.lens}",
                f"clip=({cam_obj.data.clip_start},{cam_obj.data.clip_end})",
                fit_msg,
            )
            self.report({"INFO"}, f"Created {cam_obj.name} ({fit_msg})")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Make 3D Mesh Camera failed: {exc}")
            return {"CANCELLED"}


class OBJECT_OT_make_3d_mesh_camera_marquee(bpy.types.Operator):
    bl_idname = "object.make_3d_mesh_camera_marquee"
    bl_label = "Make 3D Mesh Camera (Marquee)"
    bl_description = "Draw a viewport marquee to set exact camera boundaries from current view"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and context.region_data is not None
            and context.space_data is not None
            and context.space_data.type == "VIEW_3D"
        )

    def _remove_draw_handler(self):
        if getattr(self, "_draw_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, "WINDOW")
            self._draw_handle = None

    def _draw_callback(self, context):
        if not getattr(self, "_dragging", False):
            return
        x0, y0 = self._start
        x1, y1 = self._end
        left, right = min(x0, x1), max(x0, x1)
        bottom, top = min(y0, y1), max(y0, y1)
        try:
            import gpu
            from gpu_extras.batch import batch_for_shader

            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            verts = [(left, bottom), (right, bottom), (right, top), (left, top)]
            lines = [(verts[0], verts[1]), (verts[1], verts[2]), (verts[2], verts[3]), (verts[3], verts[0])]
            batch = batch_for_shader(shader, "LINES", {"pos": [v for seg in lines for v in seg]})
            shader.bind()
            shader.uniform_float("color", (1.0, 0.85, 0.2, 1.0))
            batch.draw(shader)
        except Exception:
            pass

    def invoke(self, context, event):
        self._start = (event.mouse_region_x, event.mouse_region_y)
        self._end = self._start
        self._dragging = False
        self._region_width = context.region.width
        self._region_height = context.region.height
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback,
            (context,),
            "WINDOW",
            "POST_PIXEL",
        )
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        self.report({"INFO"}, "Drag marquee in viewport, release to create 3D camera. Esc to cancel.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._remove_draw_handler()
            context.area.tag_redraw()
            self.report({"INFO"}, "Marquee camera creation cancelled.")
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self._start = (event.mouse_region_x, event.mouse_region_y)
            self._end = self._start
            self._dragging = True
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE" and self._dragging:
            self._end = (event.mouse_region_x, event.mouse_region_y)
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE" and self._dragging:
            self._dragging = False
            x0, y0 = self._start
            x1, y1 = self._end
            left, right = sorted((x0, x1))
            bottom, top = sorted((y0, y1))
            min_size = 8
            if (right - left) < min_size or (top - bottom) < min_size:
                self._remove_draw_handler()
                context.area.tag_redraw()
                self.report({"ERROR"}, "Marquee too small. Drag a larger rectangle.")
                return {"CANCELLED"}

            rw = max(1, self._region_width)
            rh = max(1, self._region_height)
            rect_ndc = (
                max(0.0, min(1.0, left / rw)),
                max(0.0, min(1.0, bottom / rh)),
                max(0.0, min(1.0, right / rw)),
                max(0.0, min(1.0, top / rh)),
            )

            try:
                cam_obj, fit_msg, target = create_3d_camera_from_view(context, rect_ndc=rect_ndc)
                if context.region_data is not None:
                    context.region_data.view_perspective = "CAMERA"
                print(
                    "MAKE_3D_MESH_CAMERA_MARQUEE_OK",
                    cam_obj.name,
                    f"target={target.name if target else 'None'}",
                    f"lens={cam_obj.data.lens}",
                    f"clip=({cam_obj.data.clip_start},{cam_obj.data.clip_end})",
                    fit_msg,
                    f"rect_ndc={rect_ndc}",
                )
                self.report({"INFO"}, f"Created {cam_obj.name} from marquee ({fit_msg})")
                result = {"FINISHED"}
            except Exception as exc:
                self.report({"ERROR"}, f"Marquee 3D camera failed: {exc}")
                result = {"CANCELLED"}

            self._remove_draw_handler()
            context.area.tag_redraw()
            return result

        return {"RUNNING_MODAL"}


class OBJECT_OT_make_3d_framing_plane_marquee(bpy.types.Operator):
    bl_idname = "object.make_3d_framing_plane_marquee"
    bl_label = "Draw 3D Framing Plane"
    bl_description = "Draw marquee and create editable wireframe framing plane for active camera"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and context.region_data is not None
            and context.space_data is not None
            and context.space_data.type == "VIEW_3D"
            and context.scene is not None
        )

    def _remove_draw_handler(self):
        if getattr(self, "_draw_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, "WINDOW")
            self._draw_handle = None

    def _draw_callback(self, context):
        if not getattr(self, "_dragging", False):
            return
        x0, y0 = self._start
        x1, y1 = self._end
        left, right = min(x0, x1), max(x0, x1)
        bottom, top = min(y0, y1), max(y0, y1)
        try:
            import gpu
            from gpu_extras.batch import batch_for_shader

            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            verts = [(left, bottom), (right, bottom), (right, top), (left, top)]
            lines = [(verts[0], verts[1]), (verts[1], verts[2]), (verts[2], verts[3]), (verts[3], verts[0])]
            batch = batch_for_shader(shader, "LINES", {"pos": [v for seg in lines for v in seg]})
            shader.bind()
            shader.uniform_float("color", (0.2, 0.9, 1.0, 1.0))
            batch.draw(shader)
        except Exception:
            pass

    def invoke(self, context, event):
        target = get_selected_mesh_target(context)
        self._target_name = target.name if target is not None else ""

        # Create a fresh camera immediately so placement is fixed before marquee draw.
        cam_data = bpy.data.cameras.new(name="Make3DCamData_Scene")
        cam_obj = bpy.data.objects.new(name="Make3DCam_Scene", object_data=cam_data)
        context.scene.collection.objects.link(cam_obj)
        cam_obj.matrix_world = context.region_data.view_matrix.inverted()
        cam_data.type = "PERSP"
        cam_data.lens_unit = "MILLIMETERS"
        cam_data.lens = float(context.space_data.lens)
        cam_data.clip_start = float(context.space_data.clip_start)
        cam_data.clip_end = float(context.space_data.clip_end)
        context.scene.camera = cam_obj
        self._camera_name = cam_obj.name

        self._start = (event.mouse_region_x, event.mouse_region_y)
        self._end = self._start
        self._dragging = False
        self._region_width = context.region.width
        self._region_height = context.region.height
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback,
            (context,),
            "WINDOW",
            "POST_PIXEL",
        )
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        self.report(
            {"INFO"},
            f"Created {cam_obj.name}. Target locked: {self._target_name or 'None'}. "
            "Drag marquee to create framing plane. Esc to cancel.",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._remove_draw_handler()
            context.area.tag_redraw()
            self.report({"INFO"}, "Framing plane marquee cancelled.")
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self._start = (event.mouse_region_x, event.mouse_region_y)
            self._end = self._start
            self._dragging = True
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE" and self._dragging:
            self._end = (event.mouse_region_x, event.mouse_region_y)
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE" and self._dragging:
            self._dragging = False
            x0, y0 = self._start
            x1, y1 = self._end
            left, right = sorted((x0, x1))
            bottom, top = sorted((y0, y1))
            min_size = 8
            if (right - left) < min_size or (top - bottom) < min_size:
                self._remove_draw_handler()
                context.area.tag_redraw()
                self.report({"ERROR"}, "Marquee too small. Drag a larger rectangle.")
                return {"CANCELLED"}

            rw = max(1, self._region_width)
            rh = max(1, self._region_height)
            rect_ndc = (
                max(0.0, min(1.0, left / rw)),
                max(0.0, min(1.0, bottom / rh)),
                max(0.0, min(1.0, right / rw)),
                max(0.0, min(1.0, top / rh)),
            )
            rect_aspect = max(1e-6, (rect_ndc[2] - rect_ndc[0])) / max(1e-6, (rect_ndc[3] - rect_ndc[1]))

            try:
                cam_obj = bpy.data.objects.get(getattr(self, "_camera_name", ""))
                if cam_obj is None or cam_obj.type != "CAMERA":
                    self.report({"ERROR"}, "Working camera missing. Retry drawing framing plane.")
                    self._remove_draw_handler()
                    context.area.tag_redraw()
                    return {"CANCELLED"}
                res_x, res_y = set_camera_resolution_from_aspect(cam_obj, rect_aspect)
                apply_scene_resolution_from_camera(context.scene, cam_obj)

                target = None
                locked_name = getattr(self, "_target_name", "")
                if locked_name and locked_name in bpy.data.objects:
                    cand = bpy.data.objects[locked_name]
                    if cand.type == "MESH":
                        target = cand
                if target is None:
                    target = get_selected_mesh_target(context)
                fit_msg = "scene view settings"
                if target is not None:
                    buffer_pct = max(0.0, float(getattr(context.scene, SCENE_3D_BUFFER_PCT, 5.0)))
                    use_convex_hull = bool(getattr(context.scene, SCENE_3D_USE_CONVEX_HULL, False))
                    coords_all = get_evaluated_world_vertices(context, target)
                    if use_convex_hull:
                        coords_sampled = sample_points_for_fit(coords_all, HULL_3D_FIT_SAMPLE_POINTS)
                        coords = convex_hull_points(coords_sampled)
                        fit_mode = "hull"
                    else:
                        coords_sampled = sample_points_for_fit(coords_all, MAX_3D_FIT_POINTS)
                        coords = coords_sampled
                        fit_mode = "sample"

                    old_scene_camera = context.scene.camera
                    context.scene.camera = cam_obj
                    try:
                        span_x, span_y = fit_perspective_camera_to_points(
                            context,
                            context.scene,
                            cam_obj,
                            coords,
                            buffer_pct,
                            rect_ndc=rect_ndc,
                            set_aspect=False,
                        )
                    finally:
                        context.scene.camera = old_scene_camera

                    fit_msg = (
                        f"fitted to {target.name} ({fit_mode} {len(coords)}/{len(coords_all)} pts, "
                        f"buffer {buffer_pct:.2f}%, frame span {span_x:.3f}x{span_y:.3f})"
                    )
                    cam_obj[PAIR_TAG] = target.name
                    target[PAIR_CAM_NAME] = cam_obj.name

                plane = create_or_update_framing_plane(context, cam_obj, rect_ndc, mesh_parent=target)
                bpy.ops.object.select_all(action="DESELECT")
                plane.select_set(True)
                context.view_layer.objects.active = plane
                context.region_data.view_perspective = "CAMERA"
                print(
                    "MAKE_3D_FRAMING_PLANE_OK",
                    f"plane={plane.name}",
                    f"camera={cam_obj.name}",
                    f"plane_parent={plane.parent.name if plane.parent else 'None'}",
                    f"camera_parent={cam_obj.parent.name if cam_obj.parent else 'None'}",
                    f"res=({res_x}x{res_y})",
                    fit_msg,
                    f"rect_ndc={rect_ndc}",
                )
                self.report({"INFO"}, f"Created framing plane {plane.name} for {cam_obj.name}")
                result = {"FINISHED"}
            except Exception as exc:
                self.report({"ERROR"}, f"Framing plane creation failed: {exc}")
                result = {"CANCELLED"}

            self._remove_draw_handler()
            context.area.tag_redraw()
            return result

        return {"RUNNING_MODAL"}


class OBJECT_OT_refresh_3d_camera_from_plane(bpy.types.Operator):
    bl_idname = "object.refresh_3d_camera_from_plane"
    bl_label = "Refresh 3D Camera From Plane"
    bl_description = "Fit linked camera to selected framing plane edits"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context):
        plane = context.active_object
        cam_name = plane.get(FRAMING_PLANE_CAMERA_TAG)
        if not cam_name or cam_name not in bpy.data.objects:
            self.report({"ERROR"}, "Selected mesh is not a linked framing plane.")
            return {"CANCELLED"}
        cam_obj = bpy.data.objects[cam_name]
        if cam_obj.type != "CAMERA":
            self.report({"ERROR"}, "Linked camera is missing or invalid.")
            return {"CANCELLED"}

        try:
            coords = get_evaluated_world_vertices(context, plane)
            old_scene_camera = context.scene.camera
            context.scene.camera = cam_obj
            try:
                span_x, span_y = fit_perspective_camera_to_points(
                    context,
                    context.scene,
                    cam_obj,
                    coords,
                    max(0.0, float(getattr(context.scene, SCENE_3D_BUFFER_PCT, 5.0))),
                    rect_ndc=(0.0, 0.0, 1.0, 1.0),
                    set_aspect=False,
                )
                plane_aspect = camera_local_aspect_from_points(cam_obj, coords)
                res_x, res_y = set_camera_resolution_from_aspect(cam_obj, plane_aspect)
                apply_scene_resolution_from_camera(context.scene, cam_obj)
            finally:
                context.scene.camera = cam_obj
            print(
                "REFRESH_3D_CAMERA_FROM_PLANE_OK",
                f"plane={plane.name}",
                f"camera={cam_obj.name}",
                f"span=({span_x:.3f},{span_y:.3f})",
                f"res=({res_x}x{res_y})",
            )
            self.report({"INFO"}, f"Refreshed {cam_obj.name} from {plane.name}")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Refresh 3D camera failed: {exc}")
            return {"CANCELLED"}


class MESH_CAMERA_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    obsidian_assets_path: bpy.props.StringProperty(
        name="Obsidian Assets Path",
        subtype="DIR_PATH",
        default=DEFAULT_OBSIDIAN_ASSETS_PATH,
        description="Directory used when 'Copy image to Obsidian assets' is enabled",
    )
    pie_hotkey: bpy.props.EnumProperty(
        name="Pie Hotkey",
        items=HOTKEY_TYPES,
        default="E",
    )
    pie_ctrl: bpy.props.BoolProperty(name="Ctrl", default=True)
    pie_shift: bpy.props.BoolProperty(name="Shift", default=True)
    pie_alt: bpy.props.BoolProperty(name="Alt", default=False)

    pie_pos_make_2d: bpy.props.EnumProperty(name="Make 2D", items=PIE_DIRECTIONS, default="WEST")
    pie_pos_refresh_2d: bpy.props.EnumProperty(name="Refresh 2D", items=PIE_DIRECTIONS, default="SOUTH_WEST")
    pie_pos_make_3d: bpy.props.EnumProperty(name="Make 3D", items=PIE_DIRECTIONS, default="EAST")
    pie_pos_make_3d_marquee: bpy.props.EnumProperty(name="Make 3D Marquee", items=PIE_DIRECTIONS, default="NORTH_EAST")
    pie_pos_draw_3d_plane: bpy.props.EnumProperty(name="Draw 3D Plane", items=PIE_DIRECTIONS, default="NORTH")
    pie_pos_refresh_3d_plane: bpy.props.EnumProperty(name="Refresh 3D From Plane", items=PIE_DIRECTIONS, default="NORTH_WEST")
    pie_pos_one_shot: bpy.props.EnumProperty(name="One-Shot", items=PIE_DIRECTIONS, default="SOUTH")
    pie_pos_render_2d: bpy.props.EnumProperty(name="Render 2D", items=PIE_DIRECTIONS, default="SOUTH_EAST")
    pie_pos_render_3d: bpy.props.EnumProperty(name="Render 3D", items=PIE_DIRECTIONS, default="HIDDEN")

    def draw(self, context):
        layout = self.layout
        layout.label(text="Mesh Camera Export")
        layout.prop(self, "obsidian_assets_path")
        layout.separator()
        layout.label(text="Pie Menu Hotkey")
        row = layout.row(align=True)
        row.prop(self, "pie_hotkey", text="Key")
        row.prop(self, "pie_ctrl")
        row.prop(self, "pie_shift")
        row.prop(self, "pie_alt")
        layout.operator("wm.hanuman_apply_pie_hotkey", icon="FILE_REFRESH")
        layout.separator()
        layout.label(text="Pie Menu Slot Mapping")
        for action_id, label, _op, _icon in PIE_ACTIONS:
            layout.prop(self, PIE_ACTION_PROP_MAP[action_id], text=label)


classes = (
    MESH_CAMERA_AddonPreferences,
    VIEW3D_MT_hanuman_mesh_camera_pie,
    WM_OT_hanuman_apply_pie_hotkey,
    OBJECT_OT_make_mesh_camera,
    OBJECT_OT_refresh_mesh_camera,
    OBJECT_OT_make_3d_mesh_camera,
    OBJECT_OT_make_3d_mesh_camera_marquee,
    OBJECT_OT_make_3d_framing_plane_marquee,
    OBJECT_OT_refresh_3d_camera_from_plane,
    OBJECT_OT_render_mesh_camera,
    OBJECT_OT_render_active_3d_camera,
    OBJECT_OT_one_shot_selected_mesh,
    VIEW3D_PT_make_mesh_camera_2d,
    VIEW3D_PT_make_mesh_camera_3d,
    VIEW3D_PT_make_mesh_camera_3d_framing_plane,
    VIEW3D_PT_make_mesh_camera_render,
)


def register():
    # Cleanup legacy panel registrations from older versions.
    for legacy in (
        "VIEW3D_PT_make_mesh_camera",
        "VIEW3D_PT_export_mesh_bounds_png",
    ):
        cls = getattr(bpy.types, legacy, None)
        if cls is not None:
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass

    if not hasattr(bpy.types.Scene, SCENE_OUTPUT_PATH):
        setattr(
            bpy.types.Scene,
            SCENE_OUTPUT_PATH,
            bpy.props.StringProperty(
                name="Mesh Camera Output Path",
                subtype="FILE_PATH",
                default=DEFAULT_RENDER_PATH,
            ),
        )
    if not hasattr(bpy.types.Scene, SCENE_COPY_CLIPBOARD):
        setattr(
            bpy.types.Scene,
            SCENE_COPY_CLIPBOARD,
            bpy.props.BoolProperty(
                name="Copy Mesh Camera Render To Clipboard",
                default=False,
            ),
        )
    if not hasattr(bpy.types.Scene, SCENE_COPY_OBSIDIAN):
        setattr(
            bpy.types.Scene,
            SCENE_COPY_OBSIDIAN,
            bpy.props.BoolProperty(
                name="Copy Mesh Camera Render To Obsidian Assets",
                default=False,
            ),
        )
    if not hasattr(bpy.types.Scene, SCENE_USE_FILENAME_MACRO):
        setattr(
            bpy.types.Scene,
            SCENE_USE_FILENAME_MACRO,
            bpy.props.BoolProperty(
                name="Use Mesh Camera Filename Macro",
                default=False,
            ),
        )
    if not hasattr(bpy.types.Scene, SCENE_FILENAME_TEMPLATE):
        setattr(
            bpy.types.Scene,
            SCENE_FILENAME_TEMPLATE,
            bpy.props.StringProperty(
                name="Mesh Camera Filename Template",
                default="{mesh}_{camera}_{timestamp}.png",
            ),
        )
    if not hasattr(bpy.types.Scene, SCENE_KEEP_CAMERA):
        setattr(
            bpy.types.Scene,
            SCENE_KEEP_CAMERA,
            bpy.props.BoolProperty(
                name="Keep Camera?",
                default=True,
            ),
        )
    if not hasattr(bpy.types.Scene, SCENE_HIDE_ALL_ELSE):
        setattr(
            bpy.types.Scene,
            SCENE_HIDE_ALL_ELSE,
            bpy.props.BoolProperty(
                name="Hide All Else?",
                default=True,
            ),
        )
    if not hasattr(bpy.types.Scene, SCENE_3D_BUFFER_PCT):
        setattr(
            bpy.types.Scene,
            SCENE_3D_BUFFER_PCT,
            bpy.props.FloatProperty(
                name="3D Boundary Buffer %",
                default=5.0,
                min=0.0,
                max=200.0,
            ),
        )
    if not hasattr(bpy.types.Scene, SCENE_3D_USE_CONVEX_HULL):
        setattr(
            bpy.types.Scene,
            SCENE_3D_USE_CONVEX_HULL,
            bpy.props.BoolProperty(
                name="Use Convex Hull Fast Fit?",
                default=False,
            ),
        )
    for cls in classes:
        bpy.utils.register_class(cls)
    register_pie_keymap()


def unregister():
    unregister_pie_keymap()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, SCENE_OUTPUT_PATH):
        delattr(bpy.types.Scene, SCENE_OUTPUT_PATH)
    if hasattr(bpy.types.Scene, SCENE_COPY_CLIPBOARD):
        delattr(bpy.types.Scene, SCENE_COPY_CLIPBOARD)
    if hasattr(bpy.types.Scene, SCENE_COPY_OBSIDIAN):
        delattr(bpy.types.Scene, SCENE_COPY_OBSIDIAN)
    if hasattr(bpy.types.Scene, SCENE_USE_FILENAME_MACRO):
        delattr(bpy.types.Scene, SCENE_USE_FILENAME_MACRO)
    if hasattr(bpy.types.Scene, SCENE_FILENAME_TEMPLATE):
        delattr(bpy.types.Scene, SCENE_FILENAME_TEMPLATE)
    if hasattr(bpy.types.Scene, SCENE_KEEP_CAMERA):
        delattr(bpy.types.Scene, SCENE_KEEP_CAMERA)
    if hasattr(bpy.types.Scene, SCENE_HIDE_ALL_ELSE):
        delattr(bpy.types.Scene, SCENE_HIDE_ALL_ELSE)
    if hasattr(bpy.types.Scene, SCENE_3D_BUFFER_PCT):
        delattr(bpy.types.Scene, SCENE_3D_BUFFER_PCT)
    if hasattr(bpy.types.Scene, SCENE_3D_USE_CONVEX_HULL):
        delattr(bpy.types.Scene, SCENE_3D_USE_CONVEX_HULL)


if __name__ == "__main__":
    try:
        unregister()
    except Exception:
        pass
    register()
