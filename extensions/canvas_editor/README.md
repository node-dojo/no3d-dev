# Canvas Editor

Experimental Blender 5.2 extension for borderless spatial documents on top of
Blender's native Node Editor mechanics.

V0.2 provides a dedicated Canvas window, an automatically created untitled
custom node tree, GPU-skinned image and note cards, hover-revealed controls,
native relationship sockets, frames, and nested Canvas group datablocks.

Image Card creation uses Blender's native file browser and creates a card only
after the image loads successfully. Note Cards open their native `Text`
datablock in a same-window companion Text Editor through **Edit Note** or a
double-click. Use the companion editor's Canvas sidebar to return that area to
the Canvas.

## V0 boundary

- Blender-native `.blend` persistence only.
- No Blender fork.
- No Obsidian synchronization.
- No document-computation runtime yet.
- No Node Wrangler dependency.

Open **3D View > Sidebar > NO3D Dev > Canvas Editor > Open Canvas**. The
Canvas opens without asking for a name or destination. Use the Canvas sidebar
or Add menu to place cards.
