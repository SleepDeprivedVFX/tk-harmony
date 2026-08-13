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
import time

import sgtk


HookBaseClass = sgtk.get_hook_baseclass()


# TODO: this retry helper is duplicated in publish_session.py/
# publish_element.py/publish_palette.py/publish_template.py — all four call
# the base publish_file.py hook's validate(), which is where this failure
# mode lives.
def _retry_on_shotgun_connectivity_error(fn, logger, max_attempts=3, delay_seconds=3):
    """
    Calls fn() (a zero-arg callable), retrying up to max_attempts times if it
    raises sgtk.util.ShotgunPublishError — a live ShotGrid API failure
    inside the base class validate()'s conflict check, confirmed live as a
    transient stale-connection issue rather than a real validation result.
    See publish_session.py for the full writeup.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except sgtk.util.ShotgunPublishError as e:
            if attempt >= max_attempts:
                logger.error(
                    "ShotGrid connectivity error persisted after %d "
                    "attempt(s): %s" % (max_attempts, e)
                )
                raise
            logger.warning(
                "ShotGrid connectivity error (attempt %d/%d): %s -- "
                "retrying in %ds..." % (attempt, max_attempts, e, delay_seconds)
            )
            time.sleep(delay_seconds)


class HarmonyPalettePublishPlugin(HookBaseClass):
    """
    Plugin for publishing a Harmony .plt palette (found in the current
    scene's own palette-library/ folder) as a Harmony Palette PublishedFile,
    so it can be reused via the Loader.

    A .plt is a single file (unlike a .tpl, which is a whole folder), so —
    unlike publish_template.py — no manual copy override is needed; the
    base publish plugin's own copy-to-publish step handles it directly.
    """

    @property
    def icon(self):
        """
        Path to a png icon on disk
        """
        return os.path.join(self.disk_location, os.pardir, "icons", "texture.png")

    @property
    def name(self):
        """
        One line display name describing the plugin
        """
        return "Publish Harmony Palette"

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """
        return """
        Publishes a Harmony .plt palette from the current scene's own
        palette-library folder to ShotGrid. Other artists can then load it
        into their own scenes via the <b>Loader</b>.<br><br>

        Only scene-local palettes are scanned (not shared job/environment
        palette libraries). A scene's palette-library folder often holds
        several palettes at once, so items are <b>unchecked by default</b>
        &mdash; pick the specific palette(s) to publish each time.
        """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.
        """

        # inherit the settings from the base publish plugin
        base_settings = super(HarmonyPalettePublishPlugin, self).settings or {}

        harmony_palette_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for the published .plt "
                "palette. Should correspond to a template "
                "defined in templates.yml (e.g. "
                "harmony_asset_palette_publish).",
            }
        }

        base_settings.update(harmony_palette_settings)

        return base_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.
        """
        return ["harmony.palette"]

    def accept(self, settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin.
        """
        path = item.properties.get("path")
        if not path or not os.path.isfile(path):
            return {"accepted": False}

        publish_template_setting = settings.get("Publish Template")
        publish_template = None
        if publish_template_setting and publish_template_setting.value:
            publish_template = self.parent.engine.get_template_by_name(
                publish_template_setting.value
            )

        if not publish_template:
            self.logger.debug(
                "No 'Publish Template' configured for Harmony Palette items."
            )
            return {"accepted": False}

        item.properties["publish_template"] = publish_template

        # unchecked by default — a scene's palette-library folder routinely
        # holds several palettes at once (default/unused/character ones),
        # and which one(s) should publish varies every time, so the artist
        # must deliberately opt in per palette per publish.
        return {"accepted": True, "checked": False}

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish.
        """
        path = item.properties.get("path")

        if not path or not os.path.isfile(path):
            error_msg = "Harmony palette file no longer exists: %s" % path
            self.logger.error(error_msg)
            raise Exception(error_msg)

        publish_template = item.properties["publish_template"]

        # the {name} template key is filter_by: alphanumeric (letters and
        # digits only) — real palette filenames routinely contain
        # underscores (e.g. an artist named it after their scene, like
        # "Baguette_MDL_v001"), which raises a TankError from
        # apply_fields() if used as-is. Same class of bug as Session 4's
        # render_fields["name"] issue. Strip to alphanumeric for the actual
        # path segment, but keep the original, readable filename as the
        # ShotGrid-facing publish name.
        raw_name = os.path.splitext(os.path.basename(path))[0]
        engine = sgtk.platform.current_engine()
        fields = engine.context.as_template_fields(publish_template)
        fields["name"] = re.sub(r"[^A-Za-z0-9]", "", raw_name) or "palette"

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
        item.properties["publish_type"] = "Harmony Palette"

        return _retry_on_shotgun_connectivity_error(
            lambda: super(HarmonyPalettePublishPlugin, self).validate(settings, item),
            self.logger,
        )

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.
        """
        # a .plt is a single file — the base class's own
        # _copy_local_to_publish() step handles copying item.properties
        # ["path"] to the resolved publish_path directly, no manual copy
        # needed here (unlike publish_template.py's directory case).
        super(HarmonyPalettePublishPlugin, self).publish(settings, item)

    def finalize(self, settings, item):
        """
        Execute the finalization pass.
        """
        super(HarmonyPalettePublishPlugin, self).finalize(settings, item)
