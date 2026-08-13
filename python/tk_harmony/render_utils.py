# Copyright (c) 2026 Adam Benson
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.

"""
Shared render-path-resolution logic used by both the "Render Current
Version" standalone engine command (engine.py) and the Render publish
plugin (hooks/tk-multi-publish2/basic/publish_render.py). Factored out so
both share identical output_dir/base_name/leading_zeros computation instead
of two copies drifting apart — see Session 13, DEVELOPMENT_NOTES.txt, for
why the standalone command exists at all (in-publish render-completion
detection has proven unreliable across Harmony versions).
"""

import os
import glob


__author__ = "Adam Benson"
__contact__ = "https://www.linkedin.com/in/sleepdeprivedproductions/"


# common frame image extensions to look for when locating already-rendered
# frames (Write node output, or Harmony's own native output folder).
FALLBACK_FRAME_EXTENSIONS = ("png", "tga", "tif", "tiff", "jpg")

# {Shot}/{Asset} render templates are named identically apart from the
# entity-type prefix (see templates.yml) — map SG entity type to the pair.
RENDER_TEMPLATE_NAMES_BY_ENTITY_TYPE = {
    "Shot": ("harmony_shot_render_sequence", "harmony_shot_render_movie"),
    "Asset": ("harmony_asset_render_sequence", "harmony_asset_render_movie"),
}


class RenderPathError(Exception):
    """Raised when the current session/context can't be resolved to a
    render output path — always carries a message safe to show an artist
    directly (via a Harmony dialog or a publish validation error)."""
    pass


def resolve_render_paths(engine, image_format="PNG"):
    """
    Resolves the current Harmony session to a Toolkit-computed render
    output location, mirroring the Render publish plugin's validate()
    logic exactly. Returns a dict with output_dir, base_name, video_path,
    leading_zeros, sequence_template, movie_template, render_fields.

    Raises RenderPathError (message is artist-facing) if the session isn't
    saved, the context's entity type has no configured render templates,
    or the templates can't resolve against the current path.
    """
    current_path = engine.app.get_current_project_path()
    if not current_path or current_path == "Unknown":
        raise RenderPathError("The Harmony session has not been saved.")

    if engine.app.is_startup_project():
        raise RenderPathError(
            "The current project is the startup template and has not been "
            "saved to a pipeline path. Please save the session first."
        )

    entity_type = (engine.context.entity or {}).get("type")
    template_names = RENDER_TEMPLATE_NAMES_BY_ENTITY_TYPE.get(entity_type)
    if not template_names:
        raise RenderPathError(
            "No render templates configured for entity type '%s'." % entity_type
        )

    sequence_template = engine.get_template_by_name(template_names[0])
    movie_template = engine.get_template_by_name(template_names[1])
    if not sequence_template or not movie_template:
        raise RenderPathError(
            "Could not resolve the render sequence/movie templates (%s / %s). "
            "Check templates.yml." % template_names
        )

    work_template = engine.sgtk.template_from_path(current_path)
    if not work_template:
        raise RenderPathError(
            "Could not match the current session path against any Toolkit "
            "work template: %s" % current_path
        )
    work_fields = work_template.get_fields(current_path)

    render_fields = {}
    for key in sequence_template.keys:
        if key in work_fields:
            render_fields[key] = work_fields[key]

    if "version" not in render_fields:
        render_fields["version"] = work_fields.get("version", 1)
    if "name" not in render_fields:
        render_fields["name"] = work_fields.get("name", "render")

    try:
        # SEQ is a formatting placeholder, not a real frame number — build
        # the sequence path with a representative frame and derive the
        # glob/ffmpeg patterns from it (same approach as the publish plugin).
        sequence_fields = dict(render_fields)
        sequence_fields["SEQ"] = 1
        sample_frame_path = sequence_template.apply_fields(sequence_fields)
        output_dir = os.path.dirname(sample_frame_path)
        base_name = os.path.basename(sample_frame_path).split(".")[0]

        video_path = movie_template.apply_fields(render_fields)
    except Exception as e:
        raise RenderPathError("Could not resolve render templates to a path: %s" % e)

    # Harmony's LEADING_ZEROS attribute pads to a total width of
    # (LEADING_ZEROS + 1), not LEADING_ZEROS itself — see publish_render.py.
    seq_format_spec = sequence_template.keys["SEQ"].format_spec
    seq_width = int(seq_format_spec) if seq_format_spec else 4
    leading_zeros = max(seq_width - 1, 0)

    return {
        "output_dir": output_dir,
        "base_name": base_name,
        "video_path": video_path,
        "leading_zeros": leading_zeros,
        "sequence_template": sequence_template,
        "movie_template": movie_template,
        "render_fields": render_fields,
        "image_format": image_format,
    }


def find_rendered_frames(output_dir, base_name):
    """
    Looks for an already-rendered frame sequence matching base_name at
    output_dir. Shared by the publish plugin's "skip render if frames
    already exist" fast path and anything else that needs to check.
    """
    if not os.path.isdir(output_dir):
        return []

    for ext in FALLBACK_FRAME_EXTENSIONS:
        frames = sorted(glob.glob(os.path.join(output_dir, base_name + ".*." + ext)))
        if frames:
            return frames

    return []
