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
import glob
import json
import time
import uuid
import tempfile
import subprocess

import sgtk
from sgtk.util.filesystem import ensure_folder_exists


__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


HookBaseClass = sgtk.get_hook_baseclass()


class HarmonyRenderPublishPlugin(HookBaseClass):
    """
    Plugin for rendering a Harmony session and publishing the result to
    ShotGrid as a Version and PublishedFile.

    Uses a fire-and-forget + status file polling pattern:
    1. Sends RENDER_SCENE to Harmony (no response waited for).
    2. Polls a temp JSON status file that Harmony writes when done.
    3. Transcodes the image sequence to MP4 via FFmpeg.
    4. Publishes to ShotGrid.
    """

    @property
    def description(self):
        return """
        Renders the current Harmony scene and publishes the result to ShotGrid.

        The render is triggered via a fire-and-forget command to Harmony.
        Python polls a temporary status file until Harmony signals completion.
        The rendered image sequence is then transcoded to an MP4 via FFmpeg and
        registered in ShotGrid as a <b>Version</b> and <b>PublishedFile</b>.

        The plugin is <b>unchecked by default</b> — enable it explicitly when
        you want to include a render publish in the current session.
        """

    @property
    def settings(self):
        base_settings = super(HarmonyRenderPublishPlugin, self).settings or {}

        render_settings = {
            "Render Template": {
                "type": "template",
                "default": None,
                "description": "ShotGrid template for the output MP4 path. "
                "Should correspond to a template defined in templates.yml.",
            },
            "FFmpeg Path": {
                "type": "str",
                "default": "ffmpeg",
                "description": "Path to the ffmpeg executable. Defaults to "
                "'ffmpeg', assuming it is available on the system PATH.",
            },
            "Image Format": {
                "type": "str",
                "default": "PNG4",
                "description": "Harmony render format string passed to the "
                "RENDER_SCENE command.",
            },
        }

        base_settings.update(render_settings)
        return base_settings

    @property
    def item_filters(self):
        return ["harmony.session"]

    def accept(self, settings, item):
        render_template_setting = settings.get("Render Template")
        if not render_template_setting or not render_template_setting.value:
            self.logger.debug(
                "No Render Template configured. The render publish plugin will "
                "not be accepted."
            )
            return {"accepted": False}

        work_template = item.properties.get("work_template")
        if not work_template:
            self.logger.debug(
                "No work_template found on item. The render publish plugin "
                "will not be accepted."
            )
            return {"accepted": False}

        self.logger.info(
            "Harmony render publish plugin accepted the current session."
        )
        return {"accepted": True, "checked": False}

    def validate(self, settings, item):
        publisher = self.parent
        engine = publisher.engine

        # --- confirm session is saved
        current_path = engine.app.get_current_project_path()
        if not current_path or current_path == "Unknown":
            error_msg = "The Harmony session has not been saved."
            self.logger.error(error_msg)
            raise Exception(error_msg)

        if engine.app.is_startup_project():
            error_msg = (
                "The current project is the startup template and has not been "
                "saved to a pipeline path. Please save the session first."
            )
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # --- resolve render template
        render_template_setting = settings.get("Render Template")
        render_template = publisher.engine.get_template_by_name(
            render_template_setting.value
        )
        if not render_template:
            error_msg = (
                "Could not resolve render template '%s'. Check your "
                "templates.yml." % render_template_setting.value
            )
            self.logger.error(error_msg)
            raise Exception(error_msg)

        context = item.context
        work_template = item.properties.get("work_template")
        work_fields = work_template.get_fields(current_path)

        # determine next version number
        version = work_fields.get("version", 1)
        render_fields = {}
        for key in render_template.keys:
            if key in work_fields:
                render_fields[key] = work_fields[key]

        if "version" not in render_fields:
            render_fields["version"] = version

        if "name" not in render_fields:
            render_fields["name"] = work_fields.get(
                "name", work_fields.get("Shot", work_fields.get("Asset", "render"))
            )

        try:
            video_path = render_template.apply_fields(render_fields)
        except Exception as e:
            error_msg = (
                "Could not resolve render template to a path: %s" % e
            )
            self.logger.error(error_msg)
            raise Exception(error_msg)

        output_dir = os.path.dirname(video_path)

        # check output dir is writable
        if os.path.exists(output_dir):
            if not os.access(output_dir, os.W_OK):
                error_msg = (
                    "Output directory is not writable: %s" % output_dir
                )
                self.logger.error(error_msg)
                raise Exception(error_msg)
        else:
            parent_dir = os.path.dirname(output_dir)
            if os.path.exists(parent_dir) and not os.access(parent_dir, os.W_OK):
                error_msg = (
                    "Cannot create output directory (parent not writable): %s"
                    % output_dir
                )
                self.logger.error(error_msg)
                raise Exception(error_msg)

        # stash resolved paths for publish()
        item.properties["render_template"] = render_template
        item.properties["render_fields"] = render_fields
        item.properties["video_path"] = video_path
        item.properties["output_dir"] = output_dir

        # --- confirm ffmpeg is available
        ffmpeg_path = settings.get("FFmpeg Path").value or "ffmpeg"
        try:
            subprocess.run(
                [ffmpeg_path, "-version"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            error_msg = (
                "FFmpeg not found at '%s'. Install FFmpeg or set the "
                "'FFmpeg Path' plugin setting to the correct path." % ffmpeg_path
            )
            self.logger.error(error_msg)
            raise Exception(error_msg)
        except subprocess.CalledProcessError as e:
            self.logger.warning(
                "FFmpeg returned a non-zero exit code during version check, "
                "but the executable was found. Proceeding. (%s)" % e
            )

        # --- warn if output video already exists
        if os.path.exists(video_path):
            self.logger.warning(
                "The render output already exists on disk and will be "
                "overwritten: %s" % video_path
            )

        return True

    def publish(self, settings, item):
        publisher = self.parent
        engine = publisher.engine
        context = item.context

        ffmpeg_path = settings.get("FFmpeg Path").value or "ffmpeg"
        image_format = settings.get("Image Format").value or "PNG4"

        render_fields = item.properties["render_fields"]
        output_dir = item.properties["output_dir"]
        video_path = item.properties["video_path"]

        # --- get frame range
        frame_range = engine.app.get_frame_range()
        start_frame = int(frame_range.get("start_frame", 1))
        stop_frame = int(frame_range.get("stop_frame", 1))

        # --- derive base_name from video filename (without extension)
        base_name = os.path.splitext(os.path.basename(video_path))[0]

        # --- create output dir
        ensure_folder_exists(output_dir)

        # --- save scene before rendering
        engine.app.save_project()

        # --- generate status file path
        status_path = os.path.join(
            tempfile.gettempdir(),
            "harmony_render_{}.json".format(uuid.uuid4().hex),
        )

        # --- fire render (fire-and-forget)
        engine.app.render_scene(
            output_dir=output_dir,
            base_name=base_name,
            start_frame=start_frame,
            stop_frame=stop_frame,
            status_path=status_path,
            file_format=image_format,
        )

        # --- poll for status file
        timeout_seconds = 3600
        poll_interval = 2
        elapsed = 0

        self.logger.info(
            "Waiting for Harmony to finish rendering (timeout: %ds)..."
            % timeout_seconds
        )

        while not os.path.exists(status_path):
            engine.show_busy(
                "Rendering...",
                "Waiting for Harmony to complete render... (%ds elapsed)"
                % elapsed,
            )
            time.sleep(poll_interval)
            elapsed += poll_interval
            if elapsed >= timeout_seconds:
                raise Exception(
                    "Timed out waiting for Harmony render after %d seconds."
                    % timeout_seconds
                )

        # --- read status
        with open(status_path, "r") as fh:
            status = json.load(fh)

        # --- clean up status file
        try:
            os.remove(status_path)
        except Exception:
            pass

        if not status.get("success", False):
            error_msg = status.get(
                "error", "Harmony render failed with an unknown error."
            )
            raise Exception("Harmony render failed: %s" % error_msg)

        self.logger.info("Harmony render completed successfully.")

        # --- glob rendered image sequence
        rendered_frames = sorted(
            glob.glob(os.path.join(output_dir, base_name + ".*.png"))
        )
        if not rendered_frames:
            raise Exception(
                "No rendered frames found in '%s' matching pattern '%s.*.png'."
                % (output_dir, base_name)
            )

        self.logger.info(
            "Found %d rendered frame(s)." % len(rendered_frames)
        )

        # --- get frame rate (default 24)
        try:
            frame_rate = engine.app.execute(
                "scene.getFrameRate()"
            ) or 24
            frame_rate = float(frame_rate)
        except Exception:
            frame_rate = 24.0

        # --- transcode to MP4 via FFmpeg
        ffmpeg_cmd = [
            ffmpeg_path, "-y",
            "-framerate", str(frame_rate),
            "-i", os.path.join(output_dir, base_name + ".%04d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "18",
            video_path,
        ]

        self.logger.info("Running FFmpeg: %s" % " ".join(ffmpeg_cmd))

        subprocess.run(ffmpeg_cmd, check=True)

        self.logger.info("FFmpeg transcode complete: %s" % video_path)

        # --- build publish name
        publish_name = os.path.splitext(os.path.basename(video_path))[0]

        # --- register PublishedFile in ShotGrid
        publish_data = sgtk.util.register_publish(
            engine.sgtk,
            context,
            video_path,
            publish_name,
            published_file_type="Rendered Image",
            version_number=render_fields.get("version", 1),
            comment=item.description,
        )

        item.properties["sg_publish_data"] = publish_data
        self.logger.info(
            "Registered PublishedFile: %s" % publish_data.get("id")
        )

        # --- create ShotGrid Version entity
        version_data = {
            "code": publish_name,
            "entity": context.entity,
            "project": context.project,
            "sg_task": context.task,
            "sg_path_to_movie": video_path,
            "description": item.description,
        }
        version = engine.shotgun.create("Version", version_data)

        item.properties["sg_version_id"] = version["id"]

        self.logger.info(
            "Created ShotGrid Version (id=%s): %s" % (version["id"], publish_name)
        )

    def finalize(self, settings, item):
        publisher = self.parent
        engine = publisher.engine

        version_id = item.properties.get("sg_version_id")
        video_path = item.properties.get("video_path")

        if version_id:
            version_url = "%s/detail/Version/%s" % (
                engine.shotgun.base_url,
                version_id,
            )
            self.logger.info(
                "ShotGrid Version created: %s" % version_url
            )

            if video_path and os.path.exists(video_path):
                try:
                    engine.shotgun.upload(
                        "Version",
                        version_id,
                        video_path,
                        "sg_uploaded_movie",
                    )
                    self.logger.info(
                        "Uploaded movie for web review (Version id=%s)."
                        % version_id
                    )
                except Exception as e:
                    self.logger.warning(
                        "Could not upload movie for web review: %s" % e
                    )
