"""
Paste a clipboard image into the scene as a textured plane.

Reads PNG bytes from the macOS clipboard, saves them next to the .blend
(or to ~/Downloads if unsaved), creates a plane sized so its long edge
matches the configured target length (default 50 mm), and assigns a
material with a transparent-alpha image-texture shader.

Shader graph:
    UV Map ──► Image Texture (Closest, sRGB, Straight) ──┬─► Mix Shader factor (Alpha)
                                                          ├─► Mix Shader slot 2 (Color)
                                                          │
              Transparent BSDF ──────────────────────────┴─► Mix Shader slot 1
                                                              ▼
                                                         Material Output
"""

import datetime
import logging
import os
import subprocess
import sys
import tempfile

import bpy
from bpy.types import Operator
from mathutils import Vector

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Clipboard read (macOS)
# ---------------------------------------------------------------------------

def _read_clipboard_png_to_file(out_path: str) -> bool:
    """Write the macOS clipboard's image (if any) to out_path as PNG.

    Returns True on success. Implementation: AppleScript reads the
    clipboard as PNGf and writes raw bytes to a file.
    """
    if sys.platform != "darwin":
        return False

    script = f'''
    set outFile to POSIX file "{out_path}"
    try
        set imgData to the clipboard as «class PNGf»
    on error
        return "NO_IMAGE"
    end try
    try
        set fh to open for access outFile with write permission
        set eof of fh to 0
        write imgData to fh
        close access fh
    on error errMsg
        try
            close access outFile
        end try
        return "WRITE_FAILED: " & errMsg
    end try
    return "OK"
    '''
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=10,
            text=True,
        )
        out = (proc.stdout or "").strip()
        if proc.returncode != 0 or out != "OK":
            log.warning(
                "Clipboard read failed: rc=%s out=%r err=%r",
                proc.returncode, proc.stdout, proc.stderr,
            )
            return False
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception as exc:
        log.warning("Clipboard read exception: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _save_dir() -> str:
    blend = bpy.data.filepath
    if blend:
        return os.path.dirname(blend)
    return os.path.expanduser("~/Downloads")


def _unique_path(directory: str, stem: str, ext: str = ".png") -> str:
    base = os.path.join(directory, f"{stem}{ext}")
    if not os.path.exists(base):
        return base
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return os.path.join(directory, f"{stem}_{stamp}{ext}")


# ---------------------------------------------------------------------------
# Plane + material construction
# ---------------------------------------------------------------------------

def _build_plane_material(name: str, image: bpy.types.Image) -> bpy.types.Material:
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    mat.blend_method = 'BLEND'  # respect alpha in viewport

    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    for n in list(nodes):
        nodes.remove(n)

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)

    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (380, 0)

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (140, 140)

    tex = nodes.new("ShaderNodeTexImage")
    tex.location = (-200, -40)
    tex.image = image
    tex.interpolation = 'Closest'
    tex.projection = 'FLAT'
    tex.extension = 'REPEAT'
    if image.colorspace_settings:
        try:
            image.colorspace_settings.name = 'sRGB'
        except Exception:
            pass
    image.alpha_mode = 'STRAIGHT'

    uv = nodes.new("ShaderNodeUVMap")
    uv.location = (-440, -120)
    uv.uv_map = "UVMap"

    links.new(uv.outputs["UV"], tex.inputs["Vector"])
    links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(tex.outputs["Color"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])

    return mat


def _create_textured_plane(
    context,
    image: bpy.types.Image,
    long_edge_m: float,
    location: Vector,
    rotation_quat,
):
    """Create a plane mesh sized to image aspect, oriented to the view."""
    img_w, img_h = image.size
    if img_w <= 0 or img_h <= 0:
        raise RuntimeError(f"Image has invalid size: {image.size}")

    if img_w >= img_h:
        plane_w = long_edge_m
        plane_h = long_edge_m * (img_h / img_w)
    else:
        plane_h = long_edge_m
        plane_w = long_edge_m * (img_w / img_h)

    half_w = plane_w * 0.5
    half_h = plane_h * 0.5

    mesh = bpy.data.meshes.new(name=f"{image.name}_plane")
    verts = [
        (-half_w, -half_h, 0.0),
        ( half_w, -half_h, 0.0),
        ( half_w,  half_h, 0.0),
        (-half_w,  half_h, 0.0),
    ]
    faces = [(0, 1, 2, 3)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    # UV map: 1:1 with the image, no rotation
    uv_layer = mesh.uv_layers.new(name="UVMap")
    uv_data = uv_layer.data
    # face vertex order is 0,1,2,3 → BL, BR, TR, TL
    uv_data[0].uv = (0.0, 0.0)
    uv_data[1].uv = (1.0, 0.0)
    uv_data[2].uv = (1.0, 1.0)
    uv_data[3].uv = (0.0, 1.0)

    obj = bpy.data.objects.new(name=mesh.name, object_data=mesh)
    obj.location = location
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = rotation_quat
    # leave rotation un-applied per spec

    coll = context.collection or context.scene.collection
    coll.objects.link(obj)

    mat = _build_plane_material(name=f"{image.name}_mat", image=image)
    obj.data.materials.append(mat)

    return obj


def _viewport_view_state(context):
    """Pivot + rotation of the *active* 3D viewport — the one the user
    invoked the operator from. Falls back to the largest 3D viewport in
    the window if context.area isn't a 3D viewport (e.g. invoked via menu
    from a different editor).

    Returns (location: Vector, rotation_quat) or (origin, None).

    rv3d.view_rotation rotates view-space axes into world space. View-space
    +Z points toward the viewer (Blender views look down -Z view), so
    setting obj.rotation_quaternion = view_rotation aligns the mesh's
    local +Z with "toward the viewer" in world.
    """
    def _state(area):
        space = area.spaces.active
        rv3d = getattr(space, "region_3d", None)
        if rv3d is None:
            return None
        return rv3d.view_location.copy(), rv3d.view_rotation.copy()

    # 1) Prefer the area that owns the operator invocation
    area = getattr(context, "area", None)
    if area is not None and area.type == 'VIEW_3D':
        s = _state(area)
        if s:
            return s

    # 2) Otherwise pick the largest 3D viewport in the window
    candidates = [
        a for a in context.window.screen.areas if a.type == 'VIEW_3D'
    ]
    candidates.sort(key=lambda a: a.width * a.height, reverse=True)
    for a in candidates:
        s = _state(a)
        if s:
            return s

    return Vector((0.0, 0.0, 0.0)), None


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class NO3D_OT_paste_clipboard_plane(Operator):
    """Paste a clipboard image as a textured plane in the 3D viewport."""
    bl_idname = "no3d.paste_clipboard_plane"
    bl_label = "Paste Clipboard as Plane"
    bl_description = (
        "Read the system clipboard for an image, save it next to the .blend "
        "(or ~/Downloads if unsaved), and create a textured plane sized to "
        "the configured long edge"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def execute(self, context):
        if sys.platform != "darwin":
            self.report({'ERROR'}, "Clipboard image paste only supported on macOS")
            return {'CANCELLED'}

        # Resolve target file path
        save_dir = _save_dir()
        os.makedirs(save_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        target = _unique_path(save_dir, f"clipboard_paste_{stamp}", ".png")

        # Write to a temp first, then move into place — avoids partial files
        # if osascript fails halfway.
        with tempfile.NamedTemporaryFile(
            prefix="no3d_clip_", suffix=".png", delete=False,
        ) as tmp:
            tmp_path = tmp.name

        try:
            ok = _read_clipboard_png_to_file(tmp_path)
            if not ok:
                self.report(
                    {'ERROR'},
                    "No image on clipboard (or clipboard read failed). "
                    "Copy an image first, then run this again."
                )
                return {'CANCELLED'}
            os.replace(tmp_path, target)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        # Load image into Blender
        try:
            image = bpy.data.images.load(target, check_existing=False)
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to load image: {exc}")
            return {'CANCELLED'}

        # Resolve long-edge size from preferences (value is in millimeters)
        addon = context.preferences.addons.get(__package__)
        long_mm = 50.0
        if addon and hasattr(addon, "preferences"):
            long_mm = float(getattr(addon.preferences, "paste_plane_long_edge_mm", 50.0))

        # Convert mm → scene internal units. Blender internal is always meters,
        # but vertex coords get rendered through scene.unit_settings.scale_length.
        # internal_units = meters / scale_length
        scale_length = context.scene.unit_settings.scale_length or 1.0
        long_m = (long_mm / 1000.0) / scale_length

        # Viewport pose
        view_loc, view_rot = _viewport_view_state(context)
        if view_rot is None:
            from mathutils import Quaternion
            view_rot = Quaternion((1.0, 0.0, 0.0, 0.0))

        try:
            obj = _create_textured_plane(
                context, image, long_m, view_loc, view_rot,
            )
        except Exception as exc:
            log.exception("Plane creation failed")
            self.report({'ERROR'}, f"Plane creation failed: {exc}")
            return {'CANCELLED'}

        # Make the new plane the active selection
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

        msg = (
            f"Pasted {image.size[0]}×{image.size[1]} image as plane "
            f"({long_mm:.1f}mm long edge) — saved to {target}"
        )
        print(f"[no3d_asset_developer] {msg}")
        self.report({'INFO'}, msg)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Orient selected objects' +Z to the viewport
# ---------------------------------------------------------------------------

def _set_object_rotation_quat(obj, quat):
    """Write a quaternion into the object's current rotation mode."""
    mode = obj.rotation_mode
    if mode == 'QUATERNION':
        obj.rotation_quaternion = quat
    elif mode == 'AXIS_ANGLE':
        axis, angle = quat.to_axis_angle()
        obj.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
    else:
        # Euler — preserve the user's chosen order (XYZ, ZYX, etc.)
        obj.rotation_euler = quat.to_euler(mode)


class NO3D_OT_orient_z_to_viewport(Operator):
    """Rotate selected objects so their local +Z faces the viewer."""
    bl_idname = "no3d.orient_z_to_viewport"
    bl_label = "Orient Z to Viewport"
    bl_description = (
        "Rotate every selected object so its local +Z axis points toward "
        "the viewer in the active 3D viewport. Locations are unchanged"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == 'VIEW_3D'
            and len(context.selected_objects) > 0
        )

    def execute(self, context):
        _, view_quat = _viewport_view_state(context)
        if view_quat is None:
            self.report({'ERROR'}, "No 3D viewport found")
            return {'CANCELLED'}

        targets = list(context.selected_objects)
        if not targets:
            self.report({'INFO'}, "Nothing selected")
            return {'CANCELLED'}

        for obj in targets:
            _set_object_rotation_quat(obj, view_quat)

        n = len(targets)
        msg = f"Oriented +Z to viewport on {n} object{'s' if n != 1 else ''}"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Add menu entry
# ---------------------------------------------------------------------------

def _draw_add_menu(self, context):
    self.layout.separator()
    self.layout.operator(
        "no3d.paste_clipboard_plane",
        text="Paste Clipboard as Plane",
        icon='IMAGE_DATA',
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = (
    NO3D_OT_paste_clipboard_plane,
    NO3D_OT_orient_z_to_viewport,
)

_addon_keymaps = []


def _register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")

    # Cmd+Shift+V — paste clipboard as plane
    kmi = km.keymap_items.new(
        "no3d.paste_clipboard_plane",
        type="V", value="PRESS",
        oskey=True, shift=True,
    )
    _addon_keymaps.append((km, kmi))

    # Ctrl+Shift+Alt+Z — orient selected objects' +Z to viewport
    kmi = km.keymap_items.new(
        "no3d.orient_z_to_viewport",
        type="Z", value="PRESS",
        ctrl=True, shift=True, alt=True,
    )
    _addon_keymaps.append((km, kmi))


def _unregister_keymaps():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    _register_keymaps()
    try:
        bpy.types.VIEW3D_MT_image_add.append(_draw_add_menu)
    except Exception:
        # In Blender 5.x the image submenu may have a different name; fall
        # back to the top-level Add menu.
        try:
            bpy.types.VIEW3D_MT_add.append(_draw_add_menu)
        except Exception as exc:
            log.warning("Could not append to Add menu: %s", exc)


def unregister():
    for menu_name in ("VIEW3D_MT_image_add", "VIEW3D_MT_add"):
        menu_cls = getattr(bpy.types, menu_name, None)
        if menu_cls is not None:
            try:
                menu_cls.remove(_draw_add_menu)
            except Exception:
                pass
    _unregister_keymaps()
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
