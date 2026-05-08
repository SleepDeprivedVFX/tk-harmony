"use strict";

// -----------------------------------------------------------------------------
// resources/startup/bootstrap.js
//
// Harmony JS entry point for the ShotGrid Toolkit engine.
//
// Harmony loads this file by reading the environment variable
// SGTK_HARMONY_ENGINE_JS_STARTUP and calling include() on it.  This script
// performs a small number of guards and then delegates all real work to
// resources/packages/ShotgunBridge/configure.js, which contains the engine,
// server, and bridge logic.
//
// Constraints:
//   - ES5 only (no const/let/arrow functions/template literals) — Harmony's
//     Qt-based JS engine does not support ES6 syntax.
//   - Must not duplicate anything already handled by configure.js.
// -----------------------------------------------------------------------------

(function () {

    // -------------------------------------------------------------------------
    // Guard 1: Do not run in Harmony Paint (Pencil Check Pro) mode.
    // -------------------------------------------------------------------------
    if (about.isPaintMode()) {
        return;
    }

    // -------------------------------------------------------------------------
    // Guard 2: Require SGTK_ENGINE and SGTK_CONTEXT env vars.
    // Both are set by the Toolkit launch environment; their absence means we
    // were not launched through Toolkit and should not initialise.
    // -------------------------------------------------------------------------
    var sgtk_engine  = System.getenv("SGTK_ENGINE");
    var sgtk_context = System.getenv("SGTK_CONTEXT");

    if (!sgtk_engine || !sgtk_context) {
        MessageLog.trace(
            "ShotGrid bootstrap.js: SGTK_ENGINE or SGTK_CONTEXT is not set. " +
            "Toolkit engine will not be initialised."
        );
        return;
    }

    // -------------------------------------------------------------------------
    // Guard 3: Idempotency — do not run twice if the scene is reloaded or the
    // script block is triggered more than once in a single session.
    // -------------------------------------------------------------------------
    var app = QCoreApplication.instance();
    if (app.__SGTK_BOOTSTRAP_JS_LOADED__) {
        MessageLog.trace(
            "ShotGrid bootstrap.js: already loaded — skipping re-initialisation."
        );
        return;
    }
    app.__SGTK_BOOTSTRAP_JS_LOADED__ = true;

    // -------------------------------------------------------------------------
    // Locate configure.js via SGTK_HARMONY_ENGINE_RESOURCES_PATH.
    // startup.py guarantees all paths use forward slashes, even on Windows.
    // -------------------------------------------------------------------------
    var resources_path = System.getenv("SGTK_HARMONY_ENGINE_RESOURCES_PATH");

    if (!resources_path) {
        MessageLog.trace(
            "ShotGrid bootstrap.js: SGTK_HARMONY_ENGINE_RESOURCES_PATH is not set. " +
            "Cannot locate configure.js — engine will not start."
        );
        return;
    }

    var configure_js_path = resources_path + "/packages/ShotgunBridge/configure.js";

    MessageLog.trace(
        "ShotGrid bootstrap.js: loading configure.js from: " + configure_js_path
    );

    // -------------------------------------------------------------------------
    // Load the ShotgunBridge package.  include() evaluates configure.js in the
    // current JS context, making its top-level functions (including init())
    // available immediately after the call returns.
    // -------------------------------------------------------------------------
    include(configure_js_path);

    // -------------------------------------------------------------------------
    // Kick off the full engine startup sequence:
    //   init() -> Shotgun() -> bootstrap() -> spawns Python process
    //   Python connects -> DIR -> ENGINE_READY -> engine operational
    // -------------------------------------------------------------------------
    MessageLog.trace("ShotGrid bootstrap.js: calling init()");
    init();
    MessageLog.trace("ShotGrid bootstrap.js: init() returned");

}());
