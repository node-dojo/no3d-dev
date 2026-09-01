# No3d CAD.wip

Live development container for No3d CAD experiments.

The extension currently provides only a registration boundary, a small status
panel under `3D View > Sidebar > NO3D Dev`, and a source reload action. Modeling
features are intentionally absent until their interactions have been worked
through manually.

## Governing invariant

No3d CAD may author native Blender data and relationships, but saved `.blend`
files must remain useful in a compatible Blender installation where this
extension is absent.

## First planned feature

A native-feeling workflow for assigning, viewing, selecting by, editing, and
clearing object custom attributes. Its interaction and data contract will be
specified from real use before implementation.

## Development

The canonical source is this directory inside No3d Dev. Local Blender 5.2 uses
a source-linked installation so code edits become available without rebuilding
or reinstalling the extension. Use **Reload No3d CAD.wip** in the `NO3D Dev`
sidebar after ordinary Python changes.

