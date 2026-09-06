# No3d CAD.wip

Live development container for No3d CAD experiments.

The extension provides a source-reloadable panel under
`3D View > Sidebar > NO3D Dev` and the Geometry Node Editor sidebar. Its
Feature Tools are **New F-Tool** and **Add Split with Plane**.

The viewport also provides a mesh-line shortcut family:

- **Shift-4** creates an edge from the 3D cursor and immediately begins moving
  its second point.
- **Shift-Command-4** performs the same gesture as an F-Tool. If no target is
  selected, the status bar asks for one and the next object click supplies it.
  A target with no Geometry Nodes modifier receives a blank native
  Geometry-in/Geometry-out pass-through; the new F-Tool Embed is placed in
  that tree disconnected, ready for the author to wire deliberately.

## Embed existing objects

In the 3D View or Outliner, select one or more feature objects and make their
intended owner the active object. Selection is resolved across the View Layer,
so invoking the shortcut from a Local View does not discard selected objects
outside that viewport. **Embed Selected as F-Tools** parents the feature
objects without changing their world transforms and adds their evaluated
  geometry as an unconnected node in the owner's active Geometry Nodes tree.

- One feature object creates one direct **F-Tool Embed** node in the owner tree.
- Two or more feature objects create one tangible, owner-specific
  `<Owner> · F-Tool Set` node group. It exposes one Object socket per feature,
  passes each through an F-Tool Embed, and combines them with Join Geometry.
- A target without Geometry Nodes receives a native pass-through modifier.
- Repeated selection of an already embedded object is ignored rather than
  duplicated.

The created direct Embed node or F-Tool Set node is placed at the center of the
Node Editor currently displaying the target tree. If that position overlaps an
existing node, placement searches outward for the nearest clear location. When
the target tree is not visible, the same search begins from the graph's center.
The node is never connected to Group Output or another existing node.

The operator's **Feature Display** property is available through Adjust Last
Operation. Its modes are Hidden in Viewport, Bounds, Wire, Solid, and
Unchanged; Hidden in Viewport is the default.

Enable **Expose Objects in Modifier** in Adjust Last Operation when duplicates
of the owner should carry independently duplicated feature-object assignments
through Blender's modifier interface. Leave it off when the duplicate should
continue sharing the embedded references.

In the Geometry Node Editor, select one or more nodes with assigned Object
inputs and run **Expose Object Inputs in Modifier** from the NO3D Dev panel.
The command creates Group Input sockets all the way through the current nested
group path and preserves each assigned Object at the modifier level. Existing
Group Input connections are reused and repaired rather than duplicated.

The default 3D View shortcut is **Shift-Command-F** on macOS. It is declared in
`keymaps.py` and registered in Blender's add-on keyconfig, so users can change
or disable it in Preferences > Keymap without changing operator code.

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
- **Add Split with Plane** creates a wire plane at the active object's local
  bounds center, inserts `Split with Plane [wip]` before the active Geometry
  Output, binds the plane, and begins placement when invoked from the viewport.

Definitions resolve from the current file, then the extension's local WIP
library, then their existing asset bundle inside the registered `NO3D - WIP`
library.

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
