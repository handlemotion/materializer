"""Check native material graph discovery without opening an interactive app."""

import sys
from pathlib import Path

import maya.standalone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from materializer_workspaces import material_graph_nodes

maya.standalone.initialize(name="python")
try:
    import maya.cmds as cmds

    body = cmds.polyCube(name="body_geo")[0]
    controller = cmds.circle(name="robot_ctrl")[0]
    shader = cmds.shadingNode("phong", asShader=True, name="body_mat")
    group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="bodySG")
    cmds.connectAttr(shader + ".outColor", group + ".surfaceShader")
    cmds.sets(body, edit=True, forceElement=group)
    texture = cmds.shadingNode("file", asTexture=True, name="body_baseColor")
    cmds.connectAttr(texture + ".outColor", shader + ".color")
    cmds.select(body + ".f[1:3]", controller, replace=True)
    original = cmds.ls(selection=True, long=True)
    before = set(cmds.ls(uuid=True))
    points = cmds.xform(body + ".vtx[*]", query=True, translation=True, objectSpace=True)
    shapes = cmds.listRelatives(body, shapes=True, fullPath=True)
    nodes = material_graph_nodes(cmds, shapes)
    assert {shader, group, texture}.issubset(nodes)
    assert not any(cmds.nodeType(node) in ("transform", "mesh", "joint") for node in nodes)
    assert cmds.ls(selection=True, long=True) == original
    assert set(cmds.ls(uuid=True)) == before
    assert cmds.xform(body + ".vtx[*]", query=True, translation=True, objectSpace=True) == points
    print(
        "PASS: material graph excludes rig nodes; selection, scene nodes and points unchanged.",
        flush=True,
    )
finally:
    maya.standalone.uninitialize()
