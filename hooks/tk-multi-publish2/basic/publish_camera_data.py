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
import json

import sgtk
from sgtk.util.filesystem import ensure_folder_exists


HookBaseClass = sgtk.get_hook_baseclass()


class HarmonyCameraDataPublishPlugin(HookBaseClass):
    """
    Plugin for publishing a Harmony camera's transform data.

    Exports two files per camera: a JSON file (source of truth — full
    per-frame camera + driving-Peg transform data, exactly what Harmony
    reported) and a Nuke .chan file (frame tx ty tz rx ry rz per line,
    Nuke's own native Camera > Import chan file format — no plugin needed
    on the Nuke side).

    NOT LIVE-VERIFIED: this is the first pass at Harmony camera data in
    this codebase. The .chan conversion in particular is a first-pass
    approximation — Harmony's camera model is 2.5D (single Z-axis
    rotation), so only rz is populated; rx/ry are always 0. Expect this
    to need at least one iteration once tested against a real Nuke comp,
    same as the render pipeline's Write node redirect did.
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
        return "Publish Harmony Camera Data"

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """
        return """
        Exports a Harmony camera's transform animation as a JSON file
        (source of truth) and a Nuke .chan file (importable directly via
        Nuke's Camera > Import chan file, no plugin required).<br><br>

        <b>First pass, not yet validated against a real comp</b> &mdash;
        Harmony's camera data model hasn't been exercised in this pipeline
        before. The .chan file only populates Z-axis rotation (rx/ry are
        always 0), and the underlying attribute names are unconfirmed for
        this Harmony version. Maya (FBX) and After Effects export are not
        yet supported.
        """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.
        """

        # inherit the settings from the base publish plugin
        base_settings = super(HarmonyCameraDataPublishPlugin, self).settings or {}

        harmony_camera_data_settings = {
            "Camera Data JSON Template": {
                "type": "template",
                "default": None,
                "description": "Template path for the published camera "
                "data JSON file. Should correspond to a "
                "template defined in templates.yml (e.g. "
                "harmony_asset_camera_data_json).",
            },
            "Camera Data Chan Template": {
                "type": "template",
                "default": None,
                "description": "Template path for the published Nuke "
                ".chan file. Should correspond to a template "
                "defined in templates.yml (e.g. "
                "harmony_asset_camera_data_chan).",
            },
        }

        base_settings.update(harmony_camera_data_settings)

        return base_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.
        """
        return ["harmony.camera_data"]

    def accept(self, settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin.
        """
        camera_node = item.properties.get("camera_node")
        if not camera_node:
            return {"accepted": False}

        json_template_setting = settings.get("Camera Data JSON Template")
        chan_template_setting = settings.get("Camera Data Chan Template")
        json_template = None
        chan_template = None
        if json_template_setting and json_template_setting.value:
            json_template = self.parent.engine.get_template_by_name(
                json_template_setting.value
            )
        if chan_template_setting and chan_template_setting.value:
            chan_template = self.parent.engine.get_template_by_name(
                chan_template_setting.value
            )

        if not json_template or not chan_template:
            self.logger.debug(
                "Camera Data JSON/Chan Template not fully configured for "
                "Harmony Camera Data items."
            )
            return {"accepted": False}

        item.properties["json_template"] = json_template
        item.properties["chan_template"] = chan_template

        # a scene usually has exactly one camera, so — unlike palettes/
        # elements — there's no "which one" ambiguity to make the artist
        # resolve; checked by default.
        return {"accepted": True, "checked": True}

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish.
        """
        engine = sgtk.platform.current_engine()
        camera_node = item.properties["camera_node"]

        frame_range = engine.app.get_frame_range()
        start_frame = int(frame_range.get("start_frame", 1))
        stop_frame = int(frame_range.get("stop_frame", 1))
        item.properties["start_frame"] = start_frame
        item.properties["stop_frame"] = stop_frame

        json_template = item.properties["json_template"]
        chan_template = item.properties["chan_template"]

        # {name} is filter_by: alphanumeric — same fix as the Palette/
        # Element publishers, applied proactively this time.
        raw_name = camera_node.rsplit("/", 1)[-1]
        fields = engine.context.as_template_fields(json_template)
        fields["name"] = re.sub(r"[^A-Za-z0-9]", "", raw_name) or "camera"

        version = 1
        while True:
            fields["version"] = version
            json_path = json_template.apply_fields(fields)
            chan_path = chan_template.apply_fields(fields)
            if not os.path.exists(json_path) and not os.path.exists(chan_path):
                break
            version += 1

        item.properties["publish_version"] = version
        item.properties["publish_name"] = raw_name
        item.properties["json_path"] = json_path
        item.properties["chan_path"] = chan_path

        # unlike publish_palette.py/publish_element.py, this item has no
        # source file on disk at collection time (item.properties["path"]
        # was never set — the data is generated live, at publish time) so
        # the base class's file-copy/registration flow (which
        # get_publish_path() needs "path" for) doesn't apply here. Same
        # reasoning as publish_render.py: validate directly and return,
        # publish() does its own sgtk.util.register_publish() calls rather
        # than deferring to super().publish().
        return True

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.
        """
        publisher = self.parent
        engine = sgtk.platform.current_engine()
        context = item.context

        camera_node = item.properties["camera_node"]
        start_frame = item.properties["start_frame"]
        stop_frame = item.properties["stop_frame"]
        json_path = item.properties["json_path"]
        chan_path = item.properties["chan_path"]
        publish_name = item.properties["publish_name"]
        version = item.properties["publish_version"]

        camera_data = engine.app.export_camera_data(
            camera_node=camera_node, start_frame=start_frame, stop_frame=stop_frame
        )
        if not camera_data or not camera_data.get("success") or not camera_data.get("frames"):
            raise Exception(
                "EXPORT_CAMERA_DATA returned no usable data for '%s' — "
                "aborting instead of publishing an empty/bogus file. "
                "Check Harmony's Message Log for the DIAGNOSTIC attribute "
                "dump and the underlying error." % camera_node
            )

        ensure_folder_exists(os.path.dirname(json_path))
        ensure_folder_exists(os.path.dirname(chan_path))

        with open(json_path, "w") as fh:
            json.dump(camera_data, fh, indent=2)
        self.logger.info("Wrote camera data JSON: %s" % json_path)

        self._write_chan_file(chan_path, camera_data["frames"])
        self.logger.info("Wrote Nuke .chan file: %s" % chan_path)

        json_publish_data = sgtk.util.register_publish(
            engine.sgtk,
            context,
            json_path,
            publish_name,
            published_file_type="Harmony Camera Data",
            version_number=version,
            comment=item.description,
        )
        self.logger.info(
            "Registered camera data JSON PublishedFile: %s"
            % json_publish_data.get("id")
        )

        chan_publish_data = sgtk.util.register_publish(
            engine.sgtk,
            context,
            chan_path,
            publish_name,
            published_file_type="Harmony Camera Data",
            version_number=version,
            comment=item.description,
            dependency_paths=[json_path],
        )
        self.logger.info(
            "Registered camera data .chan PublishedFile: %s"
            % chan_publish_data.get("id")
        )

        item.properties["sg_publish_data"] = chan_publish_data

    def finalize(self, settings, item):
        """
        Execute the finalization pass.
        """
        pass

    def _write_chan_file(self, chan_path, frames):
        """
        Converts exported camera frame data to Nuke's .chan format: one
        line per frame, "frame tx ty tz rx ry rz". First-pass mapping —
        Harmony's camera is 2.5D (a single Z-axis rotation, "angle"), so
        rx/ry are always 0 here; expect this to need real-world validation
        against an actual Nuke comp.
        """
        lines = []
        for record in frames:
            camera = record["camera"]
            lines.append(
                "%d %f %f %f %f %f %f"
                % (
                    record["frame"],
                    camera["x"],
                    camera["y"],
                    camera["z"],
                    0.0,
                    0.0,
                    camera["angle"],
                )
            )

        with open(chan_path, "w") as fh:
            fh.write("\n".join(lines) + "\n")
