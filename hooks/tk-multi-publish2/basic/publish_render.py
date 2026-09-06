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
import sys
import subprocess

import sgtk


__author__ = "Adam Benson"
__contact__ = "https://www.linkedin.com/in/sleepdeprivedproductions/"
# based on original work by Diego Garcia Huerta and developed later by Adam Benson


HookBaseClass = sgtk.get_hook_baseclass()


# FFmpeg binaries optionally bundled with this repo, relative to the
# engine's disk location, keyed by sys.platform. Lets the plugin work with
# zero per-machine setup for studios/artists who don't have FFmpeg
# installed system-wide. Not required — if the platform has no entry here,
# or the file isn't actually present (e.g. only the Windows binary has
# been added so far), this falls back to the "FFmpeg Path" setting as-is.
BUNDLED_FFMPEG = {
    "win32": ("win64", "ffmpeg.exe"),
    "darwin": ("mac", "ffmpeg"),
}


class HarmonyRenderPublishPlugin(HookBaseClass):
    """
    Plugin for publishing one render pass (one Write node's output) from a
    Harmony session to ShotGrid as an image sequence PublishedFile, and —
    for exactly one designated "main" pass — also a transcoded movie
    PublishedFile plus a Version for web review.

    Multi-pass rework (see DEVELOPMENT_NOTES.txt): a scene can hold several
    Write nodes at once, one per compositing layer (e.g. "Background",
    "Ship", "Characters"). The collector (collector.py's
    collect_harmony_renders()) creates one harmony.render item per Write
    node found live in the scene; this plugin runs once per item.

    Rendering itself is never triggered from here — the scripted render
    trigger (render.renderSceneAll() + friends) never got a correctly-
    configured Write node to actually execute across several sessions of
    trying, and was retired. The workflow is: run the "Update Render
    Nodes" engine command to point every Write node at its Toolkit path,
    render manually via Harmony's own native Render command, then Publish
    picks up whatever frames exist on disk for each pass.
    """

    @property
    def description(self):
        return """
        Publishes one render pass (one Write node) of the current Harmony
        scene to ShotGrid as an image sequence. The pass whose Write node
        name matches the "Main Render Pass Name" setting is additionally
        transcoded to a .mov via FFmpeg and registered as a movie
        PublishedFile plus a Version for web review — other passes publish
        as sequence-only, for compositing.

        Does not render. Frames must already exist on disk for a pass
        (render manually in Harmony, after running the Shotgun menu's
        "Update Render Nodes" command to point every Write node at the
        correct output location) — a pass with no frames on disk fails
        validation with a message pointing at that workflow.
        """

    @property
    def settings(self):
        base_settings = super(HarmonyRenderPublishPlugin, self).settings or {}

        render_settings = {
            "Render Sequence Template": {
                "type": "template",
                "default": None,
                "description": "ShotGrid template for a rendered image "
                "sequence path. Should correspond to a "
                "template defined in templates.yml (e.g. "
                "harmony_shot_render_sequence).",
            },
            "Render Movie Template": {
                "type": "template",
                "default": None,
                "description": "ShotGrid template for the transcoded movie "
                "path. Should correspond to a template "
                "defined in templates.yml (e.g. "
                "harmony_shot_render_movie).",
            },
            "Main Render Pass Name": {
                "type": "str",
                "default": "Comp",
                "description": "The Write node name (case-insensitive) "
                "that identifies the scene's designated 'main' render "
                "pass — that pass, and only that pass, gets FFmpeg-"
                "transcoded and registered as a movie PublishedFile plus "
                "a ShotGrid Version for review. Every other pass publishes "
                "as a sequence only. If no Write node in the scene matches "
                "this name, all passes still publish as sequences; no "
                "Version is created.",
            },
            "FFmpeg Path": {
                "type": "str",
                "default": "ffmpeg",
                "description": "Path to the ffmpeg executable. Defaults to "
                "'ffmpeg', assuming it is available on the system PATH.",
            },
        }

        base_settings.update(render_settings)
        return base_settings

    @property
    def item_filters(self):
        return ["harmony.render"]

    def accept(self, settings, item):
        sequence_template_setting = settings.get("Render Sequence Template")
        movie_template_setting = settings.get("Render Movie Template")
        if not (
            sequence_template_setting
            and sequence_template_setting.value
            and movie_template_setting
            and movie_template_setting.value
        ):
            self.logger.debug(
                "Render Sequence/Movie Template not fully configured. The "
                "render publish plugin will not be accepted."
            )
            return {"accepted": False}

        self.logger.info(
            "Harmony render publish plugin accepted pass '%s'."
            % item.properties.get("pass_name_raw")
        )
        # render passes are core scene output (unlike Palette/Element's
        # incidental WIP scraps) — checked by default.
        return {"accepted": True, "checked": True}

    def validate(self, settings, item):
        publisher = self.parent
        engine = publisher.engine
        render_utils = engine.tk_harmony.render_utils

        pass_name_raw = item.properties["pass_name_raw"]

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

        # --- resolve this pass's output paths (shared with the "Update
        # Render Nodes" engine command, so they can never drift apart)
        pass_name = render_utils.sanitize_pass_name(pass_name_raw)
        try:
            paths = render_utils.resolve_render_paths_for_pass(engine, pass_name)
        except render_utils.RenderPathError as e:
            self.logger.error(str(e))
            raise Exception(str(e))

        output_dir = paths["output_dir"]
        base_name = paths["base_name"]

        # check output dir is writable (or its parent, if it doesn't exist yet)
        check_dir = output_dir if os.path.exists(output_dir) else os.path.dirname(output_dir)
        if os.path.exists(check_dir) and not os.access(check_dir, os.W_OK):
            error_msg = "Output directory is not writable: %s" % output_dir
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # --- confirm frames already exist for this pass — this plugin never
        # triggers a render itself
        existing_frames = render_utils.find_rendered_frames(output_dir, base_name)
        if not existing_frames:
            error_msg = (
                "No rendered frames found for pass '%s' at '%s'. Run the "
                "Shotgun menu's 'Update Render Nodes' command, render the "
                "scene manually in Harmony, then re-run Publish."
                % (pass_name_raw, output_dir)
            )
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # --- is this the designated "main" pass? (case-insensitive match
        # against the Write node's own, un-sanitized name)
        main_pass_setting = (settings.get("Main Render Pass Name").value or "").strip()
        is_main = bool(main_pass_setting) and (
            pass_name_raw.strip().lower() == main_pass_setting.lower()
        )

        item.properties["output_dir"] = output_dir
        item.properties["base_name"] = base_name
        item.properties["video_path"] = paths["video_path"]
        item.properties["render_fields"] = paths["render_fields"]
        item.properties["is_main"] = is_main

        if is_main:
            # --- confirm ffmpeg is available (only the main pass transcodes)
            ffmpeg_path = self._resolve_ffmpeg_path(engine, settings)
            try:
                subprocess.run(
                    [ffmpeg_path, "-version"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except FileNotFoundError:
                error_msg = (
                    "FFmpeg not found at '%s'. Install FFmpeg, bundle it under "
                    "resources/bin/, or set the 'FFmpeg Path' plugin setting to "
                    "the correct path." % ffmpeg_path
                )
                self.logger.error(error_msg)
                raise Exception(error_msg)
            except subprocess.CalledProcessError as e:
                self.logger.warning(
                    "FFmpeg returned a non-zero exit code during version check, "
                    "but the executable was found. Proceeding. (%s)" % e
                )

            item.properties["ffmpeg_path"] = ffmpeg_path

        return True

    def publish(self, settings, item):
        publisher = self.parent
        engine = publisher.engine
        context = item.context
        render_utils = engine.tk_harmony.render_utils

        pass_name_raw = item.properties["pass_name_raw"]
        output_dir = item.properties["output_dir"]
        base_name = item.properties["base_name"]
        render_fields = item.properties["render_fields"]
        is_main = item.properties["is_main"]

        existing_frames = render_utils.find_rendered_frames(output_dir, base_name)
        if not existing_frames:
            # re-checked here in case disk state changed between validate()
            # and publish() (e.g. another process cleared the folder)
            raise Exception(
                "No rendered frames found for pass '%s' at '%s'."
                % (pass_name_raw, output_dir)
            )

        self.logger.info(
            "Using %d rendered frame(s) for pass '%s'."
            % (len(existing_frames), pass_name_raw)
        )

        # --- register the image sequence as its own PublishedFile — every
        # pass gets this, main or not
        sequence_path = publisher.util.get_frame_sequence_path(
            existing_frames[0], frame_spec="%04d"
        )
        # output_dir's own last path segment is "{Shot}_{name}.v{version}"
        # (the render templates put the version in the folder, not the
        # filename — see render_fields note in render_utils.py) — same
        # clean, version-included name the movie template would produce,
        # so use it here too rather than parsing it back out of a frame path.
        sequence_publish_name = os.path.basename(output_dir)

        sequence_publish_data = sgtk.util.register_publish(
            engine.sgtk,
            context,
            sequence_path,
            sequence_publish_name,
            published_file_type="Rendered Image",
            version_number=render_fields.get("version", 1),
            comment=item.description,
        )
        item.properties["sg_publish_data"] = sequence_publish_data
        self.logger.info(
            "Registered image sequence PublishedFile for pass '%s': %s"
            % (pass_name_raw, sequence_publish_data.get("id"))
        )

        if not is_main:
            # layer passes stop here — sequence only, no movie/Version
            return

        video_path = item.properties["video_path"]
        ffmpeg_path = item.properties["ffmpeg_path"]

        # --- get frame rate (default 24)
        try:
            frame_rate = engine.app.execute("scene.getFrameRate()") or 24
            frame_rate = float(frame_rate)
        except Exception:
            frame_rate = 24.0

        # --- transcode to movie via FFmpeg
        ext = os.path.splitext(existing_frames[0])[1].lstrip(".")
        ffmpeg_cmd = [
            ffmpeg_path, "-y",
            "-framerate", str(frame_rate),
            "-i", os.path.join(output_dir, base_name + ".%04d." + ext),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "18",
            video_path,
        ]

        self.logger.info("Running FFmpeg: %s" % " ".join(ffmpeg_cmd))
        subprocess.run(ffmpeg_cmd, check=True)
        self.logger.info("FFmpeg transcode complete: %s" % video_path)

        # --- register the movie as its own PublishedFile
        movie_publish_name = os.path.splitext(os.path.basename(video_path))[0]
        movie_publish_data = sgtk.util.register_publish(
            engine.sgtk,
            context,
            video_path,
            movie_publish_name,
            published_file_type="Movie File",
            version_number=render_fields.get("version", 1),
            comment=item.description,
            dependency_paths=[sequence_path],
        )

        item.properties["sg_publish_data"] = movie_publish_data
        self.logger.info(
            "Registered movie PublishedFile: %s" % movie_publish_data.get("id")
        )

        # --- create ShotGrid Version entity
        version_data = {
            "code": movie_publish_name,
            "entity": context.entity,
            "project": context.project,
            "sg_task": context.task,
            "sg_path_to_movie": video_path,
            "description": item.description,
        }
        version = engine.shotgun.create("Version", version_data)

        item.properties["sg_version_id"] = version["id"]
        self.logger.info(
            "Created ShotGrid Version (id=%s): %s" % (version["id"], movie_publish_name)
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
            self.logger.info("ShotGrid Version created: %s" % version_url)

            if video_path and os.path.exists(video_path):
                try:
                    engine.shotgun.upload(
                        "Version", version_id, video_path, "sg_uploaded_movie"
                    )
                    self.logger.info(
                        "Uploaded movie for web review (Version id=%s)." % version_id
                    )
                except Exception as e:
                    self.logger.warning(
                        "Could not upload movie for web review: %s" % e
                    )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _resolve_ffmpeg_path(self, engine, settings):
        """
        An explicit "FFmpeg Path" setting always wins. Otherwise, prefer a
        copy of FFmpeg bundled with this repo (resources/bin/<platform>/)
        so the plugin works with no per-machine setup; if none is bundled
        for this platform (or the file just isn't there yet), fall back to
        the setting as-is, which defaults to a bare "ffmpeg" (PATH lookup).
        """
        configured = settings.get("FFmpeg Path").value or "ffmpeg"

        if configured != "ffmpeg":
            return configured

        platform_dir_exe = BUNDLED_FFMPEG.get(sys.platform)
        if not platform_dir_exe:
            return configured

        platform_dir, exe_name = platform_dir_exe
        bundled_path = os.path.join(
            engine.disk_location, "resources", "bin", platform_dir, exe_name
        )
        if not os.path.isfile(bundled_path):
            return configured

        if sys.platform != "win32":
            try:
                os.chmod(bundled_path, os.stat(bundled_path).st_mode | 0o111)
            except OSError as e:
                self.logger.warning(
                    "Could not ensure bundled FFmpeg is executable: %s" % e
                )

        return bundled_path
