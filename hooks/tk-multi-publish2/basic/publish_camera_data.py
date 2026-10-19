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
import math

import sgtk
from sgtk.util.filesystem import ensure_folder_exists


HookBaseClass = sgtk.get_hook_baseclass()


class HarmonyCameraDataPublishPlugin(HookBaseClass):
    """
    Plugin for publishing the scene's default camera's transform data.

    Exports two files: a JSON file (source of truth — full per-frame camera
    transform data plus scene/lens metadata that a .chan file has no room
    for) and a Nuke .chan file (frame tx ty tz rx ry rz per line, Nuke's own
    native Camera > Import chan file format — no plugin needed on the Nuke
    side).

    Scoped to the scene's current DEFAULT camera only (Scene > Camera):
    Harmony's scene.getCameraMatrix() — used to read the fully-composited
    transform, any driving Peg already baked in — can only read the current
    default camera, not an arbitrary camera node. Multi-camera scenes would
    need temporarily switching the default camera at publish time; deferred
    for now.

    Ported from Toon Boom's own TB_ExportCamera.js (matrix.extract*() calls,
    default-camera resolution, FOV/focal-length reporting, scale-varies
    detection) rather than the earlier guessed-attribute-name approach this
    plugin originally shipped with.
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
        Exports the scene's default camera's transform animation as a JSON
        file (source of truth, including scene/lens metadata) and a Nuke
        .chan file (importable directly via Nuke's Camera > Import chan
        file, no plugin required).<br><br>

        Scoped to the scene's current default camera (Scene &gt; Camera)
        only. If the camera's zoom is animated via SCALE rather than a
        Z-truck, that motion is NOT captured by the .chan file &mdash; check
        the JSON's <code>scene_info.scale_varies</code> flag and the
        publish log for a warning.
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
            "Unit Scale": {
                "type": "float",
                "default": 1.0,
                "description": "Multiplier applied to Harmony's position "
                "units when writing the .chan file (Harmony field units "
                "-> Nuke world units).",
            },
            "Flip X": {
                "type": "bool",
                "default": False,
                "description": "Invert the X axis when writing the .chan file.",
            },
            "Flip Y": {
                "type": "bool",
                "default": False,
                "description": "Invert the Y axis when writing the .chan file.",
            },
            "Flip Z": {
                "type": "bool",
                "default": False,
                "description": "Invert the Z axis when writing the .chan file "
                "(try this first if depth/parallax reads inverted in Nuke).",
            },
            "Flip Rotation X": {
                "type": "bool",
                "default": False,
                "description": "Invert the X rotation when writing the .chan file.",
            },
            "Flip Rotation Y": {
                "type": "bool",
                "default": False,
                "description": "Invert the Y rotation when writing the .chan file.",
            },
            "Flip Rotation Z": {
                "type": "bool",
                "default": False,
                "description": "Invert the Z rotation when writing the .chan file.",
            },
            "Rotation Is Radians": {
                "type": "bool",
                "default": False,
                "description": "Set True ONLY if rotations come out tiny "
                "(~0.01 instead of ~degrees) on retest, meaning "
                "matrix.extractRotation() returned radians on this build.",
            },
            "Nuke Horizontal Aperture (mm)": {
                "type": "float",
                "default": 24.576,
                "description": "Nuke camera horizontal aperture used to "
                "compute a suggested focal length from Harmony's FOV. Set "
                "to match the plate's camera in Nuke.",
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

        # Re-resolve the default camera now, rather than trusting the item
        # property from collection time — the artist may have changed the
        # scene's default camera (Scene > Camera) in between. Using the
        # freshly-resolved node keeps the computed name/paths below
        # consistent with what will actually be exported at publish time.
        default_camera = engine.app.get_default_camera()
        if not default_camera or not default_camera.get("success"):
            raise Exception(
                "No default camera found in the scene (%s). Set one via "
                "Scene > Camera before publishing camera data."
                % (default_camera.get("error") if default_camera else "no response")
            )

        camera_node = default_camera["camera_node"]
        if camera_node != item.properties.get("camera_node"):
            self.logger.warning(
                "Scene's default camera changed since collection (was '%s', "
                "now '%s') — publishing the current default camera."
                % (item.properties.get("camera_node"), camera_node)
            )
        item.properties["camera_node"] = camera_node

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
                "EXPORT_CAMERA_DATA returned no usable data for '%s': %s — "
                "aborting instead of publishing an empty/bogus file."
                % (
                    camera_node,
                    camera_data.get("error") if camera_data else "no response",
                )
            )

        scene_info = camera_data.get("scene_info", {}) or {}
        haperture_mm = settings.get("Nuke Horizontal Aperture (mm)").value
        fov_deg = scene_info.get("fov_deg")
        suggested_focal_mm = None
        if fov_deg:
            suggested_focal_mm = haperture_mm / (
                2.0 * math.tan(math.radians(fov_deg) / 2.0)
            )
        scene_info["nuke_haperture_mm"] = haperture_mm
        scene_info["suggested_focal_mm"] = suggested_focal_mm

        if scene_info.get("scale_varies"):
            self.logger.warning(
                "Camera SCALE animates in this scene — that is usually a "
                "zoom done by scaling the camera rather than trucking in Z, "
                "and it is NOT captured by the .chan file's translate/"
                "rotate channels. It must become animated focal length in "
                "Nuke instead. See scene_info.scale_varies in the published "
                "JSON."
            )

        ensure_folder_exists(os.path.dirname(json_path))
        ensure_folder_exists(os.path.dirname(chan_path))

        json_payload = {
            "camera_node": camera_data["camera_node"],
            "publish_name": publish_name,
            "version": version,
            "start_frame": start_frame,
            "stop_frame": stop_frame,
            "scene_info": scene_info,
            "frames": camera_data["frames"],
        }
        with open(json_path, "w") as fh:
            json.dump(json_payload, fh, indent=2)
        self.logger.info("Wrote camera data JSON: %s" % json_path)

        self._write_chan_file(chan_path, camera_data["frames"], settings)
        self.logger.info("Wrote Nuke .chan file: %s" % chan_path)

        # Registered under a separate published_file_type AND a distinct SG
        # "name" from the .chan (below). Loader2's "latest publish" browse
        # view groups/collapses publishes by (entity, name) alone, ignoring
        # published_file_type entirely — sharing publish_name with the .chan
        # (even under a different type) caused the two to collapse into a
        # single ambiguous tile with no working actions, confirmed live
        # (Session 20). The on-disk path/version stay siblings (same
        # {name}/{version} template fields as the .chan) so the Nuke-side
        # sibling-JSON lookup by extension-swap still works — only this SG
        # display name differs.
        json_publish_data = sgtk.util.register_publish(
            engine.sgtk,
            context,
            json_path,
            "%s Metadata" % publish_name,
            published_file_type="Harmony Camera Metadata",
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

    def _write_chan_file(self, chan_path, frames, settings):
        """
        Converts exported camera frame data to Nuke's .chan format: one
        line per frame, "frame tx ty tz rx ry rz". Axis-flip/unit-scale
        tunables are plugin settings (rather than hardcoded, as they were
        in the original TB_ExportCamera.js) so a TD can adjust Harmony ->
        Nuke coordinate conventions without touching JS. Defaults (no
        flips, unit scale 1.0) match that script's own defaults.
        """
        unit_scale = settings.get("Unit Scale").value
        flip_x = -1.0 if settings.get("Flip X").value else 1.0
        flip_y = -1.0 if settings.get("Flip Y").value else 1.0
        flip_z = -1.0 if settings.get("Flip Z").value else 1.0
        flip_rx = -1.0 if settings.get("Flip Rotation X").value else 1.0
        flip_ry = -1.0 if settings.get("Flip Rotation Y").value else 1.0
        flip_rz = -1.0 if settings.get("Flip Rotation Z").value else 1.0
        rotation_is_radians = settings.get("Rotation Is Radians").value
        rad_to_deg = 180.0 / math.pi

        lines = []
        for record in frames:
            p = record["position"]
            r = record["rotation"]

            tx = p["x"] * unit_scale * flip_x
            ty = p["y"] * unit_scale * flip_y
            tz = p["z"] * unit_scale * flip_z

            rx = r["x"] * flip_rx
            ry = r["y"] * flip_ry
            rz = r["z"] * flip_rz
            if rotation_is_radians:
                rx *= rad_to_deg
                ry *= rad_to_deg
                rz *= rad_to_deg

            lines.append(
                "%d %.6f %.6f %.6f %.6f %.6f %.6f"
                % (record["frame"], tx, ty, tz, rx, ry, rz)
            )

        with open(chan_path, "w") as fh:
            fh.write("\n".join(lines) + "\n")
