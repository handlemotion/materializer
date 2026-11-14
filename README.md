# Materializer

Connect texture sets to Arnold materials in Maya. Select a few props, scan, check the assignments and apply. I built this because wiring the same texture nodes by hand gets old pretty quickly.

## Install

Download the ZIP from [Releases](https://github.com/handlemotion/materializer/releases/latest), unzip it, then drag `install_materializer.py` into Maya’s viewport. Keep the two module files beside the installer. A **Materializer** shelf button opens the toolbar.

To update, download the latest ZIP and run its installer again. It replaces the managed install, keeps your texture choices and removes duplicate launchers. Existing Material Assistant installs are migrated. The downloaded folder can be moved or deleted afterward.

Supports Maya 2026 and newer with Arnold on Windows and macOS. Maya 2027.2 has been tested in the macOS app. Windows and Qt 6.5/6.8 compatibility are covered by CI fixtures; full Maya on Windows and Maya 2026 still need testing by users. Linux is unverified.

## Use

Select props and click the blue scan button. Click the status or list icon to see which meshes and texture files belong to each material. If a material needs textures, choose its folder. Check the matches, then click the green check to apply. Changing your selection requires another scan.

Existing Arnold and OpenPBR shaders are preserved. Legacy Phong, Blinn and Lambert shaders can be converted. The tool connects base color, normal, roughness, metalness, opacity and emission maps. Use **Inspector → Options** to choose a known DirectX normal convention.

The toolbar sits beside The Key Machine when it’s docked, or above the timeline at full width. Right-click for floating mode, updates or static FBX import.

## Limits

UVs must already match the textures. Numbered UDIM tiles use one file node per channel with viewport previews. Packed maps and gloss-only sets need manual setup. Opacity needs its own map. Scenes aren’t saved automatically, and applying materials is one Maya Undo step.

MIT licensed. [Development and checks](docs/development.md).
