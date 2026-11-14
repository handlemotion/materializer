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
        # A rig screen can share Maya's default material with the entire rig.
        rig = cmds.polyCube(name="rigScreen")[0]
        sibling = cmds.polyCube(name="rigBody")[0]
        cmds.select(clear=True)
        joint = cmds.joint(name="screenJoint")
        skin = cmds.skinCluster(joint, rig, toSelectedBones=True)[0]
        rig_shape = cmds.listRelatives(rig, shapes=True, noIntermediate=True, fullPath=True)[0]
        sibling_shape = cmds.listRelatives(sibling, shapes=True, fullPath=True)[0]
        original_history = cmds.listHistory(rig_shape)
        cmds.sets([rig, sibling], edit=True, forceElement="initialShadingGroup")
        default_shader = cmds.listConnections("initialShadingGroup.surfaceShader", s=True, d=False)[
            0
        ]
        row = materializer.inspect_materials([rig_shape])[0]
        assert row["shader"] == default_shader
        assert materializer.plan_material(row, TextureIndex(files))["state"] == "Needs textures"
        plan = materializer.plan_texture_set(row, TextureIndex(files), "fixture")
        assert plan["state"] == "Ready", plan
        token, changes = materializer.apply_plans([plan])
        assert len(changes) == 1
        assert "initialShadingGroup" not in cmds.listConnections(rig_shape, type="shadingEngine")
        assert "initialShadingGroup" in cmds.listConnections(sibling_shape, type="shadingEngine")
        assert cmds.listConnections("initialShadingGroup.surfaceShader", s=True, d=False) == [
            default_shader
        ]
        assert cmds.objExists(skin)
        assert cmds.listHistory(rig_shape) == original_history
        cmds.undo()
        assert "initialShadingGroup" in cmds.listConnections(rig_shape, type="shadingEngine")
        assert cmds.objExists(skin)

        # Authored OpenPBR networks remain untouched unless a texture set is chosen.
        modern = cmds.shadingNode("openPBRSurface", asShader=True, name="AuthoredFixture")
        group = cmds.sets(
            renderable=True, noSurfaceShader=True, empty=True, name="AuthoredFixtureSG"
        )
        cmds.connectAttr(modern + ".outColor", group + ".surfaceShader")
        cmds.sets([rig, sibling], edit=True, forceElement=group)
        tex = cmds.shadingNode("file", asTexture=True)
        cmds.setAttr(tex + ".fileTextureName", str(files[0]), type="string")
        cmds.connectAttr(tex + ".outColor", modern + ".baseColor")
        row = materializer.inspect_materials([rig_shape])[0]
        assert materializer.plan_material(row, TextureIndex(files))["state"] == "Existing shader"
        plan = materializer.plan_texture_set(row, TextureIndex(files), "fixture")
        assert plan["state"] == "Ready", plan
        token, changes = materializer.apply_plans([plan])
        assert cmds.listConnections(modern + ".baseColor", s=True, d=False) == [tex]
        assert cmds.listConnections(sibling_shape, type="shadingEngine") == [group]
        cmds.undo()
        assert cmds.listConnections(rig_shape, type="shadingEngine") == [group]
        print(
            "PASS: default rig material replaceable, skin history unchanged, authored OpenPBR preserved, scoped replacement and Undo work",
            flush=True,
        )
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
