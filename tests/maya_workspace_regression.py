"""Check native scene selection in Maya standalone; no interactive app is used."""

import sys
from pathlib import Path
from unittest.mock import patch

import maya.standalone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from materializer_workspaces import graph_selection

maya.standalone.initialize(name="python")
try:
    import maya.cmds as cmds

    root = cmds.group(empty=True, name="robot_geo")
    body = cmds.polyCube(name="body_geo")[0]
    cmds.parent(body, root)
    controller = cmds.circle(name="robot_ctrl")[0]
    cmds.parent(controller, root)
    cmds.select(root, replace=True)
    before = set(cmds.ls(uuid=True))
    points = cmds.xform(body + ".vtx[*]", query=True, translation=True, objectSpace=True)

    def inspect_graph(**options):
        assert options == {"shaderNetworks": True}
        assert cmds.ls(selection=True, long=True) == ["|robot_geo|body_geo|body_geoShape"]

    with patch.object(cmds, "hyperShade", side_effect=inspect_graph):
        graph_selection(cmds, lambda: cmds.hyperShade(shaderNetworks=True))
    assert cmds.ls(selection=True, long=True) == ["|robot_geo"]
    assert set(cmds.ls(uuid=True)) == before
    assert cmds.xform(body + ".vtx[*]", query=True, translation=True, objectSpace=True) == points

    cmds.select("|robot_geo|body_geo.f[1:3]", "|robot_geo|robot_ctrl", replace=True)
    original = cmds.ls(selection=True, long=True)
    with patch.object(cmds, "hyperShade", side_effect=RuntimeError("Graph unavailable")):
        try:
            graph_selection(cmds, lambda: cmds.hyperShade(shaderNetworks=True))
        except RuntimeError as error:
            assert str(error) == "Graph unavailable"
        else:
            raise AssertionError("Expected graph error")
    assert cmds.ls(selection=True, long=True) == original
    assert set(cmds.ls(uuid=True)) == before
    print(
        "PASS: native group/component selections restored; no scene nodes or points changed.",
        flush=True,
    )
finally:
    maya.standalone.uninitialize()
