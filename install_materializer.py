"""Drag into Maya to install or update Materializer."""

import builtins
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

MODULES = ("materializer_core.py", "materializer.py")


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
    from PySide6 import QtCore, QtGui, QtSvg

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

    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><g fill="none" stroke="#b7d4fa" stroke-width="1.8" stroke-linecap="round"><circle cx="16" cy="16" r="11"/><path d="M16 5c-7 6-7 16 0 22M16 5c7 6 7 16 0 22M5 16h22"/></g></svg>'
    image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode())).render(painter)
    painter.end()
    icon = target / "materializer.png"
    if not image.save(str(icon)):
        raise RuntimeError("Could not save the Materializer shelf icon.")

    folder = str(target)
    if folder in sys.path:
        sys.path.remove(folder)
    sys.path.insert(0, folder)
    for name in ("materializer", "materializer_core"):
        sys.modules.pop(name, None)
    importlib.invalidate_caches()
    module = importlib.import_module("materializer")
    legacy_module = target.parent / "material_assistant_tool" / "material_assistant.py"
    if legacy_module.is_file():
        shim = f"import sys\np={folder!r}\nif p not in sys.path: sys.path.insert(0,p)\nfrom materializer import launch, show, toolbar, shutdown\n\ndef restore_workspace():\n    import maya.cmds as cmds\n    from PySide6 import QtCore\n    def remove_legacy_dock():\n        name='MaterialAssistantQuickBarWorkspaceControl'\n        if cmds.workspaceControl(name,query=True,exists=True): cmds.deleteUI(name)\n    QtCore.QTimer.singleShot(0,remove_legacy_dock)\n    return launch()\n"
        legacy_module.write_text(shim)
        sys.modules.pop("material_assistant", None)
    command = f"import sys; p={folder!r}; sys.path.insert(0,p) if p not in sys.path else None; import materializer; materializer.launch()"
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
            if cmds.objectTypeUI(button) != "shelfButton":
                continue
            note = cmds.shelfButton(button, query=True, annotation=True)
            if note in legacy_notes or note.startswith(("Material Assistant:", "Materializer:")):
                cmds.deleteUI(button)
        if tab == "MaterialAssistant" and not cmds.shelfLayout(tab, query=True, childArray=True):
            cmds.deleteUI(tab)
    if not cmds.shelfLayout("Materializer", exists=True):
        cmds.shelfLayout("Materializer", parent=shelves)
    cmds.shelfButton(
        parent="Materializer",
        label="Materializer",
        image=str(icon),
        annotation="Materializer: open toolbar",
        sourceType="python",
        command=command,
    )
    cmds.shelfTabLayout(shelves, edit=True, selectTab="Materializer")
    mel.eval("saveAllShelves " + json.dumps(shelves) + ";")
    print(f"Materializer {module.__version__} installed in {target}")
    return module.launch() if open_toolbar else module


def onMayaDroppedPythonFile(*args):
    return install()


if __name__ == "__main__":
    install()
