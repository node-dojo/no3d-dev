# SPDX-License-Identifier: GPL-3.0-or-later
"""Render and convert transparent animated media with predictable presets."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator, Panel


_FRAME_RE = re.compile(r"^(.*?)(\d+)(\.png)$", re.IGNORECASE)


@dataclass(frozen=True)
class SequenceInfo:
    folder: Path
    prefix: str
    digits: int
    start: int
    end: int
    count: int

    @property
    def pattern(self) -> str:
        return str(self.folder / f"{self.prefix}%0{self.digits}d.png")


def find_ffmpeg(override: str = "") -> str | None:
    candidates = [
        bpy.path.abspath(override).strip() if override else "",
        shutil.which("ffmpeg") or "",
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def discover_sequence(
    folder: str | Path,
    preferred_prefix: str | None = None,
    expected_range: tuple[int, int] | None = None,
) -> SequenceInfo:
    directory = Path(folder).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"PNG sequence folder not found: {directory}")

    groups: dict[tuple[str, int], list[int]] = {}
    for path in directory.iterdir():
        match = _FRAME_RE.match(path.name)
        if not match:
            continue
        prefix, number, _extension = match.groups()
        key = (prefix, len(number))
        groups.setdefault(key, []).append(int(number))

    if preferred_prefix is not None:
        preferred = [(key, values) for key, values in groups.items() if key[0] == preferred_prefix]
    else:
        preferred = []
    choices = preferred or list(groups.items())
    if not choices:
        raise ValueError(f"No numbered PNG sequence found in: {directory}")

    (prefix, digits), frames = max(choices, key=lambda item: len(item[1]))
    ordered = sorted(set(frames))
    if expected_range is not None:
        expected_start, expected_end = expected_range
        wanted = list(range(expected_start, expected_end + 1))
        missing = sorted(set(wanted) - set(ordered))
        if missing:
            sample = ", ".join(str(frame) for frame in missing[:5])
            raise ValueError(f"Rendered PNG sequence has missing frames: {sample}")
        return SequenceInfo(directory, prefix, digits, expected_start, expected_end, len(wanted))
    expected = list(range(ordered[0], ordered[-1] + 1))
    if ordered != expected:
        missing = sorted(set(expected) - set(ordered))
        sample = ", ".join(str(frame) for frame in missing[:5])
        raise ValueError(f"PNG sequence has missing frames: {sample}")
    return SequenceInfo(directory, prefix, digits, ordered[0], ordered[-1], len(ordered))


def render_output_location(scene) -> tuple[Path, str]:
    raw = scene.render.filepath or "//"
    absolute = Path(bpy.path.abspath(raw)).expanduser()
    directory_hint = raw.endswith(("/", "\\")) or absolute.is_dir()
    if directory_hint:
        return absolute.resolve(), ""
    return absolute.parent.resolve(), absolute.name


def inferred_stem(sequence: SequenceInfo, from_scene: bool) -> str:
    if from_scene and bpy.data.filepath:
        return Path(bpy.data.filepath).stem
    return sequence.folder.name or "transparent-animation"


def output_path(sequence: SequenceInfo, from_scene: bool, kind: str) -> Path:
    suffix = ".mov" if kind == "MOV" else ".gif"
    stem = inferred_stem(sequence, from_scene)
    return sequence.folder.parent / f"{stem}-transparent{suffix}"


def ffmpeg_command(ffmpeg: str, sequence: SequenceInfo, fps: float, kind: str, destination: Path) -> list[str]:
    base = [
        ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
        "-framerate", f"{fps:g}", "-start_number", str(sequence.start),
        "-i", sequence.pattern,
    ]
    if kind == "MOV":
        return base + [
            "-an", "-c:v", "prores_ks", "-profile:v", "4",
            "-pix_fmt", "yuva444p10le", "-alpha_bits", "16",
            str(destination),
        ]
    return base + [
        "-filter_complex",
        "[0:v]split[frames][palette_source];"
        "[palette_source]palettegen=reserve_transparent=1:transparency_color=ffffff[palette];"
        "[frames][palette]paletteuse=alpha_threshold=128:dither=sierra2_4a",
        "-loop", "0", str(destination),
    ]


def _addon_preferences(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _source_sequence(context, render_scene: bool) -> SequenceInfo:
    scene = context.scene
    folder, prefix = render_output_location(scene)
    if not render_scene:
        selected = (scene.no3d_transparent_sequence_folder or "").strip()
        if selected:
            return discover_sequence(bpy.path.abspath(selected))
        return discover_sequence(folder, preferred_prefix=prefix)

    original = {
        "file_format": scene.render.image_settings.file_format,
        "color_mode": scene.render.image_settings.color_mode,
        "color_depth": scene.render.image_settings.color_depth,
        "film_transparent": scene.render.film_transparent,
    }
    folder.mkdir(parents=True, exist_ok=True)
    try:
        try:
            scene.render.image_settings.file_format = "PNG"
            scene.render.image_settings.color_mode = "RGBA"
            scene.render.image_settings.color_depth = "8"
            scene.render.film_transparent = True
            bpy.ops.render.render(animation=True)
        except TypeError as exc:
            # Blender 5.2 Stable can dynamically restrict file_format to the
            # current movie type (('FFMPEG',)) in scenes already configured
            # for direct video. Render Result still supports PNG, so write the
            # same RGBA master one frame at a time without touching the movie
            # encoding setup.
            if 'enum "PNG" not found' not in str(exc):
                raise
            scene.render.film_transparent = True
            original_frame = scene.frame_current
            try:
                for frame in range(scene.frame_start, scene.frame_end + 1, scene.frame_step):
                    scene.frame_set(frame)
                    bpy.ops.render.render()
                    image = bpy.data.images.get("Render Result")
                    if image is None:
                        raise RuntimeError("Blender did not create Render Result")
                    image.file_format = "PNG"
                    image.save_render(str(folder / f"{prefix}{frame:04d}.png"))
            finally:
                scene.frame_set(original_frame)
    finally:
        scene.render.image_settings.file_format = original["file_format"]
        scene.render.image_settings.color_mode = original["color_mode"]
        scene.render.image_settings.color_depth = original["color_depth"]
        scene.render.film_transparent = original["film_transparent"]
    return discover_sequence(
        folder,
        preferred_prefix=prefix,
        expected_range=(scene.frame_start, scene.frame_end),
    )


class NO3D_AD_OT_transparent_media(Operator):
    bl_idname = "no3d.transparent_media"
    bl_label = "Create Transparent Media"
    bl_description = "Render or convert a PNG sequence using a tested transparent-media preset"

    action: EnumProperty(
        items=(
            ("RENDER_MOV", "Render Transparent Video", "Render PNGs, then create a ProRes 4444 MOV"),
            ("RENDER_GIF", "Render Transparent GIF", "Render PNGs, then create a looping transparent GIF"),
            ("CONVERT_MOV", "Sequence to Video", "Convert an existing numbered PNG sequence to ProRes 4444 MOV"),
            ("CONVERT_GIF", "Sequence to GIF", "Convert an existing numbered PNG sequence to a looping transparent GIF"),
        ),
    )

    def execute(self, context):
        render_scene = self.action.startswith("RENDER_")
        kind = self.action.rsplit("_", 1)[-1]
        prefs = _addon_preferences(context)
        ffmpeg = find_ffmpeg(getattr(prefs, "transparent_media_ffmpeg_path", "") if prefs else "")
        if not ffmpeg:
            self.report({"ERROR"}, "FFmpeg not found. Set its path in No3d Asset Developer preferences.")
            return {"CANCELLED"}
        try:
            sequence = _source_sequence(context, render_scene)
            fps = context.scene.render.fps / context.scene.render.fps_base
            destination = output_path(sequence, render_scene, kind)
            command = ffmpeg_command(ffmpeg, sequence, fps, kind, destination)
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "FFmpeg failed").strip().splitlines()[-1]
                raise RuntimeError(message)
            if not destination.is_file() or destination.stat().st_size == 0:
                raise RuntimeError("FFmpeg completed without creating a usable output file")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        context.scene.no3d_transparent_media_last_output = str(destination)
        self.report({"INFO"}, f"Created {destination.name}")
        return {"FINISHED"}


class NO3D_AD_OT_open_transparent_media_output(Operator):
    bl_idname = "no3d.open_transparent_media_output"
    bl_label = "Show Last Output"

    def execute(self, context):
        output = Path(context.scene.no3d_transparent_media_last_output)
        if not output.exists():
            self.report({"ERROR"}, "No transparent-media output is available yet")
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=str(output.parent))
        return {"FINISHED"}


class NO3D_AD_PT_transparent_media(Panel):
    bl_label = "Transparent Media"
    bl_idname = "NO3D_AD_PT_transparent_media"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NO3D Dev"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        render_box = layout.box()
        render_box.label(text="Create from Scene", icon="RENDER_ANIMATION")
        render_box.label(text="Uses current camera, range, size, engine and FPS.", icon="INFO")
        row = render_box.row(align=True)
        op = row.operator("no3d.transparent_media", text="Video", icon="FILE_MOVIE")
        op.action = "RENDER_MOV"
        op = row.operator("no3d.transparent_media", text="GIF", icon="IMAGE_DATA")
        op.action = "RENDER_GIF"

        convert_box = layout.box()
        convert_box.label(text="Convert PNG Sequence", icon="SEQ_SEQUENCER")
        convert_box.prop(scene, "no3d_transparent_sequence_folder", text="Folder")
        if not scene.no3d_transparent_sequence_folder:
            convert_box.label(text="Empty uses the current Output folder.", icon="INFO")
        row = convert_box.row(align=True)
        op = row.operator("no3d.transparent_media", text="Video", icon="FILE_MOVIE")
        op.action = "CONVERT_MOV"
        op = row.operator("no3d.transparent_media", text="GIF", icon="IMAGE_DATA")
        op.action = "CONVERT_GIF"

        if scene.no3d_transparent_media_last_output:
            layout.operator("no3d.open_transparent_media_output", icon="FILE_FOLDER")

        prefs = _addon_preferences(context)
        ffmpeg = find_ffmpeg(getattr(prefs, "transparent_media_ffmpeg_path", "") if prefs else "")
        layout.label(text="FFmpeg ready" if ffmpeg else "FFmpeg path needed in Preferences", icon="CHECKMARK" if ffmpeg else "ERROR")
        layout.label(text="Video: ProRes 4444 MOV  |  GIF: binary alpha", icon="INFO")


_CLASSES = (
    NO3D_AD_OT_transparent_media,
    NO3D_AD_OT_open_transparent_media_output,
    NO3D_AD_PT_transparent_media,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.no3d_transparent_sequence_folder = StringProperty(
        name="PNG Sequence Folder",
        description="Folder containing numbered PNG frames; empty uses the scene Output folder",
        subtype="DIR_PATH",
        default="",
    )
    bpy.types.Scene.no3d_transparent_media_last_output = StringProperty(default="")


def unregister():
    for prop in ("no3d_transparent_media_last_output", "no3d_transparent_sequence_folder"):
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
