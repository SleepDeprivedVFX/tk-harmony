# Copyright (c) 2026 SleepDeprivedVFX
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import re

import sgtk
from sgtk.util.filesystem import copy_folder


HookBaseClass = sgtk.get_hook_baseclass()


class HarmonyElementPublishPlugin(HookBaseClass):
    """
    Plugin for publishing a Harmony element (found in the current scene's
    own elements/ folder) as a Harmony Element PublishedFile.

    An element is a folder — e.g. elements/Shotgun_Banner/ — that can hold
    one or several drawings/timings (a turnaround's multiple angles, a
    prop's single drawing, etc.), plus a Harmony-managed .thumbnails/
    cache. Like publish_template.py's .tpl handling, the whole folder is
    copied as a unit; unlike publish_template.py, .thumbnails/ is
    deliberately excluded since it's regenerable cache data, not asset
    content.
    """

    @property
    def icon(self):
        """
        Path to a png icon on disk
        """
        return os.path.join(self.disk_location, os.pardir, "icons", "publish.png")

    @property
    def name(self):
        """
        One line display name describing the plugin
        """
        return "Publish Harmony Element"

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """
        return """
        Publishes a Harmony element (a drawing or set of drawings, e.g. a
        turnaround or a prop) from the current scene's own elements folder
        to ShotGrid, so it can be reused in other scenes.<br><br>

        Only scene-local elements are scanned (not shared job/environment
        libraries). Harmony's regenerable .thumbnails cache is not
        published. A scene's elements folder often holds several elements
        at once, so items are <b>unchecked by default</b> &mdash; pick the
        specific element(s) to publish each time.
        """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.
        """

        # inherit the settings from the base publish plugin
        base_settings = super(HarmonyElementPublishPlugin, self).settings or {}

        harmony_element_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for the published element "
                "folder. Should correspond to a template "
                "defined in templates.yml (e.g. "
                "harmony_asset_element_publish).",
            }
        }

        base_settings.update(harmony_element_settings)

        return base_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.
        """
        return ["harmony.element"]

    def accept(self, settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin.
        """
        path = item.properties.get("path")
        if not path or not os.path.isdir(path):
            return {"accepted": False}

        publish_template_setting = settings.get("Publish Template")
        publish_template = None
        if publish_template_setting and publish_template_setting.value:
            publish_template = self.parent.engine.get_template_by_name(
                publish_template_setting.value
            )

        if not publish_template:
            self.logger.debug(
                "No 'Publish Template' configured for Harmony Element items."
            )
            return {"accepted": False}

        item.properties["publish_template"] = publish_template

        # unchecked by default — a scene's elements folder routinely holds
        # several elements at once, and which one(s) should publish varies
        # every time, so the artist must deliberately opt in per publish.
        return {"accepted": True, "checked": False}

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish.
        """
        path = item.properties.get("path")

        if not path or not os.path.isdir(path):
            error_msg = "Harmony element folder no longer exists: %s" % path
            self.logger.error(error_msg)
            raise Exception(error_msg)

        publish_template = item.properties["publish_template"]

        # the {name} template key is filter_by: alphanumeric — element
        # folder names can contain underscores just like the palette
        # publisher's did, which raised a TankError from apply_fields().
        # Strip to alphanumeric for the path segment, but keep the
        # original, readable folder name as the ShotGrid-facing publish
        # name.
        raw_name = os.path.basename(os.path.normpath(path))
        engine = sgtk.platform.current_engine()
        fields = engine.context.as_template_fields(publish_template)
        fields["name"] = re.sub(r"[^A-Za-z0-9]", "", raw_name) or "element"

        # find the next available version so a re-publish never silently
        # overwrites an earlier one
        version = 1
        while True:
            fields["version"] = version
            publish_path = publish_template.apply_fields(fields)
            if not os.path.exists(publish_path):
                break
            version += 1

        item.properties["publish_path"] = publish_path
        item.properties["publish_version"] = version
        item.properties["publish_name"] = raw_name
        item.properties["publish_type"] = "Harmony Element"

        return super(HarmonyElementPublishPlugin, self).validate(settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.
        """
        source_path = item.properties["path"]
        publish_path = item.properties["publish_path"]

        self.logger.debug(
            "Copying Harmony element folder '%s' -> '%s'" % (source_path, publish_path)
        )

        publish_folder = os.path.dirname(publish_path)
        if not os.path.exists(publish_folder):
            os.makedirs(publish_folder)

        # copy the whole element folder as a unit — same reasoning as
        # publish_template.py's .tpl handling — but skip .thumbnails/,
        # Harmony's own regenerable preview cache, not real asset data.
        copy_folder(
            source_path, publish_path, folder_permissions=0o775,
            skip_list=[".thumbnails"],
        )

        # path now equals publish_path, so the base class's own
        # _copy_local_to_publish() step becomes a no-op instead of
        # attempting (and failing) to copy the folder a second time.
        item.properties["path"] = publish_path

        # let the base class register the publish in ShotGrid
        super(HarmonyElementPublishPlugin, self).publish(settings, item)

    def finalize(self, settings, item):
        """
        Execute the finalization pass.
        """
        super(HarmonyElementPublishPlugin, self).finalize(settings, item)
