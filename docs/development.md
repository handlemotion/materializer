# Development

The two modules use Maya’s bundled Python and PySide6. No packages need installing in Maya.

Run the portable checks from the repository root.

```sh
python3 -m unittest discover -s tests
python3 scripts/build_release.py
```

For the scene and UI checks, use Maya’s `mayapy` executable.

```sh
mayapy tests/maya_regression.py
mayapy tests/ui_lifecycle.py
```

The scene test creates temporary meshes and textures. The UI test uses fixture data in a separate process and exercises the production widgets with Maya’s Qt build. Neither opens an artist’s scene.

## macOS UI

Maya 2027.2 bundles Qt 6.8.3. Native crash reports during development failed in `QMacAccessibilityElement dealloc`, consistent with [Qt’s item-view accessibility defect](https://qt-project.atlassian.net/browse/QTBUG-134784).

Assignment lists use ordinary buttons, checkboxes and rich text in scroll areas. Keep tree/table models out of these views. Accessibility stays enabled. This avoids the plugin’s affected path; it doesn’t patch Maya’s Qt libraries.

## Releases

Update `__version__` in `materializer.py`, run the checks and build the ZIP. Publish the ZIP and its SHA-256 file with a matching GitHub release tag. Updates are explicit downloads; the plugin doesn’t fetch or execute remote code.
