# No3d CAD.wip

Live development container for No3d CAD experiments.

The extension provides a source-reloadable panel under
`3D View > Sidebar > NO3D Dev` and the Geometry Node Editor sidebar. Its first
three Feature Tools are **New F-Tool**, **Make Spin**, and
**Add Split with Plane**.

The viewport also provides a mesh-line shortcut family:

- **Shift-4** creates an edge from the 3D cursor and immediately begins moving
  its second point.
- **Shift-Command-4** performs the same gesture as an F-Tool. If no target is
  selected, the status bar asks for one and the next object click supplies it.
  A target with no Geometry Nodes modifier receives a blank native
  Geometry-in/Geometry-out pass-through; the new F-Tool Embed is placed in
  that tree disconnected, ready for the author to wire deliberately.

## Governing invariant

No3d CAD may author native Blender data and relationships, but saved `.blend`
files must remain useful in a compatible Blender installation where this
extension is absent.

## Referenced objects

Right-click an Object datablock field that points to an object outside the
current scene and choose **Relink Object to Current Scene**. The operation
restores collection membership for the existing datablock; it preserves object
identity, transforms, parenting, modifiers, and every existing reference.

This is a general Object-field affordance rather than an F-Tool-only command,
so it is available wherever Blender exposes a resolvable Object property.

## Feature Tools

- **New F-Tool** creates a one-point reference mesh with a pass-through
  Geometry Nodes modifier. Its minimal embed group reads the bound reference
  through Object Info and outputs that evaluated geometry. It does not prescribe
  a merge, boolean, or owner-geometry pass-through; those are additive choices
  made by authored embed definitions. Selecting either the owner or reference
  exposes direct node-group datablock selectors for both halves, making them
  independently hot-swappable without changing add-on code.
- **Make Spin** creates a one-point feature object, attaches the local-first
  `make spin` Geometry Nodes definition, and begins point placement.
- **Add Split with Plane** creates a wire plane at the active object's local
  bounds center, inserts `Split with Plane [wip]` before the active Geometry
  Output, binds the plane, and begins placement when invoked from the viewport.

Definitions resolve from the current file, then the extension's local WIP
library, then their existing asset bundle inside the registered `NO3D - WIP`
library. Publishing Make Spin creates or replaces the extension's current
single-definition WIP library.

## Feature Tool search

Press **Shift-F** in a Geometry Nodes editor to search the configured Feature
Tool catalog and run a tool without leaving the graph. The sidebar buttons and
search results both come from the same runtime registry. Each Feature Tool
module owns one `FeatureToolSpec` that is registered with the extension.
Blender registers Shift-F in its add-on keyconfig, making the default shortcut
editable through Preferences > Keymap.

Creation from the Node Editor follows Blender's native Add behavior: the new
Feature Tool node appears at the node cursor with its reference bound and no
connections. Existing links and Group Output are left untouched. Invoking an
action-style tool from the 3D View can still perform its explicit automatic
wiring workflow.

New F-Tool does not require an active or selected object in the Node Editor.
The current edit tree is sufficient. When Blender exposes an unambiguous owner,
the reference is parented to it; otherwise the direct Object binding is created
with an unparented reference in the active collection.

See `FEATURE_TOOL_ARCHITECTURE.md` for the relationship model and catalog
definition format.

## Development

The canonical source is this directory inside No3d Dev. Local Blender 5.2 uses
a source-linked installation so code edits become available without rebuilding
or reinstalling the extension. Use **Reload No3d CAD.wip** in the `NO3D Dev`
sidebar after ordinary Python changes.
