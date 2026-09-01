# Power Panel feature-suite design

Power Panel is an internal feature suite of No3d Asset Developer. It is not a
standalone extension and does not create another N-panel category. It owns the
navigation layer around Blender's existing 3D View sidebar.

## Package boundary

`extensions/no3d_asset_developer/power_panel/` owns configuration, panel
discovery, reversible routing, numeric display slots, ordering, filtering,
search, pie navigation, keymaps, and preference drawing. The host imports only
the package and calls its lifecycle once.

## State pipeline

Every reconciliation uses this order:

1. Restore Power Panel's previous category/order/parent snapshots.
2. Discover the currently registered sidebar panel graph.
3. Route configured panels into canonical intent categories.
4. Apply stable numeric display prefixes from user slot assignments.
5. Re-register categories in native, Power Panel, then unrelated order.

Filtering is temporary presentation state layered after reconciliation. It
must restore hidden panels before any pipeline run.

## Interaction model

- F5 enters keyboard-driven filtering of the persistent Tool Settings field.
- Option+Tab invokes the spatial Power Panel radial overlay.
- Radial entries open destinations by gesture/click.
- While the overlay is invoked, number-row 1–9 opens the corresponding
  configured slot.
- No global modifier-number family is reserved.
- The popup category search remains a fallback available through the header
  and F3 operator search.

The overlay is a modal 3D View drawing rather than Blender's stock pie menu.
This preserves direct, unmodified number selection after invocation; a stock
pie consumes those events before an add-on operator can route them.

## Configuration

Python configuration is executable truth. The linked Markdown tables are the
human-editable specification and must be updated with behavioral changes.
Default slot assignments require no setup. Add-on preferences expose optional
dropdown overrides; blank/unavailable destinations retain stable slot IDs and
never compact later slots.

## Compatibility and safety

Existing public operator IDs remain stable. All foreign panel mutations are
snapshotted and restored, including partial-failure recovery. Power Panel does
not save Blender preferences. Live reload must remove stale header callbacks,
handlers, timers, and keymaps by semantic identity rather than relying only on
new Python function identity.
