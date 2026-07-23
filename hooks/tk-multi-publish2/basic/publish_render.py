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
import glob
import json
import time
import uuid
import shutil
import tempfile
import subprocess

import sgtk
from sgtk.util.filesystem import ensure_folder_exists


__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


HookBaseClass = sgtk.get_hook_baseclass()


# common frame image extensions to look for when falling back to Harmony's
# own native output folder (see _find_rendered_frames below)
FALLBACK_FRAME_EXTENSIONS = ("png", "tga", "tif", "tiff", "jpg")

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
    Plugin for rendering a Harmony session and publishing the result to
    ShotGrid as a Version, an image sequence PublishedFile, and a movie
    PublishedFile.

    1. Points the scene's Write node at a Toolkit-computed path/format
       (CONFIGURE_WRITE_NODE — best-effort, see configure.js).
    2. Sends RENDER_SCENE to Harmony (fire-and-forget, no response waited
       for — renders can run far longer than the socket's read timeout).
    3. Polls a temp JSON status file that Harmony writes when done.
    4. Locates the rendered frames — checks the Toolkit path first, and
       falls back to searching the project's native frames/ folder (in
       case the Write node redirect in step 1 didn't take effect) and
       copying them into place.
    5. Transcodes the image sequence to a .mov via FFmpeg.
    6. Publishes the sequence and the movie as separate PublishedFiles, and
       creates a Version for web review from the movie.

    If a render for the current version already exists on disk, steps 1-4
    are skipped entirely and this just publishes what's already there —
    no need to force a re-render for something already rendered outside a
    publish session.
    """

    @property
    def description(self):
        return """
        Renders the current Harmony scene (via its Write node) and publishes
        the result to ShotGrid as an image sequence and a movie.

        If a render already exists on disk for the current version, it is
        published as-is — no re-render is triggered. Otherwise the render is
        triggered via a fire-and-forget command to Harmony, and Python polls
        a temporary status file until Harmony signals completion. The
        rendered image sequence is then transcoded to a .mov via FFmpeg.

        The plugin is <b>unchecked by default</b> — enable it explicitly when
        you want to include a render publish in the current session.
        """

    @property
    def settings(self):
        base_settings = super(HarmonyRenderPublishPlugin, self).settings or {}

        render_settings = {
            "Render Sequence Template": {
                "type": "template",
                "default": None,
                "description": "ShotGrid template for the rendered image "
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
            "FFmpeg Path": {
                "type": "str",
                "default": "ffmpeg",
                "description": "Path to the ffmpeg executable. Defaults to "
                "'ffmpeg', assuming it is available on the system PATH.",
            },
            "Image Format": {
                "type": "str",
                "default": "PNG",
                "description": "Harmony render format string passed to the "
                "CONFIGURE_WRITE_NODE command. Must match a value Harmony's "
                "DRAWING_TYPE attribute actually accepts on the target "
                "version — confirmed live on Harmony 25.2 that 'PNG4' is "
                "not valid and silently falls back to Harmony's own "
                "default (TGA); 'PNG' is the confirmed-valid value.",
            },
        }

        base_settings.update(render_settings)
        return base_settings

    @property
    def item_filters(self):
        return ["harmony.session"]

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

        # --- resolve render templates
        sequence_template = publisher.engine.get_template_by_name(
            settings.get("Render Sequence Template").value
        )
        movie_template = publisher.engine.get_template_by_name(
            settings.get("Render Movie Template").value
        )
        if not sequence_template or not movie_template:
            error_msg = (
                "Could not resolve the render sequence/movie templates. "
                "Check your templates.yml."
            )
            self.logger.error(error_msg)
            raise Exception(error_msg)

        work_template = item.properties.get("work_template")
        work_fields = work_template.get_fields(current_path)

        render_fields = {}
        for key in sequence_template.keys:
            if key in work_fields:
                render_fields[key] = work_fields[key]

        if "version" not in render_fields:
            render_fields["version"] = work_fields.get("version", 1)

        if "name" not in render_fields:
            # {name} is a distinct render-pass label, not the shot/asset code
            # (Shot/Asset already appear as their own keys in the render
            # template path) — the Harmony work template has no {name} key,
            # so this always falls through to the literal default today.
            render_fields["name"] = work_fields.get("name", "render")

        try:
            # SEQ is a formatting placeholder here, not a real frame number —
            # apply_fields with a literal frame-number placeholder isn't
            # possible via the normal API, so build the sequence path with a
            # representative frame and derive the glob/ffmpeg patterns from it
            sequence_fields = dict(render_fields)
            sequence_fields["SEQ"] = 1
            sample_frame_path = sequence_template.apply_fields(sequence_fields)
            output_dir = os.path.dirname(sample_frame_path)
            base_name = os.path.basename(sample_frame_path).split(".")[0]

            video_path = movie_template.apply_fields(render_fields)
        except Exception as e:
            error_msg = "Could not resolve render templates to a path: %s" % e
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # check output dir is writable (or its parent, if it doesn't exist yet)
        check_dir = output_dir if os.path.exists(output_dir) else os.path.dirname(output_dir)
        if os.path.exists(check_dir) and not os.access(check_dir, os.W_OK):
            error_msg = "Output directory is not writable: %s" % output_dir
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # stash resolved paths for publish()
        item.properties["sequence_template"] = sequence_template
        item.properties["movie_template"] = movie_template
        item.properties["render_fields"] = render_fields
        item.properties["output_dir"] = output_dir
        item.properties["base_name"] = base_name
        item.properties["video_path"] = video_path

        # --- confirm ffmpeg is available
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

        # stash so publish() uses the exact same resolved path, not a fresh
        # (and potentially different, if disk state changed) resolution
        item.properties["ffmpeg_path"] = ffmpeg_path

        return True

    def publish(self, settings, item):
        publisher = self.parent
        engine = publisher.engine
        context = item.context

        ffmpeg_path = item.properties["ffmpeg_path"]
        image_format = settings.get("Image Format").value or "PNG"

        render_fields = item.properties["render_fields"]
        output_dir = item.properties["output_dir"]
        base_name = item.properties["base_name"]
        video_path = item.properties["video_path"]

        # --- if this version has already been rendered, don't render again —
        # just publish what's there. Covers the "artist already rendered
        # manually, just wants to publish" case without a wasted re-render.
        existing_frames = self._find_rendered_frames(output_dir, base_name)
        if existing_frames:
            self.logger.info(
                "Found %d already-rendered frame(s) for this version at '%s' — "
                "skipping render." % (len(existing_frames), output_dir)
            )
        else:
            self._render(
                engine, output_dir, base_name, image_format, ffmpeg_path
            )
            existing_frames = self._find_rendered_frames(output_dir, base_name)

            if not existing_frames:
                # the Write node redirect (configure_write_node) is a
                # best-effort, unverified operation — fall back to
                # Harmony's own native output location and copy from there
                existing_frames = self._recover_frames_from_native_output(
                    engine, output_dir, base_name
                )

        if not existing_frames:
            raise Exception(
                "No rendered frames found for this version, at '%s' or in "
                "Harmony's native output folder." % output_dir
            )

        self.logger.info("Using %d rendered frame(s)." % len(existing_frames))

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

        # --- register the image sequence as its own PublishedFile
        sequence_path = publisher.util.get_frame_sequence_path(
            existing_frames[0], frame_spec="%04d"
        )
        sequence_publish_name = os.path.splitext(os.path.basename(video_path))[0]

        sequence_publish_data = sgtk.util.register_publish(
            engine.sgtk,
            context,
            sequence_path,
            sequence_publish_name,
            published_file_type="Rendered Image",
            version_number=render_fields.get("version", 1),
            comment=item.description,
        )
        self.logger.info(
            "Registered image sequence PublishedFile: %s"
            % sequence_publish_data.get("id")
        )

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

    def _find_rendered_frames(self, output_dir, base_name):
        """
        Look for an already-rendered frame sequence matching base_name at
        the Toolkit-computed output_dir.
        """
        if not os.path.isdir(output_dir):
            return []

        for ext in FALLBACK_FRAME_EXTENSIONS:
            frames = sorted(
                glob.glob(os.path.join(output_dir, base_name + ".*." + ext))
            )
            if frames:
                return frames

        return []

    def _clear_existing_frames(self, output_dir, base_name):
        """
        Remove any pre-existing frames matching base_name before a fresh
        render. Without this, re-rendering the same version (e.g. during
        iterative testing, or an artist re-running a publish) leaves
        leftover frames from a prior attempt sitting alongside newly
        rendered ones — harmless if the prior attempt used the same
        format/frame count, but a real source of a jumbled/inconsistent
        sequence if it didn't (different image format, partial/aborted
        render, different frame range).
        """
        for ext in FALLBACK_FRAME_EXTENSIONS:
            for f in glob.glob(os.path.join(output_dir, base_name + ".*." + ext)):
                try:
                    os.remove(f)
                except OSError as e:
                    self.logger.warning("Could not remove stale frame %s: %s" % (f, e))

    def _render(self, engine, output_dir, base_name, image_format, ffmpeg_path):
        """
        Points the Write node at the Toolkit path (best-effort — see
        configure.js CONFIGURE_WRITE_NODE), triggers the render, and blocks
        until Harmony signals completion via the status file.
        """
        frame_range = engine.app.get_frame_range()
        start_frame = int(frame_range.get("start_frame", 1))
        stop_frame = int(frame_range.get("stop_frame", 1))

        ensure_folder_exists(output_dir)
        self._clear_existing_frames(output_dir, base_name)

        # save scene before rendering
        engine.app.save_project()

        engine.app.configure_write_node(
            output_dir=output_dir, base_name=base_name, file_format=image_format
        )

        status_path = os.path.join(
            tempfile.gettempdir(), "harmony_render_{}.json".format(uuid.uuid4().hex)
        )

        # fire render (fire-and-forget)
        engine.app.render_scene(
            start_frame=start_frame, stop_frame=stop_frame, status_path=status_path
        )

        # poll for status file
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
                "Waiting for Harmony to complete render... (%ds elapsed)" % elapsed,
            )
            time.sleep(poll_interval)
            elapsed += poll_interval
            if elapsed >= timeout_seconds:
                engine.clear_busy()
                raise Exception(
                    "Timed out waiting for Harmony render after %d seconds."
                    % timeout_seconds
                )

        # show_busy() has no matching clear_busy() call anywhere else in
        # this file — without this, the "Rendering..." dialog was never
        # explicitly dismissed once polling finished.
        engine.clear_busy()

        with open(status_path, "r") as fh:
            status = json.load(fh)

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

    def _recover_frames_from_native_output(self, engine, output_dir, base_name):
        """
        CONFIGURE_WRITE_NODE's redirect of the Write node's output is
        unverified — if nothing landed at output_dir, look in the current
        project's own native frames/ folder instead, and copy whatever's
        there into output_dir under the expected naming so the rest of the
        pipeline (ffmpeg, sequence path) doesn't need to know the
        difference.
        """
        current_path = engine.app.get_current_project_path()
        project_folder = os.path.dirname(current_path)
        native_frames_dir = os.path.join(project_folder, "frames")

        if not os.path.isdir(native_frames_dir):
            self.logger.debug(
                "No native frames/ folder found at '%s'." % native_frames_dir
            )
            return []

        found = []
        for ext in FALLBACK_FRAME_EXTENSIONS:
            found = sorted(glob.glob(os.path.join(native_frames_dir, "*." + ext)))
            if found:
                break

        if not found:
            return []

        self.logger.info(
            "Recovered %d frame(s) from Harmony's native output folder '%s' — "
            "copying to '%s'." % (len(found), native_frames_dir, output_dir)
        )

        ensure_folder_exists(output_dir)
        recovered = []
        for i, src in enumerate(found, start=1):
            ext = os.path.splitext(src)[1]
            dst = os.path.join(output_dir, "%s.%04d%s" % (base_name, i, ext))
            shutil.copy2(src, dst)
            recovered.append(dst)

        return recovered
