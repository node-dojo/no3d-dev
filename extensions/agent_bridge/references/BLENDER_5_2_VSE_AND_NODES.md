# Blender 5.2 VSE and Nodes Working Reference

Research snapshot: 2026-09-05. Runtime checked against Blender 5.2.0 LTS.

This is the local navigation and interpretation layer for transcript-heavy
editing work. It keeps the authoritative Blender 5.2 sources and the most
relevant external experiments close to Agent Bridge. It does not freeze the
web pages or turn community tools into approved dependencies.

## Source order

1. The live `.blend` and evaluated result are operational truth.
2. The Blender 5.2 manual explains supported use.
3. Blender 5.2 release notes define what changed in this release.
4. The Blender 5.2 Python API defines automation names and ownership.
5. Community tools and tutorials are candidates to test in a disposable
   profile before they enter the working setup.

Do not infer a 5.2 Python property from an older VSE tutorial. Blender 5.0/5.2
renamed the public sequence API around `Strip`, `strips`, and `strips_all`.

## Official documentation within reach

### VSE foundations

- [Video Editing — 5.2 manual](https://docs.blender.org/manual/en/5.2/video_editing/index.html)
- [Video Sequencer editor introduction](https://docs.blender.org/manual/en/5.2/editors/video_sequencer/introduction.html)
- [Editing a project](https://docs.blender.org/manual/en/5.2/video_editing/edit/index.html)
- [Montage and strip editing](https://docs.blender.org/manual/en/5.2/video_editing/edit/montage/index.html)
- [Strip types](https://docs.blender.org/manual/en/5.2/video_editing/edit/montage/strips/index.html)
- [Text strips](https://docs.blender.org/manual/en/5.2/video_editing/edit/montage/strips/text.html)
- [Scene strips](https://docs.blender.org/manual/en/5.2/video_editing/edit/montage/strips/scene.html)
- [Sequencer Scene, playback context, and rendering](https://docs.blender.org/manual/en/5.2/video_editing/sequencer_scene.html)
- [Blender 5.2 VSE release notes](https://developer.blender.org/docs/release_notes/5.2/sequencer/)

### Compositor inside the edit

- [Compositor strip](https://docs.blender.org/manual/en/5.2/video_editing/edit/montage/strips/compositor.html)
- [Strip modifiers](https://docs.blender.org/manual/en/5.2/video_editing/edit/montage/modifiers/index.html)
- [Compositor editor](https://docs.blender.org/manual/en/5.2/editors/compositor.html)
- [Compositor system and active/root tree contexts](https://docs.blender.org/manual/en/5.2/compositing/compositor_system.html)
- [Sequencer Strip Info node](https://docs.blender.org/manual/en/5.2/compositing/types/input/sequencer_strip_info.html)
- [String to Image node](https://docs.blender.org/manual/en/5.2/compositing/types/input/string_to_image.html)
- [Blender 5.2 compositor release notes](https://developer.blender.org/docs/release_notes/5.2/compositor/)

### Strings, lists, and scene time

- [Geometry Nodes text utilities](https://docs.blender.org/manual/en/5.2/modeling/geometry_nodes/utilities/text/index.html)
- [Geometry Nodes list utilities](https://docs.blender.org/manual/en/5.2/modeling/geometry_nodes/utilities/list/index.html)
- [Scene Time node](https://docs.blender.org/manual/en/5.2/compositing/types/input/scene/scene_time.html)
- [Blender 5.2 Geometry Nodes release notes](https://developer.blender.org/docs/release_notes/5.2/geometry_nodes/)
- [All Blender 5.2 release notes](https://developer.blender.org/docs/release_notes/5.2/)

### Python automation surface

- [`Scene`](https://docs.blender.org/api/5.2/bpy.types.Scene.html)
- [`SequenceEditor`](https://docs.blender.org/api/5.2/bpy.types.SequenceEditor.html)
- [`Strip` base class](https://docs.blender.org/api/5.2/bpy.types.Strip.html)
- [`MetaStrip`](https://docs.blender.org/api/5.2/bpy.types.MetaStrip.html)
- [`SpaceSequenceEditor`](https://docs.blender.org/api/5.2/bpy.types.SpaceSequenceEditor.html)
- [`SpaceNodeEditor`](https://docs.blender.org/api/5.2/bpy.types.SpaceNodeEditor.html)
- [Sequencer operators](https://docs.blender.org/api/5.2/bpy.ops.sequencer.html)

## 5.2 mental model for this workflow

The VSE edit belongs to a `Scene`. That scene may own a `SequenceEditor`, whose
`strips` collection contains top-level strips. `strips_all` traverses nested
meta strips, while `meta_stack` identifies the meta path currently being
edited. `active_strip` is the fallback focus when the pointer is not over a
timeline strip.

The compositor now participates at three distinct levels. Keep them separate:

- A scene compositor belongs to a Scene and processes the scene's output.
- A compositor strip is a zero-, one-, or two-input VSE effect implemented by
  a compositor node group. It processes after strip transforms.
- A compositor strip modifier processes a strip in local image space before
  its transforms. In 5.2, modifier groups can expose arbitrary interface
  inputs and can be delivered as assets through the Strip Modifier usage.

The `Sequencer Strip Info` node exposes the current strip's frame range,
position, rotation, and scale when a compositor group is evaluated as a VSE
modifier. This is the clean bridge from timeline context into a reusable node
effect.

## What 5.2 adds that matters here

- Compositor effect strips can generate visuals, process one source, or combine
  two sources with an effect-fader input.
- Compositor modifiers/effects may use GPU execution. Complex effects can
  benefit, while transfer overhead can make tiny graphs slower.
- Compositor modifiers expose arbitrary node-group inputs, panels, menus, and
  asset-backed reuse.
- Text strips have line-spacing controls and built-in style presets for
  subtitles, main titles, and corner titles.
- Scene strips have an explicit view-layer selector.
- The compositor supports String and Font sockets plus `String to Image`, which
  makes procedural caption cards and lower thirds plausible without converting
  every text treatment to geometry.
- Geometry Nodes introduces lists with `Field to List`, `Closure to List`,
  `List Length`, and `Get List Item`. Lists are intentionally limited in 5.2.
- Geometry Nodes supports string fields and adds core parsing/cleanup tools such
  as Split, Trim, Reverse, and Set String Case. String attributes are not yet
  supported, so do not design a transcript database around geometry attributes.
- Geometry-node group inputs can use the current scene frame as a default.

Strings and lists are promising for procedural graphics and structured text
transforms. They do not by themselves create or edit VSE strips; Python/API
automation remains the direct control surface for transcript-to-timeline work.

## Transcript-heavy experiments to evaluate

These are candidates, not installed or approved dependencies:

- [Subtitle Editor](https://github.com/tin2tin/Subtitle_Editor) — Faster Whisper
  transcription/translation, list-based subtitle editing, direct Text Strip
  creation, navigation, styling, and subtitle import/export. Its current branch
  claims Blender 5.2 support; inspect and sandbox-test its dependency installer
  before using it in the working profile.
- [B SubEditor](https://extensions.blender.org/add-ons/b-subeditor/) — Blender
  Extensions-hosted SRT/VTT/SBV/TXT interchange between the Text Editor and VSE.
- [SRT Subtitle Importer/Exporter](https://extensions.blender.org/add-ons/vse-srt-subtitle-importer-4-2-extension/)
  — smaller Blender Extensions-hosted SRT interchange option.
- [Awesome VSE Add-ons](https://github.com/tin2tin/Awesome_VSE_Addons) — discovery
  list only; compatibility and maintenance vary by entry.
- [Unofficial VSE documentation](https://vse-docs.readthedocs.io/video_sequencer/index.html)
  — useful alternate explanations, but older than the 5.2 authority above.

## Agent working rules

- Begin with the live target, owning scene, active meta path, active/hovered
  strip, frame range, channel, source path, and selection. Do not assume `Scene`
  or a top-level strip.
- Address a scene compositor as `Scene → Compositor Nodes`; address a VSE item
  as `Scene → Meta Strip(s) → typed Strip`.
- Preserve capture momentum. Ingest or capture should open a place to work and
  must not first demand a project name, taxonomy, destination, or publishing
  decision.
- Keep source media immutable. Treat transcript text, timing, and edit decisions
  as separable evidence until hands-on testing establishes the canonical form.
- Build proxies/caches deliberately and verify audio sync, frame rate, color
  management, and render range before evaluating editing speed.
- Use nodes for repeatable visual processing and generated graphics; use VSE
  strips for editorial timing; use Python/API tooling for transcript-driven
  timeline mutation.
- Before adopting an add-on, record its exact version/commit, permissions,
  downloaded dependencies, 5.2 API compatibility, undo behavior, and round-trip
  export quality.

## Next acceptance questions

The production workflow should be chosen through short real edits, not from a
premature schema. The next tests should compare:

1. transcript generation accuracy and time-to-first-edit;
2. word/segment timing preservation through cuts and ripple edits;
3. SRT/VTT/JSON round-trip behavior;
4. proxy playback and audio scrubbing on representative capture media;
5. caption styling through native Text Strips versus `String to Image` node
   assets;
6. final render quality, color, loudness, duration, and reproducibility.
