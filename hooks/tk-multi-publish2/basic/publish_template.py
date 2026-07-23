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

import sgtk
from sgtk.util.filesystem import copy_folder


HookBaseClass = sgtk.get_hook_baseclass()


class HarmonyTemplatePublishPlugin(HookBaseClass):
    """
    Plugin for publishing a Harmony .tpl (Library template) as a Harmony
    Template PublishedFile, so it can be loaded into other scenes via the
    Loader.

    A .tpl is created by the artist using Harmony's own Library panel
    (drag nodes into the Library, save into the work area's templates/
    folder), and collected by collector.py's collect_harmony_templates().
    This plugin only handles getting the already-created folder published.
    """

    @property
    def icon(self):
        """
        Path to a png icon on disk
        """
        return os.path.join(self.disk_location, os.pardir, "icons", "geometry.png")

    @property
    def name(self):
        """
        One line display name describing the plugin
        """
        return "Publish Harmony Template"

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """
        return """
        Publishes a Harmony .tpl (a reusable node/asset bundle exported via
        Harmony's own Library panel) to ShotGrid. Other artists can then
        load it into their own scenes via the <b>Loader</b>.<br><br>

        A .tpl is a folder, not a single file — the whole folder (template
        data, PALETTES/, thumbnail) is copied to the publish location as a
        unit.
        """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.
        """

        # inherit the settings from the base publish plugin
        base_settings = super(HarmonyTemplatePublishPlugin, self).settings or {}

        harmony_template_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for the published .tpl "
                "folder. Should correspond to a template "
                "defined in templates.yml (e.g. "
                "harmony_asset_template_publish).",
            }
        }

        base_settings.update(harmony_template_settings)

        return base_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.
        """
        return ["harmony.template"]

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
                "No 'Publish Template' configured for Harmony Template items."
            )
            return {"accepted": False}

        item.properties["publish_template"] = publish_template

        return {"accepted": True, "checked": True}

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish.
        """
        path = item.properties.get("path")

        if not path or not os.path.isdir(path):
            error_msg = "Harmony template folder no longer exists: %s" % path
            self.logger.error(error_msg)
            raise Exception(error_msg)

        publish_template = item.properties["publish_template"]

        engine = sgtk.platform.current_engine()
        fields = engine.context.as_template_fields(publish_template)
        fields["name"] = os.path.splitext(os.path.basename(path))[0]

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
        item.properties["publish_name"] = fields["name"]
        item.properties["publish_type"] = "Harmony Template"

        return super(HarmonyTemplatePublishPlugin, self).validate(settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.
        """
        source_path = item.properties["path"]
        publish_path = item.properties["publish_path"]

        self.logger.debug(
            "Copying Harmony template folder '%s' -> '%s'" % (source_path, publish_path)
        )

        publish_folder = os.path.dirname(publish_path)
        if not os.path.exists(publish_folder):
            os.makedirs(publish_folder)

        # copy the whole .tpl folder as a unit — the base class's own
        # copy-to-publish step only handles single files and would break
        # (or silently no-op) on a directory, so we do it ourselves here.
        copy_folder(source_path, publish_path, folder_permissions=0o775)

        # path now equals publish_path, so the base class's own
        # _copy_local_to_publish() step becomes a no-op instead of
        # attempting (and failing) to copy the folder a second time.
        item.properties["path"] = publish_path

        # let the base class register the publish in ShotGrid
        super(HarmonyTemplatePublishPlugin, self).publish(settings, item)

    def finalize(self, settings, item):
        """
        Execute the finalization pass.
        """
        super(HarmonyTemplatePublishPlugin, self).finalize(settings, item)
