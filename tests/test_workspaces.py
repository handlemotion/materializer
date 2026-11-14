import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from materializer_workspaces import (
    PREVIOUS,
    SHADING,
    WorkspaceSwitch,
    build_layout,
    material_graph_nodes,
)


class Settings:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass


class NativeLayouts:
    """Model native named layouts, including unsaved edits and failed switches."""

    def __init__(self):
        self.active = "Animation"
        self.saved = {
            "Animation": "animation",
            "General": "general",
            "Rendering - Standard": "rendering",
        }
        self.live = "artist's unsaved layout"
        self.fail_target = None
        self.saves = 0

    def workspaceLayoutManager(self, **options):
        if options.get("query") and options.get("current"):
            return self.active
        if options.get("listLayouts"):
            return list(self.saved)
        if "modified" in options:
            return self.live != self.saved[self.active]
        if options.get("save"):
            self.saved[self.active] = self.live
            self.saves += 1
        elif "saveAs" in options:
            self.active = options["saveAs"]
            self.saved[self.active] = self.live
        elif "delete" in options:
            del self.saved[options["delete"]]
        elif "setCurrent" in options:
            target = options["setCurrent"]
            if target == self.fail_target:
                raise RuntimeError("Native layout could not load")
            self.live, self.active = self.saved[target], target
        else:
            raise AssertionError(options)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.native = NativeLayouts()
        self.settings = Settings()
        self.build = Mock(side_effect=lambda: setattr(self.native, "live", "shading layout"))
        self.switch = WorkspaceSwitch(self.native, self.settings, self.build)

    def test_round_trip_preserves_unsaved_scene_layout_and_custom_shading_layout(self):
        self.switch.enter()
        self.assertEqual(self.native.active, SHADING)
        self.native.live = "artist's shading arrangement"
        self.switch.leave()
        self.assertEqual(self.native.active, "Animation")
        self.assertEqual(self.native.live, "artist's unsaved layout")
        self.switch.enter()
        self.assertEqual(self.native.live, "artist's shading arrangement")
        self.assertEqual(self.build.call_count, 1)

    def test_first_build_cannot_overwrite_the_general_base(self):
        base_before = self.native.saved["General"]
        self.switch.enter()
        self.assertEqual(self.native.saved["General"], base_before)
        self.assertEqual(self.native.saved[SHADING], "shading layout")

    def test_failed_build_when_starting_in_base_restores_saved_artist_layout(self):
        self.native.active = "Rendering - Standard"
        self.native.live = "custom rendering layout"

        def fail_build():
            self.native.live = "partial layout"
            raise RuntimeError("Dock failed")

        self.build.side_effect = fail_build
        with self.assertRaisesRegex(RuntimeError, "Dock failed"):
            self.switch.enter()
        self.assertEqual(self.native.active, "Rendering - Standard")
        self.assertEqual(self.native.live, "custom rendering layout")
        self.assertNotIn(SHADING, self.native.saved)

    def test_repeated_entry_does_not_overwrite_return_target_or_rebuild(self):
        self.switch.enter()
        self.assertFalse(self.switch.enter())
        self.assertEqual(self.settings.value(PREVIOUS), "Animation")
        self.build.assert_called_once()

    def test_reloaded_module_can_return_without_session_state(self):
        self.switch.enter()
        reloaded = WorkspaceSwitch(self.native, self.settings, self.build)
        reloaded.leave()
        self.assertEqual(self.native.active, "Animation")

    def test_manual_workspace_change_is_not_undone_by_return(self):
        self.switch.enter()
        self.native.workspaceLayoutManager(setCurrent="General")
        self.assertFalse(self.switch.leave())
        self.switch.enter()
        self.switch.leave()
        self.assertEqual(self.native.active, "General")

    def test_build_failure_restores_previous_layout_and_allows_retry(self):
        self.build.side_effect = RuntimeError("Hypershade missing")
        with self.assertRaisesRegex(RuntimeError, "Hypershade missing"):
            self.switch.enter()
        self.assertEqual(self.native.active, "Animation")
        self.assertEqual(self.native.live, "artist's unsaved layout")
        self.assertNotIn(SHADING, self.native.saved)
        self.assertFalse(self.switch.switching)
        self.build.side_effect = lambda: setattr(self.native, "live", "shading layout")
        self.switch.enter()
        self.assertEqual(self.native.active, SHADING)

    def test_missing_previous_workspace_keeps_shading_open(self):
        self.switch.enter()
        del self.native.saved["Animation"]
        with self.assertRaisesRegex(RuntimeError, "previous workspace"):
            self.switch.leave()
        self.assertEqual(self.native.active, SHADING)

    def test_native_return_failure_keeps_shading_layout_available(self):
        self.switch.enter()
        self.native.live = "custom shading"
        self.native.fail_target = "Animation"
        with self.assertRaisesRegex(RuntimeError, "could not load"):
            self.switch.leave()
        self.assertEqual(self.native.active, SHADING)
        self.assertEqual(self.native.live, "custom shading")
        self.assertFalse(self.switch.switching)

    def test_reentrant_restore_does_not_start_another_switch(self):
        self.build.side_effect = self.switch.enter
        with self.assertRaisesRegex(RuntimeError, "already in progress"):
            self.switch.enter()
        self.assertEqual(self.native.active, "Animation")

    def test_missing_base_does_not_modify_any_workspace(self):
        del self.native.saved["General"]
        del self.native.saved["Rendering - Standard"]
        with self.assertRaisesRegex(RuntimeError, "required"):
            self.switch.enter()
        self.assertEqual(self.native.saves, 0)
        self.assertEqual(self.native.active, "Animation")


class GraphTests(unittest.TestCase):
    def test_material_graph_follows_surface_shader_and_not_rig_connections(self):
        connections = {
            "bodyShape": ["bodySG"],
            "screenShape": ["screenSG"],
            "bodySG.surfaceShader": ["body_mat"],
            "screenSG.surfaceShader": ["screen_mat"],
        }
        histories = {
            "body_mat": ["body_mat", "body_baseColor", "body_uv"],
            "screen_mat": ["screen_mat", "screen_baseColor", "screen_uv"],
        }
        cmds = SimpleNamespace(
            listConnections=lambda node, **options: connections[node],
            listHistory=lambda node, **options: histories[node],
            select=Mock(),
        )
        nodes = material_graph_nodes(cmds, ["bodyShape", "screenShape"])
        self.assertEqual(
            set(nodes),
            {
                "bodySG",
                "screenSG",
                "body_mat",
                "screen_mat",
                "body_baseColor",
                "body_uv",
                "screen_baseColor",
                "screen_uv",
            },
        )
        cmds.select.assert_not_called()

    def test_unassigned_mesh_has_no_graph_nodes(self):
        cmds = SimpleNamespace(listConnections=lambda *args, **options: None)
        self.assertEqual(material_graph_nodes(cmds, ["unassignedShape"]), [])


class DockCreationTests(unittest.TestCase):
    def test_material_graph_starts_docked_without_hypershade(self):
        self.check_dock(False)

    def test_retained_graph_host_is_reused(self):
        self.check_dock(True)

    def check_dock(self, retained):
        controls = {"MainPane": {}, "Outliner": {}, "AttributeEditor": {}}
        if retained:
            controls["MaterializerNodes"] = {}
        created = []

        def workspace_control(name, **options):
            if options.get("exists"):
                return name in controls
            if not options.get("edit"):
                created.append((name, options))
                controls[name] = dict(options)
            else:
                controls[name].update(options)

        cmds = SimpleNamespace(workspaceControl=workspace_control, getPanel=lambda **options: [])
        build_layout(cmds)
        self.assertEqual(len(created), 0 if retained else 1)
        if not retained:
            name, options = created[0]
            self.assertEqual(name, "MaterializerNodes")
            self.assertEqual(options["dockToControl"], ("MainPane", "right"))
            self.assertTrue(options["retain"])
            self.assertNotIn("hyperShade", options["uiScript"])
            compile(options["uiScript"], "Node Editor uiScript", "exec")
        self.assertTrue(controls["Outliner"]["collapse"])
        self.assertFalse(controls["AttributeEditor"]["collapse"])


if __name__ == "__main__":
    unittest.main()
