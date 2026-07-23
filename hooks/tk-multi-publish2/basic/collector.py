# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os

import sgtk


__author__ = "Adam Benson"
__contact__ = "https://www.linkedin.com/in/sleepdeprivedproductions/"
# based on original work by Diego Garcia Huerta and developed later by Adam Benson


HookBaseClass = sgtk.get_hook_baseclass()


SESSION_PUBLISHED_TYPE = "Toon Boom Harmony Project File"
TEMPLATE_PUBLISHED_TYPE = "Harmony Template"
PALETTE_PUBLISHED_TYPE = "Harmony Palette"
ELEMENT_PUBLISHED_TYPE = "Harmony Element"
CAMERA_DATA_PUBLISHED_TYPE = "Harmony Camera Data"


class HarmonySessionCollector(HookBaseClass):
    """
    Collector that operates on the Toon Boom Harmony session. Should inherit 
    from the basic collector hook.
    """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this collector expects to receive
        through the settings parameter in the process_current_session and
        process_file methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts as
        part of its environment configuration.
        """

        # grab any base class settings
        collector_settings = super(HarmonySessionCollector, self).settings or {}

        # settings specific to this collector
        harmony_session_settings = {
            "Work Template": {
                "type": "template",
                "default": None,
                "description": "Template path for artist work files. Should "
                "correspond to a template defined in "
                "templates.yml. If configured, is made available"
                "to publish plugins via the collected item's "
                "properties. ",
            },
            "Template Work Area": {
                "type": "template",
                "default": None,
                "description": "Template pointing at the Harmony work area "
                "folder (e.g. asset_work_area_harmony). Its "
                "'templates' subfolder is scanned for .tpl "
                "folders — created via Harmony's own Library "
                "panel drag-and-drop — that are available to "
                "publish as Harmony Templates.",
            },
        }

        # update the base settings with these settings
        collector_settings.update(harmony_session_settings)

        return collector_settings

    def process_current_session(self, settings, parent_item):
        """
        Analyzes the current session open in Toon Boom Harmony and parents a 
        subtree of items under the parent_item passed in.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance

        """

        # create an item representing the current Toon Boom Harmony session
        item = self.collect_current_harmony_session(settings, parent_item)

        # create an item for every publishable .tpl template found in the
        # work area's templates/ folder
        self.collect_harmony_templates(settings, parent_item)

        # create an item for every palette found in the current scene's own
        # palette-library folder
        self.collect_harmony_palettes(settings, parent_item)

        # create an item for every element found in the current scene's own
        # elements folder
        self.collect_harmony_elements(settings, parent_item)

        # create an item for every camera node found live in the scene
        self.collect_harmony_cameras(settings, parent_item)

    def get_export_path(self, settings):
        publisher = self.parent

        work_template = None
        work_template_setting = settings.get("Work Template")
        if work_template_setting:
            work_template = publisher.engine.get_template_by_name(work_template_setting.value)

            self.logger.debug("Work template defined for Toon Boom Harmony collection.")

        work_export_template = None
        work_export_template_setting = settings.get("Work Export Template")
        if work_export_template_setting:
            self.logger.debug(
                "Work Export template settings: %s" % work_export_template_setting
            )

            work_export_template = publisher.engine.get_template_by_name(
                work_export_template_setting.value
            )

            self.logger.debug("Work Export template defined for Toon Boom Harmony collection.")

        if work_export_template and work_template:
            path = publisher.engine.app.get_current_project_path()
            fields = work_template.get_fields(path)
            export_path = work_export_template.apply_fields(fields)

            self.logger.debug("Work Export Path is: %s " % export_path)

            return export_path

    def collect_current_harmony_session(self, settings, parent_item):
        """
        Creates an item that represents the current Toon Boom Harmony session.

        :param parent_item: Parent Item instance

        :returns: Item of type harmony.session
        """

        publisher = self.parent
        engine = sgtk.platform.current_engine()

        # get the path to the current file
        path = engine.app.get_current_project_path()

        # determine the display name for the item
        if path:
            file_info = publisher.util.get_file_path_components(path)
            display_name = file_info["filename"]
        else:
            display_name = "Current Toon Boom Harmony Session"

        # create the session item for the publish hierarchy
        session_item = parent_item.create_item(
            "harmony.session", "Toon Boom Harmony Session", display_name
        )

        # get the icon path to display for this item
        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "session.png")
        session_item.set_icon_from_path(icon_path)

        # if a work template is defined, add it to the item properties so
        # that it can be used by attached publish plugins
        work_template_setting = settings.get("Work Template")
        if work_template_setting:

            work_template = publisher.engine.get_template_by_name(work_template_setting.value)

            # store the template on the item for use by publish plugins. we
            # can't evaluate the fields here because there's no guarantee the
            # current session path won't change once the item has been created.
            # the attached publish plugins will need to resolve the fields at
            # execution time.
            session_item.properties["work_template"] = work_template
            session_item.properties["publish_type"] = SESSION_PUBLISHED_TYPE

            self.logger.debug("Work template defined for session.")

        self.logger.info("Collected current Toon Boom Harmony session")

        return session_item

    def collect_harmony_templates(self, settings, parent_item):
        """
        Creates one item per .tpl folder found in the current work area's
        'templates' subfolder. Artists create the .tpl itself via Harmony's
        own Library panel (drag nodes into the Library, then drag/save it
        out into this folder) — this method only discovers what's already
        there and offers it up to publish. Unlike the session item, a .tpl
        is a directory (data + PALETTES/ + a thumbnail) that IS the
        published item, not a leaf file inside a wrapper folder.

        :param parent_item: Parent Item instance
        :returns: list of items of type harmony.template
        """
        publisher = self.parent
        engine = sgtk.platform.current_engine()

        template_work_area_setting = settings.get("Template Work Area")
        if not template_work_area_setting or not template_work_area_setting.value:
            self.logger.debug(
                "No 'Template Work Area' configured — skipping Harmony "
                "template collection."
            )
            return []

        work_area_template = publisher.engine.get_template_by_name(
            template_work_area_setting.value
        )
        if not work_area_template:
            return []

        fields = engine.context.as_template_fields(work_area_template)
        work_area = work_area_template.apply_fields(fields)

        templates_folder = os.path.join(work_area, "templates")
        if not os.path.isdir(templates_folder):
            return []

        template_items = []
        for entry in sorted(os.listdir(templates_folder)):
            tpl_path = os.path.join(templates_folder, entry)
            if os.path.isdir(tpl_path) and entry.lower().endswith(".tpl"):
                display_name = os.path.splitext(entry)[0]

                template_item = parent_item.create_item(
                    "harmony.template", "Harmony Template", display_name
                )
                icon_path = os.path.join(
                    self.disk_location, os.pardir, "icons", "geometry.png"
                )
                template_item.set_icon_from_path(icon_path)

                template_item.properties["path"] = tpl_path
                template_item.properties["publish_type"] = TEMPLATE_PUBLISHED_TYPE

                template_items.append(template_item)
                self.logger.info("Collected Harmony template: %s" % entry)

        return template_items

    def collect_harmony_palettes(self, settings, parent_item):
        """
        Creates one item per .plt palette found in the current scene's own
        palette-library/ folder (a sibling of the .xstage, always present in
        a Harmony project's directory structure). Scoped to scene-local
        palettes only — shared job/environment-level palette libraries are
        not scanned.

        A scene's palette-library/ folder routinely holds several palettes
        at once (e.g. a default one, an unused leftover, one or two actual
        character palettes) and which one(s) should be published varies
        publish to publish, so unlike collect_harmony_templates() these
        items are NOT checked by default — see publish_palette.py's
        accept(). The artist picks per-publish which palette(s) to check in
        the Publish2 dialog.

        All palette items are nested under a single "Palettes" group item,
        collapsed by default (Item.expanded = False) — a flat list of many
        palettes/elements otherwise makes the Publish2 tree unwieldy to
        scan. The group is only created if at least one palette is found,
        and it has no publish plugin of its own (no item_filters match it),
        so it's purely organizational — skipped during actual publish,
        just a collapsible parent in the UI.

        :param parent_item: Parent Item instance
        :returns: list of items of type harmony.palette
        """
        engine = sgtk.platform.current_engine()

        current_path = engine.app.get_current_project_path()
        if not current_path or current_path == "Unknown":
            self.logger.debug(
                "No current Harmony project path — skipping palette collection."
            )
            return []

        palette_library_dir = os.path.join(
            os.path.dirname(current_path), "palette-library"
        )
        if not os.path.isdir(palette_library_dir):
            return []

        icon_path = os.path.join(
            self.disk_location, os.pardir, "icons", "texture.png"
        )

        palette_items = []
        palettes_group = None
        for entry in sorted(os.listdir(palette_library_dir)):
            plt_path = os.path.join(palette_library_dir, entry)
            if os.path.isfile(plt_path) and entry.lower().endswith(".plt"):
                if palettes_group is None:
                    # tk-multi-publish2's own built-in expand/collapse arrow
                    # never renders for this kind of item: publish_tree_
                    # widget.py's _build_item_tree_r() calls
                    # update_expand_indicator() (which decides visibility by
                    # counting the item's current Qt children) BEFORE the
                    # loop that adds sub-item children — only items with
                    # their own attached task (added earlier in that same
                    # function) have a child yet at that point. A pure
                    # group item like this, with sub-items but no task of
                    # its own, always fails that check. Confirmed as an
                    # upstream app bug, not fixable from a hook — so the
                    # name itself spells out the interaction instead of
                    # relying on an indicator that won't appear.
                    palettes_group = parent_item.create_item(
                        "harmony.palette_group", "Harmony Palettes",
                        "Palettes (double-click to expand)",
                    )
                    palettes_group.expanded = False
                    palettes_group.set_icon_from_path(icon_path)

                display_name = os.path.splitext(entry)[0]

                palette_item = palettes_group.create_item(
                    "harmony.palette", "Harmony Palette", display_name
                )
                palette_item.set_icon_from_path(icon_path)

                palette_item.properties["path"] = plt_path
                palette_item.properties["publish_type"] = PALETTE_PUBLISHED_TYPE

                palette_items.append(palette_item)
                self.logger.info("Collected Harmony palette: %s" % entry)

        return palette_items

    def collect_harmony_elements(self, settings, parent_item):
        """
        Creates one item per element found in the current scene's own
        elements/ folder (a sibling of the .xstage, like palette-library/).
        An element is a subfolder (e.g. elements/Shotgun_Banner/) that can
        hold one or several drawings/timings (e.g. a turnaround's multiple
        angles) plus a Harmony-managed .thumbnails/ cache. Scoped to
        scene-local elements only.

        Like palette-library/, a scene's elements/ folder accumulates
        unused/WIP subfolders over a project's life, so these items are
        NOT checked by default — see publish_element.py's accept(). The
        artist picks per-publish which element(s) to check.

        All element items are nested under a single "Elements" group item,
        collapsed by default (Item.expanded = False) — same reasoning as
        collect_harmony_palettes()'s "Palettes" group.

        :param parent_item: Parent Item instance
        :returns: list of items of type harmony.element
        """
        engine = sgtk.platform.current_engine()

        current_path = engine.app.get_current_project_path()
        if not current_path or current_path == "Unknown":
            self.logger.debug(
                "No current Harmony project path — skipping element collection."
            )
            return []

        elements_dir = os.path.join(os.path.dirname(current_path), "elements")
        if not os.path.isdir(elements_dir):
            return []

        icon_path = os.path.join(
            self.disk_location, os.pardir, "icons", "publish.png"
        )

        element_items = []
        elements_group = None
        for entry in sorted(os.listdir(elements_dir)):
            element_path = os.path.join(elements_dir, entry)
            if os.path.isdir(element_path):
                if elements_group is None:
                    # see the matching comment in collect_harmony_palettes()
                    # — the built-in expand arrow never renders for a pure
                    # group item (confirmed upstream app bug, not fixable
                    # from a hook), so the name spells out the interaction.
                    elements_group = parent_item.create_item(
                        "harmony.element_group", "Harmony Elements",
                        "Elements (double-click to expand)",
                    )
                    elements_group.expanded = False
                    elements_group.set_icon_from_path(icon_path)

                element_item = elements_group.create_item(
                    "harmony.element", "Harmony Element", entry
                )
                element_item.set_icon_from_path(icon_path)

                element_item.properties["path"] = element_path
                element_item.properties["publish_type"] = ELEMENT_PUBLISHED_TYPE

                element_items.append(element_item)
                self.logger.info("Collected Harmony element: %s" % entry)

        return element_items

    def collect_harmony_cameras(self, settings, parent_item):
        """
        Creates one item per camera node found LIVE in the current scene
        (unlike the palette/element collectors, this queries Harmony
        directly rather than scanning disk — there's no on-disk
        equivalent of "the scene's cameras").

        Uses the existing generic GET_NODES_OF_TYPE RPC
        (engine.app.get_nodes_of_type) with node type "CAMERA" — NOT
        LIVE-VERIFIED that this is the correct Harmony node-type string
        for this version; if it isn't, this call safely returns an empty
        list rather than erroring, so an unconfirmed guess here can't
        break collection of anything else.

        Unlike palettes/elements (where a scene often has several stale
        ones and nothing should auto-publish), a scene's camera count is
        usually exactly one and there's no "which one" ambiguity, so a
        single camera is collected directly under the session rather than
        wrapped in a redundant single-item group; multiple cameras (rare)
        still get grouped, matching the standing convention.

        :param parent_item: Parent Item instance
        :returns: list of items of type harmony.camera_data
        """
        engine = sgtk.platform.current_engine()

        try:
            camera_nodes = engine.app.get_nodes_of_type(["CAMERA"]) or []
        except Exception as e:
            self.logger.debug("Could not query camera nodes: %s" % e)
            return []

        if not camera_nodes:
            return []

        icon_path = os.path.join(
            self.disk_location, os.pardir, "icons", "publish.png"
        )

        if len(camera_nodes) > 1:
            cameras_parent = parent_item.create_item(
                "harmony.camera_data_group", "Harmony Camera Data",
                "Camera Data (double-click to expand)",
            )
            cameras_parent.expanded = False
            cameras_parent.set_icon_from_path(icon_path)
        else:
            cameras_parent = parent_item

        camera_items = []
        for camera_node in camera_nodes:
            display_name = camera_node.rsplit("/", 1)[-1]

            camera_item = cameras_parent.create_item(
                "harmony.camera_data", "Harmony Camera Data", display_name
            )
            camera_item.set_icon_from_path(icon_path)

            camera_item.properties["camera_node"] = camera_node
            camera_item.properties["publish_type"] = CAMERA_DATA_PUBLISHED_TYPE

            camera_items.append(camera_item)
            self.logger.info("Collected Harmony camera: %s" % camera_node)

        return camera_items
