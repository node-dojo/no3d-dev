# Feature Tool architecture

Feature Tools are small authoring actions that establish durable relationships
between native Blender datablocks. The add-on accelerates their creation and
navigation; it is not required to evaluate the saved result.

## Native relationship first

An Object field stores a direct pointer to an Object datablock. That Object can
continue to exist and evaluate through Geometry Nodes even when it belongs to
no collection in the current scene. This is a **stowed object**, not a missing
definition and not necessarily orphaned data.

`Relink Object to Current Scene` is therefore a general Object-reference
operation. It appears in Blender's shared property-button context menu whenever
the hovered Object field references a datablock outside the current scene. It
links the same object identity back into a collection; it does not reconstruct,
rename, duplicate, or replace the reference.

The destination order is:

1. the referenced object's parent's collection in the current scene;
2. the active object's collection in the current scene;
3. the active layer collection;
4. the Scene Collection.

Because this facility understands Object fields rather than F-Tool metadata,
it also applies to modifiers, constraints, Geometry Nodes inputs, Object Info
nodes, and other Blender interfaces that expose an Object pointer.

## Feature Tool catalog

Each action-style Feature Tool module owns one immutable `FeatureToolSpec`:

```python
FEATURE_TOOL_SPEC = FeatureToolSpec(
    id="split_with_plane",
    label="Add Split with Plane",
    description="Create and bind a plane-driven split feature",
    operator="no3d_cad.add_split_with_plane",
    icon="MOD_BOOLEAN",
    order=30,
)
```

The stable catalog ID identifies the launcher entry. The operator owns the
creation action. Node-group datablocks remain separate, immediately editable
definitions and may be swapped without changing the catalog entry.

The generic baseline deliberately assigns different responsibilities to its
two definitions:

- the reference object's definition evaluates on the parented one-point object;
- the embed definition accepts that Object pointer, reads its evaluated geometry
  with Object Info, and passes that geometry to the owner graph's output.

The baseline embed does not assume that the owner's prior geometry should be
joined, subtracted, intersected, or otherwise combined. Those operations belong
to later authored embed definitions. If an existing embed definition exposes a
Geometry input, the creation action inserts it inline; without that socket, the
embed output becomes the owner graph's output directly.

During add-on registration, the extension registers each module's spec into
the runtime catalog. Stable IDs and operator IDs are validated for collisions;
unregistration removes them. Both sidebar buttons and the Node Editor search
launcher are projections of that catalog. A future built-in tool contributes
one spec and operator rather than adding itself separately to every menu.

The searchable operator must declare `bl_property = "feature_tool"`. Blender's
search popup uses that property to request the catalog's dynamic enum items;
having an enum callback without declaring the searchable property produces an
empty popup even when the catalog itself contains tools.

## Node Editor creation surface

In a Geometry Nodes editor, **Shift-F** opens **Add Feature Tool**, a searchable
catalog analogous to Blender's searchable Add menu. The key binding is created
in Blender's add-on keyconfig, so it can be changed or disabled through the
normal Preferences > Keymap workflow. The chord is a default, not operator
logic.

Feature actions invoked from the Node Editor resolve the Object owning the
displayed graph (`space_data.id`) before consulting viewport selection. This is
especially important for pinned editors: selecting or editing a reference
object does not retarget or disable actions intended for the graph still on
screen. Outside the Node Editor, the active object remains the authoring
context. A recognized feature helper can fall back to its parent when only the
parent owns a Geometry Nodes graph.

Node Editor creation follows native Add semantics. A Feature Tool node is
created in the currently edited tree at the node cursor with its reference
bound, but it is left unconnected. It does not replace Group Output, remove an
existing output link, or infer where it belongs in the graph. This applies to
the sidebar and Shift-F because both execute within the same editor context.
Action-style automatic wiring remains available when a tool is explicitly
invoked from a non-node surface such as the 3D View sidebar.

For New F-Tool, the current editable Geometry Nodes tree is sufficient
authority; object selection is not required. If the editor exposes an owning
Object, the new reference is parented and colocated through that relationship.
If the tree has no unambiguous Object owner, the reference is created
unparented in the active collection and its direct Object socket binding still
provides the durable relationship. The Node Editor never borrows an unrelated
viewport selection as an implicit owner.

Creation should begin from the author's present context. A Feature Tool may
create helper objects, insert native node groups, or begin an interactive
placement step, but it should not require naming, classification, or publishing
decisions before they become necessary.

## Viewport gesture families

An ordinary creation gesture and its F-Tool variation should share the same
spatial action. Shift-4 creates a two-point mesh line at the 3D cursor and
hands endpoint placement to Blender's native translate modal. Adding Command
creates that same line as a reference object and embeds it in a target.

Target selection is part of this spatial gesture, not an up-front form. An
already selected object is used immediately; otherwise the operator remains
active, reports `Click an object to use as the F-Tool target` in Blender's
status surface, and accepts the next object click. This keeps the creation
action available even when selection was omitted.

The target does not need pre-existing Geometry Nodes. In that case the
operator creates a native blank Geometry Nodes modifier containing only a
Geometry input-to-output pass-through, then adds the bound F-Tool Embed node
without connecting it. This establishes an authoring workspace while
preserving the target's evaluated geometry and leaving graph topology under
the author's control.

## Open authoring surface

The immediate instance controls remain the reference-definition and
embed-definition node-group selectors. They need a durable, visible editing
surface that can be reached from either half of the relationship without
turning node-group authoring into a separate configuration workflow.

Candidate options that should remain experiments until exercised include the
initial reference representation (one point, plane, or another mesh seed), a
feature-point versus target-mesh mode, and other creation-time toggles. These
are optional conveniences around the stable Object binding; they are not part
of the minimum F-Tool identity.
