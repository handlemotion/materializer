"""Exercise Run, scoped assignment and Undo with Maya and the real index worker."""

import base64
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import maya.standalone
from PySide6 import QtCore, QtWidgets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
maya.standalone.initialize(name="python")
try:
    import maya.cmds as cmds

    import materializer as m

    cmds.loadPlugin("mtoa", quiet=True)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        settings = QtCore.QSettings(str(root / "settings.ini"), QtCore.QSettings.Format.IniFormat)
        m.preferences = lambda: settings
        textures = root / "sourceimages"
        textures.mkdir()
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aCKsAAAAASUVORK5CYII="
        )
        for role in ("BaseColor", "Normal", "Roughness"):
            (textures / f"Fixture_{role}.png").write_bytes(png)
        (root / "scenes").mkdir()
        cmds.file(rename=str(root / "scenes" / "fixture.ma"))
        selected = cmds.polyCube(name="selectedProp")[0]
        other = cmds.polyCube(name="otherProp")[0]
        shader = cmds.shadingNode("phong", asShader=True, name="Fixture")
        group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="FixtureSG")
        cmds.connectAttr(shader + ".outColor", group + ".surfaceShader")
        cmds.sets([selected, other], edit=True, forceElement=group)
        file = cmds.shadingNode("file", asTexture=True)
        cmds.setAttr(
            file + ".fileTextureName", str(textures / "Fixture_BaseColor.png"), type="string"
        )
        cmds.connectAttr(file + ".outColor", shader + ".color")
        cmds.select(selected, replace=True)
        points = cmds.xform(selected + ".vtx[*]", query=True, translation=True, objectSpace=True)
        window = m.Materializer()

        def wait_for_run():
            deadline = time.monotonic() + 15
            while (window.worker and window.worker.isRunning()) or window._run_requested:
                assert time.monotonic() < deadline, window.status.text()
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()

        def assigned(node):
            return m.inspect_materials(cmds.listRelatives(node, shapes=True, fullPath=True))[0]

        window.run()
        wait_for_run()
        assert assigned(selected)["type"] == "aiStandardSurface", window.status.text()
        assert assigned(other)["shader"] == shader
        assert (
            cmds.xform(selected + ".vtx[*]", query=True, translation=True, objectSpace=True)
            == points
        )
        assert window.undo_last()
        wait_for_run()
        assert assigned(selected)["shader"] == shader
        assert assigned(other)["shader"] == shader

        window.run()
        cmds.select(other, replace=True)
        wait_for_run()
        assert assigned(selected)["shader"] == shader
        assert assigned(other)["shader"] == shader
        assert "Selection changed" in window.status.text()

        cancelled = m.Materializer()
        cmds.select(selected, replace=True)
        cancelled.run()
        cancelled.close()
        deadline = time.monotonic() + 15
        while cancelled.worker and cancelled.worker.isRunning():
            assert time.monotonic() < deadline
            app.processEvents()
            time.sleep(0.005)
        app.processEvents()
        assert assigned(selected)["shader"] == shader
        assert not cancelled._run_requested

        basic = cmds.shadingNode("openPBRSurface", asShader=True, name="Basic")
        cmds.connectAttr(basic + ".outColor", group + ".surfaceShader", force=True)
        cmds.select(selected, replace=True)
        with patch.object(
            QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(textures)
        ):
            window.run()
            wait_for_run()
        assert assigned(selected)["type"] == "aiStandardSurface", window.status.text()
        assert assigned(other)["shader"] == basic
        assert (
            cmds.xform(selected + ".vtx[*]", query=True, translation=True, objectSpace=True)
            == points
        )
        window.close()
        window.deleteLater()
        app.processEvents()
        print(
            "PASS: Run applies scoped matches, Undo restores, stale selection aborts, basic shader accepts textures.",
            flush=True,
        )
finally:
    maya.standalone.uninitialize()
