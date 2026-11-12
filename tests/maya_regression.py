"""Check material assignment scope and Undo in a disposable Maya scene."""

import base64
import sys
import tempfile
from pathlib import Path

import maya.standalone

ROOT = Path(__file__).resolve().parents[1]


def check():
    import maya.cmds as cmds

    import materializer
    from materializer_core import TextureIndex

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aCKsAAAAASUVORK5CYII="
        )
        files = []
        for role in ("BaseColor", "Normal", "Roughness"):
            path = root / f"Fixture_{role}.png"
            path.write_bytes(png)
            files.append(path)
        selected = cmds.polyCube(name="selectedProp")[0]
        other = cmds.polyCube(name="otherProp")[0]
        shader = cmds.shadingNode("phong", asShader=True, name="Fixture")
        group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="FixtureSG")
        cmds.connectAttr(shader + ".outColor", group + ".surfaceShader")
        cmds.sets([selected, other], edit=True, forceElement=group)
        file = cmds.shadingNode("file", asTexture=True)
        cmds.setAttr(file + ".fileTextureName", str(files[0]), type="string")
        cmds.connectAttr(file + ".outColor", shader + ".color")
        cmds.select(selected, replace=True)
        row = materializer.inspect_materials(materializer.scene_meshes(True))[0]
        plan = materializer.plan_material(row, TextureIndex(files))
        assert plan["state"] == "Ready", plan
        token, changes = materializer.apply_plans([plan])
        assert len(changes) == 1
        shape = cmds.listRelatives(selected, shapes=True)[0]
        untouched = cmds.listRelatives(other, shapes=True)[0]
        assert cmds.listConnections(untouched, type="shadingEngine") == [group]
        assert group not in cmds.listConnections(shape, type="shadingEngine")
        created = changes[0]["new"]
        base = cmds.listConnections(created + ".baseColor", source=True, destination=False)[0]
        assert "sRGB" in cmds.getAttr(base + ".colorSpace")
        normal = cmds.listConnections(created + ".normalCamera", source=True, destination=False)[0]
        normal_file = cmds.listConnections(normal + ".input", source=True, destination=False)[0]
        assert cmds.getAttr(normal_file + ".colorSpace") == "Raw"
        assert cmds.undoInfo(query=True, undoName=True) == token
        cmds.undo()
        assert cmds.listConnections(shape, type="shadingEngine") == [group]
        print(
            "PASS: selected mesh shaded, shared material on other mesh preserved, color spaces correct, Undo restored assignment",
            flush=True,
        )


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    maya.standalone.initialize(name="python")
    try:
        check()
    finally:
        maya.standalone.uninitialize()
