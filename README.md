# Materializer

Connect texture sets to Arnold materials in Maya. Select a few props, scan, check the assignments and apply. I built this because wiring the same texture nodes by hand gets old pretty quickly.

## Install

Download the ZIP from [Releases](https://github.com/handlemotion/materializer/releases/latest), unzip it, then drag `install_materializer.py` into Maya’s viewport. Keep the three module files beside the installer. The **Materializer** shelf holds the actions.

To update, download the latest ZIP and run its installer again. It replaces the managed install, keeps your texture choices and removes duplicate launchers. Existing Material Assistant installs are migrated. The downloaded folder can be moved or deleted afterward.

Supports Maya 2026 and newer with Arnold on Windows and macOS. Maya 2027.2 has been tested in the macOS app. Windows and Qt 6.5/6.8 compatibility are covered by CI fixtures; full Maya on Windows and Maya 2026 still need testing by users. Linux is unverified.

## Use

Select props and click **Scan** on the Materializer shelf. Review which meshes and texture files belong to each material. Use **Textures** to choose a folder, then **Apply** to connect the checked assignments. **Review** reopens the assignments. Changing your selection requires another scan.

Existing Arnold and OpenPBR shaders are preserved. Legacy Phong, Blinn and Lambert shaders can be converted. The tool connects base color, normal, roughness, metalness, opacity and emission maps. Use **Inspector → Options** to choose a known DirectX normal convention.

Actions use native Maya shelf buttons. The assignment window opens when needed; there’s no extra toolbar row.

## Shading workspace

Click **Shading** on the shelf to switch between your scene workspace and **Materializer Shading**. The shading layout puts the viewport beside Hypershade, with the native Outliner collapsed on the left. The **Materializer** menu also has **Return to scene workspace** and **Graph selected meshes**.

The switch saves layout changes before leaving a workspace. Arrange the shading panels as you like; later visits reuse that layout. Materials, geometry and scene files are untouched by workspace switching. You can also choose workspaces through Maya's usual selector.

Entry, material graphing and return were checked in Maya 2027.2 on macOS. Full Maya on Windows and Maya 2026 remain unverified.

## Limits

UVs must already match the textures. Numbered UDIM tiles use one file node per channel with viewport previews. Packed maps and gloss-only sets need manual setup. Opacity needs its own map. Scenes aren’t saved automatically, and applying materials is one Maya Undo step.

MIT licensed. [Development and checks](docs/development.md).
