"""Drag into Maya to install or update Materializer."""

import builtins
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

MODULES = (
    "materializer_core.py",
    "materializer_workspaces.py",
    "materializer.py",
    "materializer_bar.py",
)


def install_files(source, target):
    contents = {name: (source / name).read_bytes() for name in MODULES}
    for name, data in contents.items():
        compile(data, name, "exec")
    target.mkdir(parents=True, exist_ok=True)
    previous = {
        name: (target / name).read_bytes() if (target / name).exists() else None for name in MODULES
    }
    staged = []
    try:
        for name, data in contents.items():
            with tempfile.NamedTemporaryFile(dir=target, delete=False) as handle:
                staged.append((Path(handle.name), target / name))
                handle.write(data)
        for temporary, destination in staged:
            os.replace(temporary, destination)
    except OSError:
        for name, data in previous.items():
            destination = target / name
            if data is None:
                destination.unlink(missing_ok=True)
            else:
                destination.write_bytes(data)
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def close_tools(cmds):
    from shiboken6 import isValid

    for key in ("_materializer_window", "_maya_material_assistant_window"):
        window = getattr(builtins, key, None)
        if window is None or not isValid(window):
            continue
        worker = window.worker
        if worker and worker.isRunning():
            worker.requestInterruption()
            if not worker.wait(2000):
                raise RuntimeError("The texture scan is stopping. Try installing again shortly.")
        window._closing = True
    for key in (
        "_materializer_bar",
        "_maya_material_assistant_bar",
        "_materializer_window",
        "_maya_material_assistant_window",
    ):
        widget = getattr(builtins, key, None)
        if widget is not None and isValid(widget):
            widget.close()
            widget.deleteLater()
        setattr(builtins, key, None)
    for control in (
        "MaterializerQuickBarWorkspaceControl",
        "MaterialAssistantQuickBarWorkspaceControl",
    ):
        if cmds.workspaceControl(control, query=True, exists=True):
            cmds.deleteUI(control)


def install(open_toolbar=True):
    import maya.cmds as cmds
    import maya.mel as mel

    if cmds.about(apiVersion=True) < 20260000:
        raise RuntimeError("Materializer requires Maya 2026 or newer.")

    from PySide6 import QtCore

    source = Path(__file__).resolve().parent
    for name in MODULES:
        compile((source / name).read_bytes(), name, "exec")
    settings = QtCore.QSettings("Handlemotion", "Materializer")
    for control in (
        "MaterializerQuickBarWorkspaceControl",
        "MaterialAssistantQuickBarWorkspaceControl",
    ):
        if cmds.workspaceControl(control, query=True, exists=True):
            settings.setValue(
                "toolbarFloating",
                cmds.workspaceControl(control, query=True, floating=True),
            )
            break
    close_tools(cmds)
    target = Path(cmds.internalVar(userScriptDir=True)) / "materializer_tool"
    install_files(source, target)

    legacy = QtCore.QSettings("RodrigoTools", "MaterialAssistant")
    for key in legacy.allKeys():
        if not settings.contains(key):
            settings.setValue(key, legacy.value(key))
    settings.sync()

    folder = str(target)
    if folder in sys.path:
        sys.path.remove(folder)
    sys.path.insert(0, folder)
    for name in ("materializer", "materializer_core", "materializer_workspaces", "materializer_bar"):
        sys.modules.pop(name, None)
    for name in MODULES:
        for cached in (target / "__pycache__").glob(Path(name).stem + ".*.pyc"):
            cached.unlink()
    importlib.invalidate_caches()
    module = importlib.import_module("materializer")
    from materializer_workspaces import install_menu

    install_menu(cmds, replace=True)
    legacy_module = target.parent / "material_assistant_tool" / "material_assistant.py"
    if legacy_module.is_file():
        shim = f"import sys\np={folder!r}\nif p not in sys.path: sys.path.insert(0,p)\nfrom materializer import launch, show, toolbar, shutdown\n\ndef restore_workspace():\n    import maya.cmds as cmds\n    from PySide6 import QtCore\n    def remove_legacy_dock():\n        name='MaterialAssistantQuickBarWorkspaceControl'\n        if cmds.workspaceControl(name,query=True,exists=True): cmds.deleteUI(name)\n    QtCore.QTimer.singleShot(0,remove_legacy_dock)\n    return None\n"
        legacy_module.write_text(shim, encoding="utf-8")
        sys.modules.pop("material_assistant", None)
    prefix = f"import sys; p={folder!r}; sys.path.insert(0,p) if p not in sys.path else None; import materializer; "
    shelves = mel.eval("$materializerShelves = $gShelfTopLevel")
    legacy_notes = {
        "Find texture sets and connect Arnold materials",
        "Material Assistant: choose a texture folder",
        "Material Assistant: import a static FBX without animation takes",
    }
    for tab in ("MaterialAssistant", "Materializer"):
        if not cmds.shelfLayout(tab, exists=True):
            continue
        for button in cmds.shelfLayout(tab, query=True, childArray=True) or []:
            if button.rsplit("|", 1)[-1].startswith("MaterializerShelfDivider_"):
                cmds.deleteUI(button)
                continue
            if cmds.objectTypeUI(button) != "shelfButton":
                continue
            note = cmds.shelfButton(button, query=True, annotation=True)
            if note in legacy_notes or note.startswith(("Material Assistant:", "Materializer:")):
                cmds.deleteUI(button)
        if tab == "MaterialAssistant" and not cmds.shelfLayout(tab, query=True, childArray=True):
            cmds.deleteUI(tab)
    if not cmds.shelfLayout("Materializer", exists=True):
        cmds.shelfLayout("Materializer", parent=shelves)
    cmds.shelfLayout("Materializer", edit=True, spacing=8)
    actions = (
        ("Run", "run", "run", "Run on selected meshes; ask for textures only when needed"),
        ("Undo", "undo", "undo", "Undo the last material batch"),
        ("Shading", "toggle_workspace", "workspace", "Switch between shading and scene workspaces"),
        ("Graph", "graph", "graph", "Graph selected meshes in the shading workspace"),
    )
    for label, action, icon_name, description in actions:
        if action == "toggle_workspace":
            cmds.separator(
                "MaterializerShelfDivider_" + action,
                parent="Materializer",
                style="shelf",
                horizontal=False,
                width=16,
            )
        button_icon = module.toolbar_icon(icon_name)
        image_path = target / ("materializer_" + action + ".png")
        if not button_icon.pixmap(64, 64).save(str(image_path)):
            raise RuntimeError("Could not save the " + label + " shelf icon.")
        cmds.shelfButton(
            "MaterializerShelf_" + action,
            parent="Materializer",
            enable=action not in ("apply", "undo"),
            label=label,
            image=str(image_path),
            style="iconOnly",
            width=42,
            height=38,
            annotation="Materializer: " + description,
            sourceType="python",
            command=prefix + f"materializer.launch({action!r})",
        )
    cmds.shelfTabLayout(shelves, edit=True, selectTab="Materializer")
    mel.eval("saveAllShelves " + json.dumps(shelves) + ";")
    print(f"Materializer {module.__version__} installed in {target}")
    return module


def onMayaDroppedPythonFile(*args):
    return install()


if __name__ == "__main__":
    install()
