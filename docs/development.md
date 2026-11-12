# Development

The two modules use Maya’s bundled Python and PySide6. The minimum is Maya 2026, Python 3.11 and Qt 6.5.3. No packages need installing in Maya.

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

## Compatibility

Use Qt signals available in 6.5, including the two-state checkbox `toggled(bool)` signal. Keep paths native for filesystem access and normalize incoming FBX texture filenames before matching. Text files use UTF-8. Qt handles high-DPI scaling.

CI runs portable tests on Windows and Linux with Python 3.11/3.13, plus production widget fixtures on Qt 6.5.3/6.8.3. The fixture host doesn’t replace full Maya testing. Dock geometry uses public QTabWidget/QSplitter APIs to constrain the allocated row, and releases those constraints when the toolbar floats or closes.

[Autodesk’s Qt guidance](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-DEVHELP/files/Whats-New-Whats-Changed/2025-Whats-New-in-API/Qt6Migration.html) covers Maya’s Qt6 migration.

## Releases

Use Conventional Commits, such as `fix: ...` or `feat: ...`. After main passes Checks, release-please opens a version PR with the changelog, manifest, version.txt and module version updated together. The release PR gets its own dispatched checks because GitHub’s default bot token doesn’t trigger PR workflows.

Review and merge that PR when its checks pass. After the merged commit passes Checks, release-please creates a draft release. The publish job builds the ZIP, uploads it with the SHA-256 file and publishes the release. A failed publish leaves the draft intact; rerun that failed job. No bot merges PRs automatically.

There’s no automatic code download inside Maya. Users update by running the installer from the new release ZIP.
