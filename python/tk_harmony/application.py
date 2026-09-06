"""
Module that encapsulates access to the actual application

"""


import os
import re
import glob
import shutil
import traceback
from itertools import chain

from .client import QTcpSocketClient
from .utils import copy_tree, normpath, Cached


__author__ = "Adam Benson"
__contact__ = "https://www.linkedin.com/in/sleepdeprivedproductions/"
# based on original work by Diego Garcia Huerta and developed later by Adam Benson


class Application(QTcpSocketClient):
    def __init__(self, engine, parent=None, host=None, port=None):
        super(Application, self).__init__(parent=parent, host=host, port=port)
        self.engine = engine
        self.engine.logger.debug("Started Application: %s" % self)

    def connect(self):
        while not self.is_connected():
            self.connect_to_host()
            self.engine.logger.debug("Waiting for server: %s" % self.connection_status())

    def _on_callback_error(self, method, kwargs):
        self.engine.show_error(
            "Shotgun Harmony Engine encountered an error handling '%s'.\n"
            "See the log file for the full traceback." % method
        )

    def broadcast_event(self, event_name):
        self.send_command(event_name)

    def log_info(self, message):
        self.send_command("LOG_INFO", message=message)

    def log_warning(self, message):
        self.send_command("LOG_WARNING", message=message)

    def log_debug(self, message):
        self.send_command("LOG_DEBUG", message=message)

    def log_error(self, message):
        self.send_command("LOG_ERROR", message=message)

    def log_exception(self, message):
        self.send_command("LOG_EXCEPTION", message=message)

    def toggle_debug_logging(self, enabled):
        self.send_command("TOGGLE_DEBUG_LOGGING", enabled=enabled)

    def get_application_version(self):
        version = self.send_and_receive_command("GET_VERSION")
        self._app_version = str(version)
        return self._app_version

    get_application_version = Cached(get_application_version)

    def get_current_project_path(self):
        current_path = self.send_and_receive_command("GET_CURRENT_PROJECT_PATH")
        if current_path:
            current_path = normpath(str(current_path))
        else:
            current_path = "Unknown"

        return current_path

    def open_project(self, path):
        path = normpath(path)
        current_path = self.send_and_receive_command("OPEN_PROJECT", path=path)
        if current_path:
            current_path = normpath(str(current_path))

        return current_path

    def save_project(self):
        current_path = self.send_and_receive_command("SAVE_PROJECT")
        if current_path:
            current_path = normpath(str(current_path))

        return current_path

    def needs_saving(self, path):
        result = self.send_and_receive_command("NEEDS_SAVING", path=path)
        return result

    def save_new_version(self, version_name):
        current_path = self.send_and_receive_command(
            "SAVE_NEW_VERSION", version_name=version_name
        )
        if current_path:
            current_path = normpath(str(current_path))

        return current_path

    def is_startup_project(self):
        result = self.send_and_receive_command("IS_STARTUP_PROJECT")
        return result

    def execute(self, statement_str):
        result = self.send_and_receive_command("EXECUTE_STATEMENT", statement=statement_str)
        return result

    def extract_thumbnail(self, filename):
        result = self.send_and_receive_command("EXTRACT_THUMBNAIL", path=filename)
        return result

    # file management
    def new_file(self, app, context):
        import sgtk.platform

        # In Harmony we cannot really have a non saved project, so we
        # have to create one from scratch given a template to follow.
        app.log_debug("Copying the template project")

        # Suggest to save the project if it's modified
        app.log_debug("Checking if needing to save...")
        current_path = self.get_current_project_path()

        needs_saving = self.needs_saving(current_path)
        app.log_debug("Needs saving: %s" % needs_saving)

        app_settings = sgtk.platform.find_app_settings(
            app.engine.name, app.name, app.sgtk, context, app.engine.instance_name
        )

        settings = None
        for app_setting in app_settings:
            if app_setting.get("app_instance") == app.instance_name:
                settings = app_setting.get("settings")
                break

        if not settings:
            raise TankError(
                "Could not find the settings for app: %s context: %s" % (app.name, context)
            )

        # check if we have a different template to copy from than the original
        template_project_folder = settings.get("template_project_folder", None)
        if template_project_folder and os.path.exists(template_project_folder):
            source_path = template_project_folder
        else:
            source_path = os.environ["SGTK_HARMONY_NEWFILE_TEMPLATE"]

        # now we copy the newfile template to the destination path
        app.log_debug("Source_path: %s" % source_path)

        work_template = app.get_template_from(settings, "template_work")

        fields = {}

        ext_is_used = "extension" in work_template.keys
        name_is_used = "name" in work_template.keys
        version_is_used = "version" in work_template.keys

        if name_is_used:
            fields["name"] = "scene"
        if ext_is_used:
            fields["extension"] = "xstage"

        ctx_fields = context.as_template_fields(work_template, validate=True)
        fields = dict(chain(fields.items(), ctx_fields.items()))

        destination_path = None
        # very cheap way to get the next available version
        if version_is_used:
            version = 1
            while True:
                fields["version"] = version
                destination_path = work_template.apply_fields(fields)
                if not os.path.exists(destination_path):
                    break
                version += 1

        # Harmony saves projects in folders
        destination_folder, destination_filename = os.path.split(destination_path)
        destination_folder = normpath(destination_folder).replace("\\", "/")
        app.log_debug("Destination_folder: %s" % destination_folder)
        app.log_debug("Destination_filename: %s" % destination_filename)

        source_path_dir, source_path_filename = os.path.split(source_path)
        copy_tree(
            source_path_dir,
            destination_folder,
            rename_files={source_path_filename: destination_filename},
        )

        # and open it
        destination_path = normpath(destination_path).replace("\\", "/")
        app.log_debug("Opening new project: %s" % destination_path)
        self.open_project(destination_path)

        return True

    def save_new_version_action(self):
        result = self.send_and_receive_command("SAVE_NEW_VERSION_ACTION")
        return result

    def _copy_tree(self, *args, **kwargs):
        """
        We expose this function here for the hooks to take advantage of it
        """
        copy_tree(*args, **kwargs)

    def save_project_as(self, target_file, source_file=None, open_project=True):
        self.engine.logger.debug("Saving project as...")

        if source_file is None:
            source_file = self.get_current_project_path()

        source_folder, source_filename = os.path.split(source_file)
        source_filename_file, source_filename_ext = os.path.splitext(source_filename)

        target_folder, target_filename = os.path.split(target_file)
        target_filename_file, target_filename_ext = os.path.splitext(target_filename)

        # we need to ignore all the other versions within the
        # folder of this WIP version except for the ones that
        # we are publishing.
        include_files = [source_filename, source_filename_file + ".aux"]

        # start ingoring them all, but them add the good ones back
        exclude_patterns = ["*.xstage", "*.aux", "*.*~"]

        exclude_files = []
        for exclude_pattern in exclude_patterns:
            exclude_pattern_path = os.path.join(source_folder, exclude_pattern)
            exclude_files.extend(glob.glob(exclude_pattern_path))

        # just get the filenames names from their path
        exclude_files = list(map(os.path.basename, exclude_files))

        # make sure we keep the good ones!
        exclude_files = list(filter(lambda x: x not in include_files, exclude_files))

        # rename the files from source folder to publish folder
        rename_files = {}
        if source_filename != target_filename:
            rename_files[source_filename] = target_filename

        if source_filename_file + ".aux" != target_filename_file + ".aux":
            rename_files[source_filename_file + ".aux"] = target_filename_file + ".aux"

        # copy the folder to target
        # Note that I would happily use shutil.copytree, but we need to rename
        # files as they go from source to publish folder.
        # Also at the time of writting, shutil.copytree does not provide
        # the fancy callbacks that other python versions allow to choose your
        # own copy function, which could have become handy to inject the
        # renaming functionality.
        # If the copy fails partway through (a locked file, a Dropbox/OneDrive
        # placeholder that isn't fully hydrated, a path length issue, etc.),
        # target_folder is left containing an incomplete set of files —
        # looks like a real version but won't open in Harmony, and silently
        # blocks the next attempt at this version number. Only clean it up
        # on failure if we're the ones who created it (never touch a
        # folder that already existed before this call).
        target_folder_existed_before = os.path.exists(target_folder)

        try:
            target_parent_folder = os.path.dirname(target_folder)
            if not os.path.exists(target_parent_folder):
                os.makedirs(target_parent_folder)

            self._copy_tree(
                source_folder,
                target_folder,
                exclude_files=exclude_files,
                rename_files=rename_files,
            )

        except Exception as e:
            if not target_folder_existed_before and os.path.exists(target_folder):
                self.engine.logger.debug(
                    "Copy failed partway — removing incomplete target folder '%s'."
                    % target_folder
                )
                shutil.rmtree(target_folder, ignore_errors=True)

            raise Exception(
                "Failed to copy source folder from '%s' to '%s'.\n%s"
                % (source_folder, target_folder, traceback.format_exc())
            )

        self.engine.logger.debug(
            "Copied source folder '%s' to folder '%s'." % (source_folder, target_folder)
        )

        if open_project:
            self.open_project(target_file)

    # timeline
    def get_start_frame(self):
        result = self.send_and_receive_command("GET_START_FRAME")
        return result

    def set_start_frame(self, start_frame):
        result = self.send_and_receive_command("SET_START_FRAME", start_frame=start_frame)
        return result

    def get_stop_frame(self):
        result = self.send_and_receive_command("GET_STOP_FRAME")
        return result

    def set_stop_frame(self, stop_frame):
        result = self.send_and_receive_command("SET_STOP_FRAME", stop_frame=stop_frame)
        return result

    def get_frame_range(self):
        result = self.send_and_receive_command("GET_FRAME_RANGE")
        if result is None:
            # send_and_receive_command returns None on a socket timeout
            # (MAX_READ_RESPONSE_TIME, 10s in client.py) rather than
            # raising — callers that assume a dict (e.g. publish_render.py's
            # _render() calling frame_range.get(...)) crash with an
            # unrelated-looking AttributeError instead of a clear timeout
            # error. Most likely to happen right after a scene reload
            # (e.g. a version-up/save_project_as just before this call,
            # such as when the Harmony Session and Render publish items
            # run together) — reopening a real scene can easily take
            # longer than 10s, so the very next RPC call can time out
            # before Harmony has finished settling.
            raise Exception(
                "Timed out waiting for Harmony to respond to GET_FRAME_RANGE. "
                "This is most likely to happen immediately after a scene "
                "reload (e.g. a version-up just completed) — Harmony may "
                "still be settling. Try the operation again."
            )
        return result

    def set_frame_range(self, start_frame, stop_frame):
        result = self.send_and_receive_command(
            "SET_FRAME_RANGE", start_frame=start_frame, stop_frame=stop_frame
        )
        return result

    def get_frame_count(self):
        result = self.send_and_receive_command("GET_FRAME_COUNT")
        return result

    def set_frame_count(self, frame_count):
        result = self.send_and_receive_command("SET_FRAME_COUNT", frame_count=frame_count)
        return result

    # scene editing / management
    def import_project_resource(self, path, action):
        result = None

        # make sure we have a Harmony friendly path
        path = path.replace("\\", "/")

        if action == "drawing":
            result = self.send_command("IMPORT_DRAWING", path=path)

        if action == "3d":
            result = self.send_command("IMPORT_DRAWING", path=path)

        if action == "sound":
            result = self.send_command("IMPORT_AUDIO", path=path)

        if action == "movie":
            result = self.send_command("IMPORT_CLIP", path=path)

        if action == "template":
            # NOTE: unlike the other actions, this uses send_and_receive
            # (not fire-and-forget) so the Loader can actually detect and
            # report an import failure instead of silently no-op'ing — the
            # other actions above still have this gap and should get the
            # same treatment later.
            result = self.send_and_receive_command("IMPORT_TEMPLATE", path=path)

        if action == "palette":
            result = self.send_and_receive_command("IMPORT_PALETTE", path=path)

        if action == "element":
            # path is the published element FOLDER — list and correctly
            # sort its drawing files (numerically, not alphabetically —
            # see _sorted_files_by_trailing_number's docstring for why
            # that distinction matters) and hand the resolved list to
            # Harmony to rebuild as one multi-drawing element.
            element_name = os.path.basename(os.path.normpath(path))
            file_paths = self._sorted_files_by_trailing_number(path)
            result = self.send_and_receive_command(
                "IMPORT_ELEMENT_FILES",
                element_name=element_name,
                file_paths=file_paths,
                source_path=path,
            )

        if action == "sequence":
            # path is a frame_spec pattern (e.g. ".../Shot_v001.%04d.png",
            # from publisher.util.get_frame_sequence_path) — glob the
            # actual frame files it represents, in the same folder.
            sequence_dir = os.path.dirname(path)
            glob_pattern = re.sub(r"%0\d*d", "*", os.path.basename(path))
            file_paths = self._sorted_files_by_trailing_number(
                sequence_dir, glob_pattern=glob_pattern
            )
            element_name = os.path.splitext(os.path.basename(path))[0]
            result = self.send_and_receive_command(
                "IMPORT_ELEMENT_FILES",
                element_name=element_name,
                file_paths=file_paths,
                source_path=path,
            )

        return result

    def _sorted_files_by_trailing_number(self, folder, glob_pattern="*"):
        """
        Lists files in folder matching glob_pattern, sorted by the
        trailing digit run before each file's extension (numerically, not
        alphabetically) — the same fix applied to
        publish_render.py's _native_frame_number, needed here for exactly
        the same reason: plain alphabetical sort of unpadded/variously-
        padded frame numbers scrambles the sequence (1, 10, 11, ..., 2,
        20, ...).
        """

        def sort_key(file_path):
            match = re.search(r"(\d+)(?=\.\w+$)", os.path.basename(file_path))
            return int(match.group(1)) if match else -1

        found = [
            f.replace("\\", "/") for f in glob.glob(os.path.join(folder, glob_pattern))
            if os.path.isfile(f)
        ]
        return sorted(found, key=sort_key)

    def get_nodes_of_type(self, node_types):
        result = self.send_and_receive_command("GET_NODES_OF_TYPE", node_types=node_types)
        return result

    def get_node_metadata(self, node, attr_name):
        result = self.send_and_receive_command(
            "GET_NODE_METADATA", node=node, attr_name=attr_name
        )
        return result

    def get_scene_metadata(self, attr_name):
        result = self.send_and_receive_command("GET_SCENE_METADATA", attr_name=attr_name)
        return result

    def get_columns_of_type(self, column_type):
        result = self.send_and_receive_command("GET_COLUMNS_OF_TYPE", column_type=column_type)
        return result

    def get_sound_column_filenames(self, column_name):
        result = self.send_and_receive_command(
            "GET_SOUND_COLUMN_FILENAMES", column_name=column_name
        )
        return result

    def relink_read_node(self, node, path):
        return self.send_and_receive_command("RELINK_READ_NODE", node=node, path=path)

    def relink_sound_column(self, column_name, path):
        return self.send_and_receive_command("RELINK_SOUND_COLUMN", column_name=column_name, path=path)

    def update_render_nodes(self, nodes):
        """
        Points each of the scene's Write nodes at its own Toolkit-computed
        output location/format. `nodes` is a list of dicts, one per Write
        node: {"node": <full node path>, "output_dir": ..., "base_name":
        ..., "file_format": ..., "leading_zeros": ...} — see
        python/tk_harmony/render_utils.py (discover_write_node_passes() +
        resolve_render_paths_for_pass()) for how the caller builds this.

        Deliberately does not trigger a render — see engine.py's "Update
        Render Nodes" command and configure.js's update_render_nodes() for
        why (the scripted render-trigger path never got a correctly-
        configured Write node to actually execute, across Sessions 14-17,
        and was retired).

        Uses send_and_receive (not fire-and-forget) so failures are
        surfaced immediately. Returns {"updated": [...], "failed": [...]}
        (full node paths in each list).
        """
        for entry in nodes:
            entry["output_dir"] = entry["output_dir"].replace("\\", "/")
        return self.send_and_receive_command("UPDATE_RENDER_NODES", nodes=nodes)

    def show_harmony_message(self, message, level="warning", title=None):
        """
        Shows a dialog inside Harmony's own (focused) process. level is
        "info" for a clean success (plain information icon/OK button) or
        "warning" (default, for backward compatibility) for anything the
        artist should treat as not-quite-right — never conflate the two,
        confirmed live that a success reported via the warning icon reads
        as an error. Deliberately NOT using engine.show_error()/
        show_message() — those call QMessageBox.exec_(), which nests a
        modal event loop this detached background process's window can
        never receive focus to dismiss (same class of bug already fixed
        for the Shotgun menu itself in menu_generation.py). Fire-and-
        forget; nothing to wait for.
        """
        self.send_command(
            "SHOW_HARMONY_MESSAGE", message=message, level=level, title=title
        )

    def export_camera_data(self, camera_node, start_frame, stop_frame):
        """
        Reads per-frame transform data for a camera node (and its driving
        Peg, if any) from the current scene. Uses send_and_receive (not
        fire-and-forget) so a failure — or an empty/malformed result — is
        surfaced immediately to the caller rather than producing a bogus
        published file. See configure.js's export_camera_data() for the
        NOT LIVE-VERIFIED caveats on the actual attribute names used.
        """
        return self.send_and_receive_command(
            "EXPORT_CAMERA_DATA",
            camera_node=camera_node,
            start_frame=start_frame,
            stop_frame=stop_frame,
        )
