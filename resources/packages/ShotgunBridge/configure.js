"use strict";

// -----------------------------------------------------------------------------
// ShotgunBridge / configure.js
//
// Modernized from the original 2016-2019 code targeting Harmony 16.
// Tested API surface: Harmony 17 – 22+  (Qt 5.x JS engine / ES5+)
//
// Changes summary – see project commit message for full details.
// -----------------------------------------------------------------------------

function configure(packageFolder, packageName)
{
  if (about.isPaintMode())
    return;

  //---------------------------
  //Create Shortcuts
  ScriptManager.addShortcut( { id           : "ShotgunShortcut",
                               text         : "ShotGrid Menu ...",
                               action       : "ShotgunMenu in ./configure.js",
                               longDesc     : "Starts the ShotGrid connection",
                               order        : "256",
                               categoryId   : "Shotgun",
                               categoryText : "Scripts" } );

  //---------------------------
  //Create Menu items
  ScriptManager.addMenuItem( { targetMenuId : "Windows",
                               id           : "ShotgunMenuID",
                               icon         : "shotgun.png",
                               text         : "ShotGrid Menu ...",
                               action       : "ShotgunMenu in ./configure.js",
                               shortcut     : "ShotgunShortcut" } );

  //---------------------------
  //Create Toolbar
  // FIX: changed "false" string to boolean false — customizable expects a boolean
  var ShotgunToolbar = new ScriptToolbarDef( { id           : "ShotgunToolbar",
                                               text         : "Shotgun",
                                               customizable : false } );

  ShotgunToolbar.addButton( { text     : "Shotgun",
                              icon     : "shotgun.png",
                              action   : "ShotgunMenu in ./configure.js",
                              shortcut : "ShotgunShortcut" } );

  ScriptManager.addToolbar(ShotgunToolbar);
  init();
}

// -----------------------------------------------------------------------------
// Misc utilities
// -----------------------------------------------------------------------------
var META_SHOTGUN_PATH = "meta.shotgun.path";

function singleShotTimer(msec, callback)
{
    // Two prior attempts confirmed broken live on Harmony 25.2:
    //   1. t.setInterval()/t.changeInterval() instance methods — neither
    //      resolved to a function.
    //   2. The static QTimer.singleShot(msec, callback) convenience
    //      method — also undefined in this JS engine.
    // Both silently aborted every caller of singleShotTimer() (RENDER_SCENE
    // among them) before the deferred callback ever ran. This attempt sets
    // "interval" as a plain JS property instead of via a setter method —
    // QObject properties are commonly exposed this way in Harmony's
    // bindings, and t.singleShot = true below already relied on exactly
    // that pattern without ever erroring in any of the earlier attempts.
    // If even this throws, fall back to calling the callback synchronously
    // rather than leaving the caller permanently hung a third time — losing
    // the "let the socket finish processing first" deferral is a much
    // smaller problem than that.
    try {
        var t = new QTimer();
        t.interval = msec;
        t.singleShot = true;
        t.timeout.connect(function() {
            t.stop();
            callback();
        });
        t.start();
    } catch(e) {
        MessageLog.trace(
            "DIAGNOSTIC singleShotTimer: QTimer setup failed (" + e
            + "), falling back to a synchronous call."
        );
        callback();
    }
}

// -----------------------------------------------------------------------------
// Import/Reference resource methods
// -----------------------------------------------------------------------------

/*
Used to import resources into the scene.
Note that most of these methods are extracted from the example scripts.
*/

var PNGTransparencyMode       = 0; // Premultiplied with Black
var TGATransparencyMode       = 0; // Premultiplied with Black
var SGITransparencyMode       = 0; // Premultiplied with Black
var LayeredPSDTransparencyMode = 1; // Straight
var FlatPSDTransparencyMode   = 2; // Premultiplied with White


/* extract basename. Given a long filename with path and extension,
  return the name of the file without extension
   ie.  /Users/mbegin/MyFiles/image.png" ===> image
*/
function basename( filename )
{
  var pos = filename.lastIndexOf( "." );
  if( pos >= 0 )
    filename = filename.substr(0, pos);
  var name = filename.split("/");
  if( name.length > 0 )
    name = name[ name.length - 1 ];
  return name;
}


function getUniqueColumnName( column_prefix )
{
  var suffix = 0;
  var column_name = column_prefix;
  while (suffix < 2000)
  {
      if (!column.type(column_name))
          break;

      suffix = suffix + 1;
      column_name = column_prefix + "_" + suffix;
  }
  return column_name;
}

function copyFile( srcFilename, dstFilename )
{
  var srcFile = new PermanentFile(srcFilename);
  var dstFile = new PermanentFile(dstFilename);
  srcFile.copy(dstFile);
}

/*
  given a file (ie. a png, tga, tvg, 3d,...), create a new read module, column
  and element of the right type and put the file within it.

  @returns the name of the read node created so that it can be connected to the graph.
*/
function dropFileInNewElement( root, filename, transparency, alignmentRule )
{
  var vectorFormat = null;
  var extension = null;

  var pos = filename.lastIndexOf( "." );
  if( pos < 0 )
    return null;

  extension = filename.substr(pos + 1).toLowerCase();

  if( extension === "jpeg" )
    extension = "jpg";
  if( extension === "tvg" )
  {
    vectorFormat = "TVG";
    extension = "SCAN"; // element.add() will use this.
  }

  var name = basename(filename);
  var elemId = element.add(name, "BW", scene.numberOfUnitsZ(), extension.toUpperCase(), vectorFormat);
  if ( elemId === -1 )
  {
    // Unknown file type — skip it.
    return null;
  }

  var uniqueColumnName = getUniqueColumnName(name);
  column.add(uniqueColumnName, "DRAWING");
  column.setElementIdOfDrawing( uniqueColumnName, elemId );

  var read = node.add(root, name, "READ", 0, 0, 0);
  var transparencyAttr = node.getAttr(read, frame.current(), "READ_TRANSPARENCY");
  var opacityAttr      = node.getAttr(read, frame.current(), "OPACITY");
  transparencyAttr.setValue(true);
  opacityAttr.setValue(transparency);

  var alignmentAttr = node.getAttr(read, frame.current(), "ALIGNMENT_RULE");
  alignmentAttr.setValue(alignmentRule);

  var transparencyModeAttr = node.getAttr(read, frame.current(), "applyMatteToColor");
  if (extension === "png")
    transparencyModeAttr.setValue(PNGTransparencyMode);
  if (extension === "tga")
    transparencyModeAttr.setValue(TGATransparencyMode);
  if (extension === "sgi")
    transparencyModeAttr.setValue(SGITransparencyMode);
  if (extension === "psd")
    transparencyModeAttr.setValue(FlatPSDTransparencyMode);

  node.linkAttr(read, "DRAWING.ELEMENT", uniqueColumnName);

  var timing = "1"; // we're creating drawing name '1'

  Drawing.create(elemId, timing, true); // 'true' indicates that the file exists
  var drawingFilePath = Drawing.filename(elemId, timing); // actual path in tmp folder
  copyFile( filename, drawingFilePath );

  // Set exposure on all frames.
  var nframes = frame.numberOf();
  for( var i = 1; i <= nframes; ++i )
  {
    column.setEntry(uniqueColumnName, 1, i, timing);
  }

  return read; // name of the new drawing layer
}

/*
  given an ORDERED list of files (already sorted correctly by the Python
  caller — do not re-sort here, alphabetical sort of unpadded frame
  numbers was the exact cause of a previous scrambled-sequence bug, see
  publish_render.py's _native_frame_number), create ONE new element/
  column/READ node and import every file into it as a separate drawing
  timing, exposed sequentially. Used both for reloading a published
  Harmony Element (multiple drawings/timings, e.g. a turnaround) and for
  reloading a published Rendered Image sequence — same underlying shape,
  an element identified by many files rather than one.

  @returns the name of the read node created so that it can be connected
  to the graph, or null if file_paths was empty / an unknown file type.
*/
function importElementFromFiles( root, element_name, file_paths, transparency, alignmentRule )
{
  if (!file_paths || file_paths.length === 0)
    return null;

  var vectorFormat = null;
  var first = file_paths[0];
  var pos = first.lastIndexOf( "." );
  if( pos < 0 )
    return null;

  var extension = first.substr(pos + 1).toLowerCase();
  if( extension === "jpeg" )
    extension = "jpg";
  if( extension === "tvg" )
  {
    vectorFormat = "TVG";
    extension = "SCAN"; // element.add() will use this.
  }

  var elemId = element.add(element_name, "BW", scene.numberOfUnitsZ(), extension.toUpperCase(), vectorFormat);
  if ( elemId === -1 )
  {
    return null;
  }

  var uniqueColumnName = getUniqueColumnName(element_name);
  column.add(uniqueColumnName, "DRAWING");
  column.setElementIdOfDrawing( uniqueColumnName, elemId );

  var read = node.add(root, element_name, "READ", 0, 0, 0);
  var transparencyAttr = node.getAttr(read, frame.current(), "READ_TRANSPARENCY");
  var opacityAttr      = node.getAttr(read, frame.current(), "OPACITY");
  transparencyAttr.setValue(true);
  opacityAttr.setValue(transparency);

  var alignmentAttr = node.getAttr(read, frame.current(), "ALIGNMENT_RULE");
  alignmentAttr.setValue(alignmentRule);

  var transparencyModeAttr = node.getAttr(read, frame.current(), "applyMatteToColor");
  if (extension === "png")
    transparencyModeAttr.setValue(PNGTransparencyMode);
  if (extension === "tga")
    transparencyModeAttr.setValue(TGATransparencyMode);
  if (extension === "sgi")
    transparencyModeAttr.setValue(SGITransparencyMode);
  if (extension === "psd")
    transparencyModeAttr.setValue(FlatPSDTransparencyMode);

  node.linkAttr(read, "DRAWING.ELEMENT", uniqueColumnName);

  for (var i = 0; i < file_paths.length; i++)
  {
    // preserve the original drawing/timing name if the filename ends in
    // digits (e.g. "Prop-3.tvg" -> timing "3"), falling back to
    // sequential numbering — keeps fidelity with the source element
    // rather than silently renaming every drawing "1", "2", "3"...
    var srcFile = file_paths[i];
    var match = srcFile.match(/(\d+)\.\w+$/);
    var timing = match ? match[1] : String(i + 1);

    Drawing.create(elemId, timing, true);
    var drawingFilePath = Drawing.filename(elemId, timing);
    copyFile( srcFile, drawingFilePath );

    // exposed at sequential FRAME positions (1, 2, 3...) regardless of
    // the original timing name — a freshly-loaded element should play
    // its drawings back-to-back from frame 1.
    column.setEntry(uniqueColumnName, 1, i + 1, timing);
  }

  return read;
}

function dropMovieInNewElement( root, filename, transparency, alignmentRule, progress_callback )
{
  var extension = "png";
  if (typeof(progress_callback) === "undefined")
    progress_callback = MessageLog.trace;

  var pos = filename.lastIndexOf( "." );
  if( pos < 0 )
    return null;

  var name = basename(filename);
  var elemId = element.add(name, "COLOR", scene.numberOfUnitsZ(), extension.toUpperCase(), 0);
  if ( elemId === -1 )
  {
    return null;
  }

  var message = "Importing:\n\t" + name + "\n";
  progress_callback(message);

  var uniqueColumnName = getUniqueColumnName(name);
  column.add(uniqueColumnName, "DRAWING");
  column.setElementIdOfDrawing( uniqueColumnName, elemId );

  var read = node.add(root, name, "READ", 0, 0, 0);
  var transparencyAttr = node.getAttr(read, frame.current(), "READ_TRANSPARENCY");
  transparencyAttr.setValue(true);

  var transparencyModeAttr = node.getAttr(read, frame.current(), "applyMatteToColor");
  if (extension === "png")
      transparencyModeAttr.setValue(PNGTransparencyMode);

  node.linkAttr(read, "DRAWING.ELEMENT", uniqueColumnName);

  var image_folder = specialFolders.temp + "/" + column.generateAnonymousName() + "/";
  var dir = new Dir();
  dir.path = image_folder;
  dir.mkdirs();

  message += "\nConverting movie into images....\n\n";
  progress_callback(message);

  MovieImport.setMovieFilename(filename);
  MovieImport.setImageFolder(image_folder);
  MovieImport.setImagePrefix(name);
  MovieImport.setAudioFile(image_folder + "/" + name + ".wav");

  MovieImport.doImport();

  var image_count = MovieImport.numberOfImages();

  for (var i = 1; i <= image_count; i++)
  {
      // FIX: removed duplicate `var message` re-declaration inside the loop
      //      (was a block-scoping issue under strict mode).
      message = "Importing:\n\t" + name + "\n";
      message += "\nCreating drawings " + i.toString() + " of " + image_count.toString() + "\n\n";
      progress_callback(message);

      var timing = i.toString();
      var image_path = image_folder + name + "-" + timing + ".png";
      Drawing.create(elemId, timing, true);
      var drawingFilePath = Drawing.filename(elemId, timing);

      copyFile( image_path, drawingFilePath );
      column.setEntry(uniqueColumnName, 1, i, timing);
  }

  message = "Importing:\n\t" + name + "\n";
  message += "\nDone.\n\n";
  // Last callback with a timer to auto-close the busy dialog.
  progress_callback(message, 3000);
  return read;
}

// Helper: return the engine if it is ready to use.
function _get_engine()
{
    var app    = QCoreApplication.instance();
    var engine = app.shotgun_engine;

    if (engine != null && engine.is_engine_ready)
        return engine;
    // implicit return undefined when not ready — callers already guard for null/undefined
}

function import_image(filename, parent)
{
  if (parent === undefined)
    parent = node.root();

  var transparency  = null;
  var alignmentRule = null;
  var read_node = dropFileInNewElement(parent, filename, transparency, alignmentRule);
  return read_node;
}

function import_sound(filename)
{
    var column_name = getUniqueColumnName(basename(filename));
    // FIX: `frame` was shadowed by the outer Harmony `frame` global here.
    //      Use Timeline.firstFrameSel for the insertion point.
    var insert_frame = Timeline.firstFrameSel;
    column.add(column_name, "SOUND");
    // FIX: was missing `var` — result leaked into the global scope.
    var result = column.importSound(column_name, insert_frame, filename);

    // There is no way to attach metadata to sound columns, so we store
    // the source path at scene level. This breaks if the column is renamed.
    setSceneMetadata(column_name + "." + META_SHOTGUN_PATH, filename);

    return result;
}

function import_movie(filename, parent)
{
  if (parent === undefined)
    parent = node.root();

  var transparency  = null;
  var alignmentRule = null;
  var engine = _get_engine();

  function progress_callback(message, close_on_elapsed_time)
  {
    if (engine != null)
    {
        engine.show_busy("Importing Movie...", message, close_on_elapsed_time);
        System.processOneEvent();
    }
  }

  if (engine != null)
    engine.clear_busy();

  var read_node = dropMovieInNewElement(parent, filename, transparency, alignmentRule, progress_callback);

  return read_node;
}


// -----------------------------------------------------------------------------
// Meta Data related functions
// -----------------------------------------------------------------------------

function setSceneMetadata(attrName, value)
{
    scene.setMetadata({ "name": attrName, "type": "string", "value": value });
}

function getSceneMetadata(attrName)
{
    var meta = scene.metadata(attrName);
    return meta && meta.value ? meta.value : "";
}

function removeSceneMetadata(attrName)
{
    scene.setMetadata({ "name": attrName, "type": "string", "value": "" });
}

function getNodeMetadata(nodeName, attrName)
{
    return node.getTextAttr(nodeName, 1, attrName);
}

function setNodeMetadata(nodeName, attrName, value)
{
    var visualAttrName = attrName;
    var idx = attrName.lastIndexOf(".");
    if (idx >= 0)
    {
      visualAttrName = attrName.substr(idx + 1);
    }

    var attr = node.getAttr(nodeName, 1.0, attrName);
    if (attr.keyword() === "")
    {
        if (node.createDynamicAttr(nodeName, "STRING", attrName, visualAttrName, false))
        {
          attr = node.getAttr(nodeName, 1.0, attrName);
        }

        if (attr.keyword() !== "")
        {
            node.setTextAttr(nodeName, attrName, 1.0, value || visualAttrName);
        }
    }
    else
    {
        node.setTextAttr(nodeName, attrName, 1.0, value || visualAttrName);
    }
}

function removeNodeMetadata(nodeName, attrName)
{
    node.removeDynamicAttr(nodeName, attrName);
}

function renameNodeMetadata(nodeName, oldName, newName)
{
    var value = getNodeMetadata(nodeName, oldName);
    setNodeMetadata(nodeName, newName, value);
    removeNodeMetadata(nodeName, oldName);
}

// -----------------------------------------------------------------------------
// Engine related classes, methods
// -----------------------------------------------------------------------------

this.debug = true;

function log_debug(data)
{
    // FIX: `message` was an implicit global — now declared with var.
    var message = typeof(data.message) !== "undefined" ? data.message : data;

    if (this.debug)
        MessageLog.trace("(DEBUG) Shotgun bridge: " + message.toString());
}


function log_info(data)
{
    var message = typeof(data.message) !== "undefined" ? data.message : data;
    MessageLog.trace("(INFO) Shotgun bridge: " + message.toString());
}


function log_warning(data)
{
    var message = typeof(data.message) !== "undefined" ? data.message : data;
    MessageLog.trace("(WARNING) Shotgun bridge: " + message.toString());
}


function log_error(data)
{
    var message = typeof(data.message) !== "undefined" ? data.message : data;
    MessageLog.trace("(ERROR) Shotgun bridge: " + message.toString());
}


function log_exception(data)
{
    var message = typeof(data.message) !== "undefined" ? data.message : data;
    MessageLog.trace("(EXCEPTION) Shotgun bridge: " + message.toString());
}


function find_widgets(widgetNode, node_name, node_text, stop_if_found, level, result)
{
    if (typeof(level) === "undefined")
        level = 0;

    if (typeof(stop_if_found) === "undefined")
        stop_if_found = false;

    if (typeof(result) === "undefined")
        result = [];

    if (widgetNode.objectName === node_name)
    {
        result.push(widgetNode);
        if (stop_if_found)
            return result;
    }

    if (node_text && widgetNode.text && widgetNode.text.toString().indexOf(node_text) > -1)
    {
        result.push(widgetNode);
        if (stop_if_found)
            return result;
    }

    // FIX: `for (i in ...)` enumerated array indices as strings AND any
    //      enumerable prototype properties.  Use a standard numeric for-loop.
    var children = widgetNode.children();
    for (var i = 0; i < children.length; i++)
    {
        find_widgets(children[i], node_name, node_text, stop_if_found, level + 1, result);
    }
    return result;
}


function ask_question(title, message, default_option)
{
    var msgBox = new QMessageBox();
    msgBox.setWindowTitle(title);
    msgBox.text = message;
    msgBox.addButton(QMessageBox.Yes);
    msgBox.addButton(QMessageBox.No);

    if (default_option === undefined)
        default_option = QMessageBox.Yes;

    msgBox.setDefaultButton(default_option);
    return msgBox.exec();
}


function Server(host, port)
{
    var self = this;
    self.name = "Server";
    self.socket = new QTcpServer(this);
    self.host = new QHostAddress(host);
    self.port = port;
    self.active = false;
    self.connection = null;
    self._block_size = 0;
    self.INT32_SIZE = 4;
    self.MAX_READ_RESPONSE_TIME = 5000;

    self.log_debug     = log_debug;
    self.log_info      = log_info;
    self.log_warning   = log_warning;
    self.log_error     = log_error;
    self.log_exception = log_exception;
    self.debug = true;

    // rpc-ish
    self.m_id        = 0;
    self._callbacks  = null;
    self._responses  = {};

    self.start = function()
    {
        self.active      = false;
        self.connection  = null;
        self._block_size = 0;
        self.register_command("DIR", self.list_methods);

        if (self.socket.listen(self.host, self.port))
        {
            self.log_debug("Local Server started: " + self.host.toString() + ":" + self.port);
            self.active = true;
            self.socket.newConnection.connect(self, self.on_new_connection);
            return true;
        }
        else
        {
            self.active = false;
            self.log_error("Local Server could not start! " + self.host.toString() + ":" + self.port);
            return false;
        }
    };

    self.close = function()
    {
        self.active = false;
        self.socket.close();
    };

    self.list_methods = function()
    {
        var commands = [];
        for (var command in self._callbacks)
            commands.push(command);
        return commands;
    };

    self.register_command = function(command, callback)
    {
      if (self._callbacks === null)
        self._callbacks = {};

      self._callbacks[command] = callback;
    };

    self._send = function(command)
    {
        if (self.socket && self.connection)
        {
            self.log_debug("Connection status: " + self.connection.state());
            self.log_debug("Connection valid: "  + self.connection.isValid());

            command = command.toString();

            var data = new QByteArray();

            // FIX: `outstr` was an implicit global — now declared with var.
            var outstr = new QDataStream(data, QIODevice.WriteOnly);
            // NOTE: QDataStream.Qt_4_6 remains valid in Qt 5; no change needed.
            outstr.setVersion(QDataStream.Qt_4_6);
            outstr.writeInt(0);

            data.append(command);

            outstr.device().seek(0);
            outstr.writeInt(data.size() - 4);

            var written = self.connection.write(data);
            self.log_debug("Written len: " + written);
        }
        else
        {
            self.log_debug("No connection, message lost!: " + command);
        }
    };


    self._receive = function()
    {
        self.log_debug("Receiving data ... ");

        var stream = new QDataStream();
        stream.setDevice(self.connection);
        stream.setVersion(QDataStream.Qt_4_6);

        self.log_debug("self.connection.bytesAvailable() ... " + self.connection.bytesAvailable());
        var i = 0;
        while (self.connection.bytesAvailable() > 0)
        {
            self.log_debug("Request number: " + i);

            if ( (self._block_size === 0 && self.connection.bytesAvailable() >= self.INT32_SIZE) ||
                 (self._block_size > 0   && self.connection.bytesAvailable() >= self._block_size) )
            {
                self._block_size = stream.readInt();
                self.log_debug("Request number: " + i + " | block size: " + self._block_size);
            }

            if (self._block_size > 0 && self.connection.bytesAvailable() >= self._block_size)
            {
                var data = self.connection.read(self._block_size);

                // Build the request string from raw bytes.
                var request = "";
                for ( var j = 0; j < data.size(); j++ )
                {
                    if (data.at(j) > 0)
                    {
                        request = request.concat(String.fromCharCode(data.at(j)));
                    }
                }
                self.log_debug("Request number: " + i + " | About to process | Request: " + request);
                self._process_request(request);
                self._block_size = 0;
                i += 1;
            }
        }
    };

    self._prepare_request = function(command, data, request_return)
    {
        self.m_id += 1;
        // FIX: `request_id` was an implicit global — now declared with var.
        var request_id = self.m_id;
        var request = { "jsonrpc"        : "2.0",
                        "method"         : command,
                        "params"         : data,
                        "request_return" : request_return,
                        "id"             : request_id };
        // FIX: removed the second `var request = ...` re-declaration; just
        //      stringify in place.
        return JSON.stringify(request);
    };

    self._prepare_reply = function(request_id, result)
    {
        var reply_obj = { "jsonrpc"        : "2.0",
                          "result"         : result,
                          "request_return" : false,
                          "id"             : request_id };
        return JSON.stringify(reply_obj);
    };

    self._prepare_error = function(request_id, error)
    {
        var error_obj = { "jsonrpc" : "2.0",
                          "error"   : error || null,
                          "id"      : request_id };
        return JSON.stringify(error_obj);
    };

    self._process_request = function(request)
    {
        var command;
        self.log_info("_process_request | Request: " + request);

        // Check for well-formed JSON
        try
        {
            command = JSON.parse(request);
        }
        catch(err)
        {
            self.log_warning("Ignoring request, not well formed. | Request: " + request);
            return;
        }

        // Check there is a request id
        var request_id = command.id;
        if (request_id == null)
        {
            self.log_warning("Ignoring request, not well formed. | Request: " + request);
            return;
        }

        // A function call
        if (command.method != null)
        {
            self.log_debug("A function call. " + request);
            var method          = command.method.toUpperCase();
            var params          = command.params;
            var return_requested = command.request_return;

            self.log_debug("Command method : " + method);
            self.log_debug("Command return requested : " + (return_requested === true));
            self.log_debug("Command method recognised: " + (method in self._callbacks));

            if (self._callbacks && method in self._callbacks)
            {
                try
                {
                   var result = self._callbacks[method](params);
                   if (return_requested === true)
                        self.send_reply(request_id, result);
                }
                catch(err)
                {
                   self.log_error("An error occurred executing callback for method: " + method + " and params: " + params);
                   self.log_error(err.message);
                }
            }
            else
            {
                self.log_warning("Command received was ignored: " + command);
            }
        }
        // A result that we requested
        else if (command.result != null)
        {
            self.log_debug("This was a result | Result: " + request);
            self._responses[request_id] = command.result;
        }
        // An error that happened on the client side
        else if (command.error != null)
        {
            self.log_error("Error occurred when requesting command. " + command.error);
        }
    };

    self.send_and_receive_command = function(method, data)
    {
        // Request a return value
        var request = self._prepare_request(method, data, true);
        // FIX: _prepare_request now returns a JSON string (not an object),
        //      so we cannot read .id from it.  Extract the id from m_id
        //      which was just incremented by _prepare_request.
        var request_id = self.m_id;

        var st = new QTime();
        st.start();

        self._send(request);
        self.log_debug("Sent request in " + st.elapsed() + " ms | Request: " + request);

        self.log_debug("Waiting to receive data...");

        var result = null;
        var st_response = new QTime();
        st_response.start();

        self.connection.waitForReadyRead(self.MAX_READ_RESPONSE_TIME);
        while (true)
        {
            System.processOneEvent();
            if (request_id in self._responses)
            {
                result = self._responses[request_id];
                self.log_debug("Received command result in " + st_response.elapsed() + " ms | Request ID: " + request_id + " | Result: " + result);
                break;
            }

            // FIX: `logger.debug` does not exist in this scope — use self.log_debug.
            // FIX: `st_response_elapsed` was an undefined variable — use st_response.elapsed().
            var st_response_elapsed = st_response.elapsed();
            self.log_debug("st_response elapsed " + st_response_elapsed + " ms | max : " + self.MAX_READ_RESPONSE_TIME + " | responses : " + self._responses);
            if (st_response_elapsed > self.MAX_READ_RESPONSE_TIME)
            {
                self.log_debug("Did not receive command result in " + st_response.elapsed() + " ms | Request ID: " + request_id + " | Responses: " + self._responses);
                break;
            }
        }

        self.log_debug("Done send and receive in " + st.elapsed() + " ms.");
        return result;
    };

    self.send_command = function(command, data)
    {
        var request = self._prepare_request(command, data);
        self.log_debug("Command sent: " + request);
        self._send(request);
    };

    self.send_reply = function(request_id, result)
    {
        try
        {
            var reply = self._prepare_reply(request_id, result);
            MessageLog.trace("(DEBUG) Sending Response:" + reply);
            self._send(reply);
        }
        catch(err)
        {
            // FIX: `message_id` was undefined — replaced with request_id.
            var error_reply = self._prepare_error(request_id, err);
            self.log_error("Unexpected error while sending reply for request id: " + request_id + " — " + err.message);
            self._send(error_reply);
        }
    };

    self.on_connection_error = function(socket_error)
    {
        self.log_error("Connection error happened. " + socket_error.toString());
    };

    self.on_connection_disconnected = function()
    {
        self.log_debug("Client disconnected.");
        self.connection = null;
    };

    self.on_new_connection = function()
    {
        self.log_debug("New connection detected:");
        if (self.socket.hasPendingConnections())
        {
            self.connection = self.socket.nextPendingConnection();

            var state = self.connection.state();

            self.connection.readyRead.connect(self, self._receive);
            // FIX: QAbstractSocket::error signal was renamed to
            //      errorOccurred in Qt 5.15 / Harmony 21+.
            //      Connect to both signal names defensively.
            if (typeof self.connection.errorOccurred !== "undefined") {
                self.connection.errorOccurred.connect(self, self.on_connection_error);
            } else {
                self.connection.error.connect(self, self.on_connection_error);
            }
            self.connection.disconnected.connect(self, self.on_connection_disconnected);

            self.log_debug("Connection state: " + state);
            self.log_debug("Client connected: " + self.connection.toString());

            self.send_and_receive_command("PING", {});
        }
        else
        {
            self.log_debug("-----------------------------------------------------------------------------");
            // FIX: Python-style `%s %` string formatting does not work in JS.
            //      Replaced with string concatenation.
            self.log_debug("No pending connections!: " + (self.connection ? self.connection.toString() : "null"));
        }
    };
}



var app = QCoreApplication.instance();

function Engine()
{
    var self = this;
    self.app    = QCoreApplication.instance();
    self.name   = "Shotgun Engine";
    self.window = QApplication.activeWindow();
    self.server = null;
    self.log_debug     = log_debug;
    self.log_info      = log_info;
    self.log_warning   = log_warning;
    self.log_error     = log_error;
    self.log_exception = log_exception;
    self.debug = true;
    self.is_engine_ready = false;
    self.on_engine_ready_callbacks = [];

    // ------------------------------------------------------------------------
    // Local Engine methods
    // ------------------------------------------------------------------------

    self._create_busy_dialog = function()
    {
        var resources_path = System.getenv("SGTK_HARMONY_ENGINE_RESOURCES_PATH");
        var ui_file   = resources_path + "/ui/busy_dialog.ui";
        var icon_file = resources_path + "/ui/sg_logo_80px.png";
        var ui = UiLoader.load(ui_file);
        ui.windowTitle = "ShotGrid Harmony Engine";

        var icon_widget    = ui.frame.horizontalLayout.itemAt(0).widget();
        var title_widget   = ui.frame.horizontalLayout.verticalLayout.itemAt(0).widget();
        var details_widget = ui.frame.horizontalLayout.verticalLayout.itemAt(1).widget();

        icon_widget.text    = "<html><img src='" + icon_file + "'></html>";
        title_widget.text   = "";
        details_widget.text = "";
        return ui;
    };

    self.show_busy_dialog = self._create_busy_dialog();

    self.show_busy = function(title, message, close_on_elapsed_time)
    {
        if (self.show_busy_dialog == null)
            self.show_busy_dialog = self._create_busy_dialog();

        var ui = self.show_busy_dialog;
        var title_widget   = ui.frame.horizontalLayout.verticalLayout.itemAt(0).widget();
        var details_widget = ui.frame.horizontalLayout.verticalLayout.itemAt(1).widget();
        title_widget.text   = title;
        details_widget.text = message;
        ui.show();

        if (typeof close_on_elapsed_time !== "undefined")
        {
            singleShotTimer(close_on_elapsed_time, function() { ui.hide(); });
        }
    };

    self.clear_busy = function()
    {
        if (self.show_busy_dialog != null)
            self.show_busy_dialog.hide();
    };

    self.set_main_window = function(widget)
    {
        self.window = widget;
    };

    // ------------------------------------------------------------------------
    // Harmony Scene operations
    // ------------------------------------------------------------------------
    self.extract_thumbnail = function()
    {
        if (self.window != null)
        {
            // FIX: `f` and `filename` were implicit globals.
            var f = new TemporaryFile("png");
            var filename = f.path();
            f.close();

            // NOTE: QPixmap.grabWindow(winId) is deprecated in Qt 5.x and
            // removed in Qt 6. Use QScreen.grabWindow() instead when available.
            // This requires live Harmony testing to verify the correct approach
            // on the studio's specific Harmony version.
            var result = find_widgets(self.window, "ContainGLWidget", null, true);
            if (result.length > 0) {
                var p = QPixmap.grabWindow(result[0].winId());
                p.save(filename, "png");
                return filename;
            }
            self.log_warning("extract_thumbnail: ContainGLWidget not found.");
        }
        return "";
    };

    self.get_version = function(data)
    {
        // FIX: the previous regex required a space on BOTH sides of the
        //      version number (/.* (\d+\.\d+\.\d+) .*/), which fails to
        //      match whenever the version happens to be at the very end of
        //      the string (no trailing space) — a real risk since this
        //      format is not documented and varies across Harmony builds.
        //      Search for the version pattern anywhere in the string instead.
        var regex = /(\d+\.\d+\.\d+)/;
        var version_info = about.getVersionInfoStr();
        var version_re = regex.exec(version_info);

        if (version_re && version_re[1])
            return version_re[1];

        self.log_warning("get_version: could not parse version from: " + version_info);
        return "";
    };

    self.engine_restart = function(data)
    {
        // The python engine is about to be restarted; mark it as not ready.
        self.is_engine_ready = false;
    };

    self.engine_ready = function(data)
    {
        MessageLog.trace("Engine is operational, we can ask for its menu now!");
        self.is_engine_ready = true;
        for (var i = 0; i < self.on_engine_ready_callbacks.length; i++)
            self.on_engine_ready_callbacks[i]();
    };

    self.execute_statement = function(data)
    {
        try
        {
          scene.beginUndoRedoAccum("Execute Statement");
          // NOTE: eval() is intentionally used here; the Python engine sends
          // JS snippets that are meant to be evaluated in the Harmony context.
          var result = eval(data.statement); // jshint ignore:line
          scene.endUndoRedoAccum();
          return result;
        }
        catch (err)
        {
          scene.cancelUndoRedoAccum();
          self.log_exception(err);
          return false;
        }
    };

    self.toggle_debug_logging = function(data)
    {
        self.debug = data.enabled;
    };

    self.current_project_path = function(data)
    {
        return scene.currentProjectPath() + "/" + scene.currentVersionName() + ".xstage";
    };

    self.current_project_folder = function(data)
    {
        return scene.currentProjectPath();
    };

    self.open_project = function(data)
    {
        var path = data.path;
        MessageLog.trace("SceneOperations: open - Action");
        self.window.requestOpenScene(path);
        self.refresh_title();
        return scene.currentProjectPath();
    };

    self.save_project = function(data)
    {
        var result = scene.saveAll();
        self.refresh_title();
        return scene.currentProjectPath();
    };

    self.save_new_version_action = function(data)
    {
        Action.perform("onActionSaveAsScene");
    };

    self.save_new_version = function(data)
    {
        var version_name = data.version_name;
        MessageLog.trace("SceneOperations: save_new_version - Action");
        MessageLog.trace("SceneOperations: save_new_version - version_name : " + version_name);

        scene.saveAsNewVersion(version_name, true);
        scene.saveAll();
        self.refresh_title();

        return scene.currentProjectPath();
    };

    self.needs_saving_project = function(data)
    {
        return scene.isDirty();
    };

    self.close_project = function(data)
    {
        // We do not really close the project; instead we reopen the startup template.
        // FIX: was passing the `scene` global object instead of the startup path string.
        var startup_project = System.getenv("SGTK_HARMONY_ENGINE_STARTUP_PROJECT");
        self.window.requestOpenScene(startup_project);
        self.refresh_title();
    };

    self.is_startup_project = function(data)
    {
        var sg_metadata = scene.metadata("Shotgun Toolkit Engine");
        if (sg_metadata != null)
            return sg_metadata.value === "Startup template";
        return false;
    };

    // Timeline
    self.get_start_frame = function(data)
    {
        return scene.getStartFrame();
    };

    self.set_start_frame = function(data)
    {
        scene.beginUndoRedoAccum("Set Start Frame");
        scene.setStartFrame(data.start_frame);
        var start_frame = scene.getStartFrame();
        // FIX: `start_frame_metadata` was an implicit global — now uses var.
        var start_frame_metadata = {
                                      "name"    : "sg_start_frame",
                                      "type"    : "int",
                                      "creator" : "Shotgun Harmony Engine",
                                      "version" : "1.0",
                                      "value"   : start_frame
                                   };
        scene.setMetadata(start_frame_metadata);
        scene.endUndoRedoAccum();
        return start_frame;
    };

    self.get_stop_frame = function(data)
    {
        return scene.getStopFrame();
    };

    self.set_stop_frame = function(data)
    {
        scene.beginUndoRedoAccum("Set Stop Frame");
        scene.setStopFrame(data.stop_frame);
        var stop_frame = scene.getStopFrame();
        // FIX: `stop_frame_metadata` was an implicit global — now uses var.
        var stop_frame_metadata = {
                                      "name"    : "sg_stop_frame",
                                      "type"    : "int",
                                      "creator" : "Shotgun Harmony Engine",
                                      "version" : "1.0",
                                      "value"   : stop_frame
                                   };
        scene.setMetadata(stop_frame_metadata);
        scene.endUndoRedoAccum();
        return stop_frame;
    };

    self.get_frame_range = function(data)
    {
        var start_frame = scene.getStartFrame();
        var stop_frame  = scene.getStopFrame();
        return { start_frame: start_frame, stop_frame: stop_frame };
    };

    self.get_frame_count = function(data)
    {
        return frame.numberOf();
    };

    self.set_frame_count = function(data)
    {
        scene.beginUndoRedoAccum("Set Frame Count");

        var current_frame_count = self.get_frame_count();
        var frame_count = data.frame_count;

        if (frame_count > current_frame_count)
        {
            frame.insert(current_frame_count, frame_count - current_frame_count);
        }
        else
        {
            frame.remove(current_frame_count, current_frame_count - frame_count);
        }
        scene.endUndoRedoAccum();

        return self.get_frame_count();
    };

    self.set_frame_range = function(data)
    {
        scene.beginUndoRedoAccum("Set Frame Range");
        var start_frame = self.set_start_frame(data);
        var stop_frame  = self.set_stop_frame(data);
        scene.endUndoRedoAccum();
        return { start_frame: start_frame, stop_frame: stop_frame };
    };

    self.get_frame_rate = function(data)
    {
        return scene.getFrameRate();
    };

    // Actions
    self.import_drawing = function(data)
    {
        scene.beginUndoRedoAccum("Import Drawing");
        var path = data.path;
        var read_node = import_image(path);
        setNodeMetadata(read_node, META_SHOTGUN_PATH, path);
        scene.endUndoRedoAccum();
        return read_node;
    };

    self.import_audio = function(data)
    {
        scene.beginUndoRedoAccum("Import Audio");
        var path = data.path;
        var result = import_sound(path);
        scene.endUndoRedoAccum();
        return result;
    };

    self.import_clip = function(data)
    {
        scene.beginUndoRedoAccum("Import Movie");
        var path = data.path;
        var read_node = import_movie(path);
        setNodeMetadata(read_node, META_SHOTGUN_PATH, path);
        scene.endUndoRedoAccum();
        return read_node;
    };

    self.import_element_files = function(data)
    {
        // used for both Harmony Element (multi-drawing) and Rendered
        // Image sequence reload — see importElementFromFiles() above.
        // Python resolves and sorts file_paths before this is called;
        // this function does not touch the filesystem beyond the copies
        // importElementFromFiles() itself performs.
        scene.beginUndoRedoAccum("Import Element");
        var element_name = data.element_name;
        var file_paths    = data.file_paths;
        var read_node = null;
        try
        {
            // null/null matches import_image()'s own established
            // transparency/alignmentRule defaults for a freshly dropped
            // element, rather than guessing a new value.
            read_node = importElementFromFiles(node.root(), element_name, file_paths, null, null);
            if (read_node !== null)
            {
                setNodeMetadata(read_node, META_SHOTGUN_PATH, data.source_path || "");
            }
        }
        catch(e)
        {
            scene.cancelUndoRedoAccum();
            self.log_exception("IMPORT_ELEMENT_FILES failed: " + e);
            return false;
        }
        scene.endUndoRedoAccum();
        return read_node;
    };

    self.import_palette = function(data)
    {
        // Guaranteed-value baseline: a Harmony palette IS just a .plt
        // file sitting in the scene's own palette-library/ folder
        // (confirmed on disk via the startup/newfile templates while
        // building the Palette publisher) — so copying the published
        // .plt in there is real, working functionality on its own, with
        // no dependency on any uncertain scripting API.
        //
        // NOT LIVE-VERIFIED, best-effort ONLY: this also attempts to
        // register the palette with PaletteObjectManager so it shows up
        // in the Palette panel immediately without a scene reload. The
        // exact scripting API for "import an existing .plt's contents"
        // (as opposed to creating a new empty palette) is unconfirmed for
        // this Harmony version — wrapped in its own try/catch so a
        // failure here does NOT undo the file copy above. If this
        // doesn't work live, the palette should still appear the next
        // time the scene is opened, or via Harmony's own Palette panel
        // "Import Palette" pointed at the copied file.
        var source_path = data.path;

        try
        {
            var project_folder = scene.currentProjectPath();
            var palette_library_dir = project_folder + "/palette-library";

            var baseName = basename(source_path);
            var destPath = palette_library_dir + "/" + baseName + ".plt";

            // avoid clobbering an existing palette of the same name
            var suffix = 0;
            while ((new PermanentFile(destPath)).exists())
            {
                suffix += 1;
                destPath = palette_library_dir + "/" + baseName + "_" + suffix + ".plt";
            }

            copyFile(source_path, destPath);

            var live_registered = false;
            try
            {
                // DIAGNOSTIC / NOT LIVE-VERIFIED — report what's actually
                // available so this can be corrected against ground truth.
                self.log_warning("DIAGNOSTIC IMPORT_PALETTE PaletteObjectManager available: "
                    + (typeof PaletteObjectManager !== "undefined"));
                if (typeof PaletteObjectManager !== "undefined")
                {
                    var paletteList = PaletteObjectManager.getScenePaletteList();
                    // best-effort guess at the scripting call — unconfirmed.
                    paletteList.insertPaletteFile(destPath, paletteList.numPalettes, baseName, false);
                    live_registered = true;
                }
            }
            catch(liveErr)
            {
                self.log_warning("DIAGNOSTIC IMPORT_PALETTE live registration failed (file copy "
                    + "still succeeded, palette will appear on next scene open): " + liveErr);
            }

            return { "success": true, "path": destPath, "live_registered": live_registered };
        }
        catch(e)
        {
            self.log_exception("IMPORT_PALETTE failed: " + e);
            return { "success": false, "error": e.toString() };
        }
    };

    self.import_template = function(data)
    {
        // NOT LIVE-VERIFIED — needs Sarah to confirm against Harmony 25.2
        // in the Script Editor before this is trusted.
        //
        // copyPaste.pasteTemplateIntoScene(srcPath, dstNode, startFrame,
        // pasteOptions) is the function documented in Toon Boom's
        // scripting reference for importing a .tpl the same way dragging
        // it out of the Library panel does. Argument order/names and
        // exact behaviour (what "dstNode" should be, whether pasteOptions
        // can be null) are unconfirmed for this Harmony version — test
        // with a real .tpl and adjust as needed. The path this receives
        // is the .tpl FOLDER's path (see harmony_asset_template_publish /
        // harmony_shot_template_publish in templates.yml).
        var path = data.path;

        scene.beginUndoRedoAccum("Import Template");
        try
        {
            copyPaste.pasteTemplateIntoScene(path, node.root(), 1, null);
        }
        catch(e)
        {
            scene.cancelUndoRedoAccum();
            self.log_exception("IMPORT_TEMPLATE failed: " + e);
            return false;
        }
        scene.endUndoRedoAccum();
        return true;
    };

    self.get_node_metadata = function(data)
    {
        // FIX: renamed local `node` variable to `node_name` to avoid
        //      shadowing the Harmony global `node` object.
        var node_name = data.node;
        var attr_name = data.attr_name;
        return getNodeMetadata(node_name, attr_name);
    };

    self.get_scene_metadata = function(data)
    {
        var attr_name = data.attr_name;
        return getSceneMetadata(attr_name);
    };

    self.get_nodes_of_type = function(data)
    {
        var node_types = data.node_types;
        return node.getNodes(node_types);
    };

    self.get_columns_of_type = function(data)
    {
        var column_type = data.column_type;
        return column.getColumnListOfType(column_type);
    };

    self.get_sound_column_filenames = function(data)
    {
        var column_name    = data.column_name;
        var sound_col      = column.soundColumn(column_name);
        var sound_sequences = sound_col.sequences();
        var sound_filenames = [];

        for (var j = 0; j < sound_sequences.length; j++)
        {
            var sound_sequence = sound_sequences[j];
            var sound_filename = sound_sequence.filename;
            if (sound_filename !== undefined)
                sound_filenames.push(sound_filename);
        }

        return sound_filenames;
    };

    self.relink_read_node = function(data)
    {
        var node_name = data.node;
        var new_path  = data.path;

        scene.beginUndoRedoAccum("Relink Read Node");
        try
        {
            var col_name  = node.linkedColumn(node_name, "DRAWING.ELEMENT");
            var elem_id   = column.getElementIdOfDrawing(col_name);
            var draw_path = Drawing.filename(elem_id, "1");
            copyFile(new_path, draw_path);
            setNodeMetadata(node_name, "meta.shotgun.path", new_path);
            scene.endUndoRedoAccum();
        }
        catch(e)
        {
            scene.cancelUndoRedoAccum();
            self.log_exception("RELINK_READ_NODE failed: " + e);
            return false;
        }
        return node_name;
    };

    self.relink_sound_column = function(data)
    {
        var col_name = data.column_name;
        var new_path = data.path;

        scene.beginUndoRedoAccum("Relink Sound Column");
        try
        {
            column.importSound(col_name, 1, new_path);
            setSceneMetadata(col_name + ".meta.shotgun.path", new_path);
            scene.endUndoRedoAccum();
        }
        catch(e)
        {
            scene.cancelUndoRedoAccum();
            self.log_exception("RELINK_SOUND_COLUMN failed: " + e);
            return false;
        }
        return col_name;
    };

    self.set_node_metadata = function(data)
    {
        try
        {
            setNodeMetadata(data.node, data.attr_name, data.value);
        }
        catch(e)
        {
            self.log_exception("SET_NODE_METADATA failed: " + e);
            return false;
        }
        return true;
    };

    self.configure_write_node = function(data)
    {
        // Confirmed live against Harmony 25.2 via node.getAttrList() dump:
        // DRAWING_NAME is a single attribute holding the full folder +
        // filename-prefix (e.g. ".../v003/$Scene."); Harmony appends
        // {frame, zero-padded to LEADING_ZEROS}.{extension for DRAWING_TYPE}
        // after it. There are no separate "Image Folder"/"Image Filename"
        // attributes. LEADING_ZEROS must be forced explicitly — the scene
        // default (3) does not match Toolkit's SEQ key padding (4), and
        // publish_render.py's FFmpeg/PublishedFile registration both
        // hardcode 4-digit frame numbers.
        var output_dir    = data.output_dir;
        var base_name     = data.base_name;
        var file_format   = data.file_format || "PNG";
        var leading_zeros = data.leading_zeros || 4;

        var write_nodes = node.getNodes(["WRITE"]);
        if (!write_nodes || write_nodes.length === 0)
        {
            self.log_exception("CONFIGURE_WRITE_NODE: no WRITE node found in the scene.");
            return false;
        }

        var write_node = write_nodes[0];
        if (write_nodes.length > 1)
        {
            self.log_warning(
                "CONFIGURE_WRITE_NODE: multiple WRITE nodes found, configuring "
                + "only the first: " + write_node
            );
        }

        scene.beginUndoRedoAccum("Configure Write Node");
        try
        {
            node.setTextAttr(write_node, "DRAWING_TYPE", 1, file_format);
            node.setTextAttr(write_node, "DRAWING_NAME", 1, output_dir + "/" + base_name + ".");
            node.setTextAttr(write_node, "LEADING_ZEROS", 1, String(leading_zeros));
        }
        catch(e)
        {
            scene.cancelUndoRedoAccum();
            self.log_exception("CONFIGURE_WRITE_NODE failed: " + e);
            return false;
        }
        scene.endUndoRedoAccum();

        // DIAGNOSTIC (temporary — remove once the render pipeline is
        // confirmed working live): setTextAttr() does not throw when
        // Harmony rejects a value it doesn't like (e.g. an invalid
        // DRAWING_TYPE silently falls back to TGA) — read the attributes
        // straight back so the log shows what Harmony actually stored,
        // not just what we tried to set.
        self.log_warning("DIAGNOSTIC CONFIGURE_WRITE_NODE readback: DRAWING_TYPE="
            + node.getTextAttr(write_node, 1, "DRAWING_TYPE")
            + " DRAWING_NAME=" + node.getTextAttr(write_node, 1, "DRAWING_NAME")
            + " LEADING_ZEROS=" + node.getTextAttr(write_node, 1, "LEADING_ZEROS"));

        return write_node;
    };

    // Shared by render_scene() (Publish2's fire-and-forget path) and
    // render_current_version() (the standalone artist-triggered command) —
    // both need the same "kick off render.renderSceneAll(), then wait for
    // the real render.renderFinished signal instead of trusting either
    // renderSceneAll()'s own return or the non-existent
    // renderSceneAllWithCallback()" logic. See render_scene()'s own history
    // (Session 13, DEVELOPMENT_NOTES.txt) for why this exists.
    // on_complete(rendered_frames, elapsed_ms) fires once, after a genuine
    // render.renderFinished. on_error(message) fires once instead if
    // render.renderSceneAll() throws synchronously. Never both.
    function _run_render_and_detect_completion(on_complete, on_error) {
        var rendered_frames = 0;
        var finished = false;
        var render_start_ms = Date.now();

        var on_frame_ready = function(frame, frameCel) {
            rendered_frames += 1;
        };

        var on_render_finished = function() {
            if (finished) {
                return;
            }
            finished = true;
            render.frameReady.disconnect(on_frame_ready);
            render.renderFinished.disconnect(on_render_finished);
            on_complete(rendered_frames, Date.now() - render_start_ms);
        };

        try {
            // Every documented usage of renderSceneAll() sets a render
            // display target first (e.g. Toon Boom's own scripting example:
            // render.setRenderDisplay("Top/Display")) — this was missing
            // here, and is the leading suspect for a full hang observed
            // live (Session 14): renderSceneAll() called, then dead
            // silence forever — no error, no frameReady, no renderFinished,
            // no frames on disk after 2.5+ minutes. Without a render
            // target, there may be nothing for the render to composite
            // through at all. Find the scene's actual Display node
            // dynamically instead of hardcoding Toon Boom's example name,
            // which may not match this scene's — same approach already
            // used for the Write node.
            var display_nodes = node.getNodes(["DISPLAY"]);
            if (display_nodes && display_nodes.length > 0) {
                if (display_nodes.length > 1) {
                    self.log_warning(
                        "DIAGNOSTIC multiple DISPLAY nodes found, using "
                        + "only the first: " + display_nodes[0]
                    );
                }
                self.log_warning("DIAGNOSTIC render.setRenderDisplay(" + display_nodes[0] + ")");
                render.setRenderDisplay(display_nodes[0]);
            } else {
                self.log_warning(
                    "DIAGNOSTIC no DISPLAY node found in scene — skipping "
                    + "setRenderDisplay; render may have no target."
                );
            }

            render.frameReady.connect(on_frame_ready);
            render.renderFinished.connect(on_render_finished);

            render.renderSceneAll();
        } catch (e) {
            if (!finished) {
                finished = true;
                try {
                    render.frameReady.disconnect(on_frame_ready);
                    render.renderFinished.disconnect(on_render_finished);
                } catch (disconnect_err) {
                    // ignore — connect() may never have run
                }
                on_error(e.toString());
            }
        }
    }

    self.show_harmony_message = function(data) {
        // Lightweight way for Python to surface an error to the artist
        // without going through engine.py's show_message()/show_error()
        // (those use QMessageBox.exec_(), a nested modal loop — this
        // engine runs as a detached background process that Windows won't
        // grant foreground focus to, so exec_() can never receive the
        // click needed to dismiss it and hangs the process forever; see
        // MenuGenerator.show()'s popup()-not-exec_() fix for the same
        // issue). MessageBox here runs in Harmony's own focused process,
        // so it has no such risk.
        MessageBox.warning(data.message || "");
        return true;
    };

    self.render_current_version = function(data) {
        // Standalone, artist-triggered render — completely separate from
        // Publish2. No status file, no Python-side polling: Python resolves
        // the Toolkit output path/format and fires this once
        // (fire-and-forget, same as RENDER_SCENE), then this function
        // reports success/failure directly to the artist via a native
        // Harmony dialog once the real render.renderFinished signal fires.
        // Exists because in-publish auto-render's completion detection has
        // proven unreliable across Harmony versions (Sessions 9 and 13) —
        // this gives artists a way to render and SEE it finish before ever
        // touching Publish, so Publish's own job can shrink to "does a
        // rendered sequence already exist for this version" (see
        // publish_render.py's "Auto-Render if Missing" setting).
        var output_dir    = data.output_dir;
        var base_name     = data.base_name;
        var file_format    = data.file_format || "PNG";
        var leading_zeros  = data.leading_zeros || 4;

        self.log_warning("DIAGNOSTIC RENDER_CURRENT_VERSION received: output_dir="
            + output_dir + " base_name=" + base_name);

        singleShotTimer(0, function() {
            try {
                var write_node = self.configure_write_node({
                    output_dir: output_dir,
                    base_name: base_name,
                    file_format: file_format,
                    leading_zeros: leading_zeros
                });
                if (!write_node) {
                    MessageBox.warning(
                        "Render failed: could not configure the Write node — "
                        + "see Harmony's Message Log for details."
                    );
                    return;
                }

                self.log_warning("DIAGNOSTIC RENDER_CURRENT_VERSION calling "
                    + "render.renderSceneAll() (async — waiting for "
                    + "render.renderFinished signal)...");

                _run_render_and_detect_completion(
                    function(rendered_frames, elapsed_ms) {
                        self.log_warning("DIAGNOSTIC RENDER_CURRENT_VERSION "
                            + "render.renderFinished fired after " + elapsed_ms
                            + " ms; frameReady fired " + rendered_frames + " time(s).");
                        MessageBox.information(
                            "Render complete: " + rendered_frames
                            + " frame(s) rendered to:\n" + output_dir
                        );
                    },
                    function(error_msg) {
                        self.log_exception("RENDER_CURRENT_VERSION failed: " + error_msg);
                        MessageBox.warning("Render failed: " + error_msg);
                    }
                );
            } catch (e) {
                self.log_exception("RENDER_CURRENT_VERSION failed: " + e);
                MessageBox.warning("Render failed: " + e.toString());
            }
        });

        return true;  // Immediate acknowledgement — render happens asynchronously
    };

    self.render_scene = function(data) {
        var start_frame  = data.start_frame;
        var stop_frame   = data.stop_frame;
        var status_path  = data.status_path;  // path Python will poll for completion
        var expected_frame_count = stop_frame - start_frame + 1;
        var status_written = false;  // guard against writing the status file twice

        // DIAGNOSTIC (temporary — remove once the render pipeline is
        // confirmed working live): WARNING level so it's guaranteed to hit
        // the log regardless of debug settings, same approach that found
        // the readyRead/deadlock bugs in Session 2.
        self.log_warning("DIAGNOSTIC RENDER_SCENE received: start=" + start_frame
            + " stop=" + stop_frame + " status_path=" + status_path);

        function write_status(success, rendered_frames, error_msg) {
            if (status_written) {
                return;
            }
            status_written = true;

            self.log_warning("DIAGNOSTIC RENDER_SCENE writing status file: success=" + success
                + " rendered_frames=" + rendered_frames + " error=" + error_msg);

            var status = {
                "success": success,
                "rendered_frames": rendered_frames,
                "error": error_msg
            };

            try {
                var qfile = new QFile(status_path);
                if (qfile.open(QIODevice.WriteOnly | QIODevice.Text)) {
                    var stream = new QTextStream(qfile);
                    stream.writeString(JSON.stringify(status));
                    qfile.close();
                    self.log_warning("DIAGNOSTIC RENDER_SCENE status file written OK.");
                } else {
                    self.log_exception("RENDER_SCENE: could not open status file for writing: " + status_path);
                }
            } catch(write_err) {
                self.log_exception("RENDER_SCENE: could not write status file: " + write_err);
            }
        }

        // Defer the render so the socket can process the incoming message first
        singleShotTimer(0, function() {
            self.log_warning("DIAGNOSTIC RENDER_SCENE deferred callback fired.");

            try {
                // Previously start_frame/stop_frame were only used to
                // estimate rendered_frames below — never actually applied
                // to the scene, so renderSceneAll()/renderSceneAllWithCallback()
                // always rendered whatever the scene's own Start/Stop frame
                // settings happened to be, regardless of what Toolkit asked
                // for. Now explicitly set, same call SET_START_FRAME/
                // SET_STOP_FRAME already use.
                scene.beginUndoRedoAccum("Render Scene - Set Frame Range");
                scene.setStartFrame(start_frame);
                scene.setStopFrame(stop_frame);
                scene.endUndoRedoAccum();

                self.log_warning("DIAGNOSTIC RENDER_SCENE frame range set, scene now reports: "
                    + scene.getStartFrame() + "-" + scene.getStopFrame());

                // Confirmed broken live on Harmony 25.2: render.setRenderMode
                // is not a function in this JS engine at all (unlike the
                // singleShotTimer case, there's no evidence for a property-
                // style alternative, and this is a quality/speed knob, not
                // something the render actually depends on) — skip
                // gracefully rather than guess another name blind.
                if (typeof render.setRenderMode === "function" && typeof render.DRAFT !== "undefined") {
                    render.setRenderMode(render.DRAFT);
                } else {
                    self.log_warning("DIAGNOSTIC render.setRenderMode/DRAFT not available in this Harmony version — skipping, rendering at default quality.");
                }

                // render.renderSceneAllWithCallback() DOES NOT EXIST — confirmed
                // against Toon Boom's own Harmony 25.2 scripting reference
                // (classrender.html). The correct, documented way to detect
                // real completion is the render.renderFinished Qt-style
                // signal (render.frameReady fires per frame before it) — see
                // _run_render_and_detect_completion() above, shared with
                // render_current_version().
                self.log_warning("DIAGNOSTIC calling render.renderSceneAll() (async — waiting for "
                    + "render.renderFinished signal)...");

                _run_render_and_detect_completion(
                    function(rendered_frames, elapsed_ms) {
                        self.log_warning("DIAGNOSTIC render.renderFinished fired after "
                            + elapsed_ms + " ms; frameReady fired " + rendered_frames
                            + " time(s) (expected " + expected_frame_count + ").");
                        write_status(true, rendered_frames, "");
                    },
                    function(error_msg) {
                        self.log_exception("RENDER_SCENE failed: " + error_msg);
                        write_status(false, 0, error_msg);
                    }
                );
            } catch(e) {
                self.log_exception("RENDER_SCENE failed: " + e);
                write_status(false, 0, e.toString());
            }
        });

        return true;  // Immediate acknowledgement — render happens asynchronously
    };

    self.export_camera_data = function(data)
    {
        // NOT LIVE-VERIFIED. Nothing in this codebase has touched a
        // Camera/Peg node before this — the attribute names below
        // (POSITION.X/Y/Z, SCALE.X/Y, ANGLE) are standard Toon Boom
        // Harmony scripting conventions but are UNCONFIRMED against this
        // studio's actual Harmony version. A raw node.getAttrList() dump
        // is logged below (same technique that found the real Write node
        // attributes in an earlier session) specifically so a wrong guess
        // here is easy to correct from the Message Log rather than
        // silently producing bogus data.
        var camera_node  = data.camera_node;
        var start_frame  = data.start_frame;
        var stop_frame   = data.stop_frame;

        try
        {
            self.log_warning("DIAGNOSTIC EXPORT_CAMERA_DATA attributes on "
                + camera_node + ": " + JSON.stringify(node.getAttrList(camera_node, 1)));

            // node.parentNode() is Harmony's animation-parenting call —
            // the node a given node is pegged to, which is what actually
            // drives its combined on-screen transform if the camera
            // itself is left static and a Peg above it carries the move.
            // NOT LIVE-VERIFIED: unconfirmed this returns "" / "Top" at
            // the scene root rather than some other sentinel.
            var parent_peg = node.parentNode(camera_node);
            if (parent_peg === "Top" || parent_peg === "")
            {
                parent_peg = null;
            }
            else
            {
                self.log_warning("DIAGNOSTIC EXPORT_CAMERA_DATA attributes on "
                    + "driving peg " + parent_peg + ": "
                    + JSON.stringify(node.getAttrList(parent_peg, 1)));
            }

            function readTransform(nodeName, atFrame)
            {
                return {
                    "x":     node.getAttr(nodeName, atFrame, "POSITION.X").doubleValue(),
                    "y":     node.getAttr(nodeName, atFrame, "POSITION.Y").doubleValue(),
                    "z":     node.getAttr(nodeName, atFrame, "POSITION.Z").doubleValue(),
                    "scale_x": node.getAttr(nodeName, atFrame, "SCALE.X").doubleValue(),
                    "scale_y": node.getAttr(nodeName, atFrame, "SCALE.Y").doubleValue(),
                    "angle":   node.getAttr(nodeName, atFrame, "ANGLE").doubleValue()
                };
            }

            var frames = [];
            for (var f = start_frame; f <= stop_frame; f++)
            {
                var record = { "frame": f, "camera": readTransform(camera_node, f) };
                if (parent_peg !== null)
                {
                    record["peg"] = readTransform(parent_peg, f);
                }
                frames.push(record);
            }

            return {
                "success": true,
                "camera_node": camera_node,
                "parent_peg": parent_peg,
                "frames": frames
            };
        }
        catch(e)
        {
            self.log_exception("EXPORT_CAMERA_DATA failed: " + e);
            return { "success": false, "error": e.toString() };
        }
    };

    // ----
    self.ping = function(data)
    {
        return "PONG";
    };

    self.adquire_main_window = function()
    {
        var active_window = QApplication.activeWindow();
        self.set_main_window(active_window);
    };

    self.refresh_title = function()
    {
        if (self.window != null)
        {
            // FIX: `version_name` and `app_version` were implicit globals.
            var version_name;
            if (self.is_startup_project())
            {
                version_name = "ShotGrid Toolkit - Open a file from the ShotGrid menu.";
            }
            else
            {
                version_name = scene.currentVersionName();
            }

            if (version_name === "")
                version_name = scene.currentScene();

            var app_version = about.productName();
            var title = app_version + " Project: " + version_name;
            self.window.setWindowTitle(title);
        }
        else
        {
            MessageLog.trace("Refresh title: window not ready!");
        }
    };



    // ------------------------------------------------------------------------

    self.registerCallback = function(command, callback)
    {
        self.server.register_command(command, callback);
        self.log_debug("Registered callback: " + command);
    };

    self.register_callbacks = function()
    {
        self.registerCallback("LOG_INFO",      log_info);
        self.registerCallback("LOG_WARNING",   log_warning);
        self.registerCallback("LOG_DEBUG",     log_debug);
        self.registerCallback("LOG_ERROR",     log_error);
        self.registerCallback("LOG_EXCEPTION", log_exception);
        self.registerCallback("GET_VERSION",   self.get_version);
        self.registerCallback("ENGINE_READY",  self.engine_ready);
        self.registerCallback("ENGINE_RESTART", self.engine_restart);
        self.registerCallback("OPEN_PROJECT",              self.open_project);
        self.registerCallback("GET_CURRENT_PROJECT_FOLDER", self.current_project_folder);
        self.registerCallback("GET_CURRENT_PROJECT_PATH",  self.current_project_path);
        self.registerCallback("SAVE_PROJECT",              self.save_project);
        self.registerCallback("SAVE_NEW_VERSION",          self.save_new_version);
        self.registerCallback("SAVE_NEW_VERSION_ACTION",   self.save_new_version_action);
        self.registerCallback("NEEDS_SAVING",              self.needs_saving_project);
        self.registerCallback("CLOSE_PROJECT",             self.close_project);
        self.registerCallback("EXECUTE_STATEMENT",         self.execute_statement);
        self.registerCallback("EXTRACT_THUMBNAIL",         self.extract_thumbnail);
        self.registerCallback("TOGGLE_DEBUG_LOGGING",      self.toggle_debug_logging);
        self.registerCallback("IS_STARTUP_PROJECT",        self.is_startup_project);

        // Timeline
        self.registerCallback("GET_FRAME_RANGE",  self.get_frame_range);
        self.registerCallback("SET_FRAME_RANGE",  self.set_frame_range);

        self.registerCallback("GET_FRAME_COUNT",  self.get_frame_count);
        self.registerCallback("SET_FRAME_COUNT",  self.set_frame_count);

        self.registerCallback("GET_START_FRAME",  self.get_start_frame);
        self.registerCallback("SET_START_FRAME",  self.set_start_frame);

        self.registerCallback("GET_STOP_FRAME",   self.get_stop_frame);
        self.registerCallback("SET_STOP_FRAME",   self.set_stop_frame);

        // Actions
        self.registerCallback("IMPORT_DRAWING",   self.import_drawing);
        self.registerCallback("IMPORT_AUDIO",     self.import_audio);
        self.registerCallback("IMPORT_CLIP",      self.import_clip);
        self.registerCallback("IMPORT_TEMPLATE",  self.import_template);
        self.registerCallback("IMPORT_ELEMENT_FILES", self.import_element_files);
        self.registerCallback("IMPORT_PALETTE",       self.import_palette);

        // Metadata
        self.registerCallback("GET_NODE_METADATA",  self.get_node_metadata);
        self.registerCallback("GET_SCENE_METADATA", self.get_scene_metadata);

        // Scene inspection
        self.registerCallback("GET_NODES_OF_TYPE",           self.get_nodes_of_type);
        self.registerCallback("GET_COLUMNS_OF_TYPE",         self.get_columns_of_type);
        self.registerCallback("GET_SOUND_COLUMN_FILENAMES",  self.get_sound_column_filenames);

        // Breakdown update / relink
        self.registerCallback("RELINK_READ_NODE",    self.relink_read_node);
        self.registerCallback("RELINK_SOUND_COLUMN", self.relink_sound_column);
        self.registerCallback("SET_NODE_METADATA",   self.set_node_metadata);

        // Render
        self.registerCallback("CONFIGURE_WRITE_NODE", self.configure_write_node);
        self.registerCallback("RENDER_SCENE", self.render_scene);
        self.registerCallback("RENDER_CURRENT_VERSION", self.render_current_version);
        self.registerCallback("SHOW_HARMONY_MESSAGE", self.show_harmony_message);

        // Camera / scene data export
        self.registerCallback("EXPORT_CAMERA_DATA", self.export_camera_data);

        self.registerCallback("PING",  self.ping);
        self.registerCallback("CLOSE", self.stop);
        self.log_debug("Registered callbacks");
    };

    self.start = function()
    {
        if (self.server != null)
        {
            self.log_debug("Killed server");
            self.server.close();
            self.server = null;
        }

        self.log_debug("New server");
        var host = System.getenv("SGTK_HARMONY_ENGINE_HOST");
        var port = parseInt(System.getenv("SGTK_HARMONY_ENGINE_PORT"), 10);

        self.server = new Server(host, port);
        self.register_callbacks();
        self.server.start();

        MessageLog.trace("--");
    };

    self.stop = function()
    {
        if (self.server != null)
        {
            self.log_debug("Killed server");
            self.server.close();
            self.server = null;
        }
    };

    self.show_menu = function()
    {
        var x = QCursor.pos().x();
        var y = QCursor.pos().y();
        self.server.send_command("SHOW_MENU", { "clickedPosition": { "x": x, "y": y } });
    };

    self.on_about_to_quit = function()
    {
        // Best-effort notification to the Python engine before we terminate it.
        self.server.send_command("QUIT", {});

        // Reliable way to kill the engine process.
        var engine_pid = System.getenv("SGTK_HARMONY_ENGINE_PID");
        // FIX: `p` was an implicit global.
        var p = new Process2(parseInt(engine_pid, 10));
        p.terminate();
    };
}

function Shotgun()
{
    // Check if we are under a ShotGrid Desktop environment first.
    var engine_env  = System.getenv("SGTK_ENGINE");
    var context_env = System.getenv("SGTK_CONTEXT");
    // FIX: original code re-declared `var engine` below, shadowing this one.
    //      Renamed to engine_env / context_env to avoid the shadow.
    if (engine_env === "" || context_env === "")
    {
        var message = "Harmony has not been run from within the ShotGrid Desktop Launcher.\n\nNot under a ShotGrid Desktop environment.\n";
        MessageLog.trace(message);
        return false;
    }

    MessageLog.trace("Shotgun engine...");
    var engine_port = System.getenv("SGTK_HARMONY_ENGINE_PORT");
    MessageLog.trace("Shotgun engine port: " + engine_port);

    var shotgun_app = QCoreApplication.instance();
    var active_window = QApplication.activeWindow();
    var engine = shotgun_app.shotgun_engine;

    if (engine == null)
    {
        engine = new Engine();
        engine.start();
        bootstrap();
        shotgun_app.shotgun_engine = engine;

        shotgun_app.aboutToQuit.connect(shotgun_app, engine.on_about_to_quit);
    }

    if (engine != null)
    {
        if (!engine.is_engine_ready)
        {
            engine.clear_busy();
            engine.show_busy(
                "Initializing ShotGrid Engine, please wait ...",
                "ShotGrid engine is being loaded. This dialog will close once the connection has been established."
            );
            System.processOneEvent();

            engine.on_engine_ready_callbacks.push(engine.clear_busy);
            engine.on_engine_ready_callbacks.push(engine.adquire_main_window);
            engine.on_engine_ready_callbacks.push(engine.refresh_title);
        }
    }
    MessageLog.trace("Shotgun engine...Done");
    return true;
}

function ShotgunMenu()
{
    var initialized = Shotgun();

    if (!initialized)
    {
        var message = "Harmony has not been run from within the ShotGrid Desktop Launcher.\n\nNot under a ShotGrid Desktop environment.\n";
        MessageBox.information(message, 0, 0, 0, "ShotGrid Harmony Engine");
        return;
    }

    var shotgun_app = QCoreApplication.instance();
    var engine = shotgun_app.shotgun_engine;

    if (engine != null)
    {
        var active_window = QApplication.activeWindow();
        engine.set_main_window(active_window);

        if (engine.is_engine_ready)
        {
            engine.show_menu();
            engine.refresh_title();
        }
    }
}

function bootstrap()
{
    var SGTK_HARMONY_ENGINE_RESOURCES_PATH = System.getenv("SGTK_HARMONY_ENGINE_RESOURCES_PATH");

    var bootstrap_app = QCoreApplication.instance();
    var engine_is_up  = typeof(bootstrap_app.__SGTK_STARTUP_INIT__) !== "undefined";
    if (engine_is_up)
        engine_is_up = engine_is_up && typeof(bootstrap_app.shotgun) !== "undefined";

    if (engine_is_up)
        engine_is_up = engine_is_up && typeof(bootstrap_app.shotgun.engine_process) !== "undefined";

    if (engine_is_up)
        engine_is_up = engine_is_up && bootstrap_app.shotgun.engine_process.isAlive() === true;

    MessageLog.trace("engine_is_up:" + engine_is_up);
    if (engine_is_up)
        MessageLog.trace("app.shotgun.engine_process:" + bootstrap_app.shotgun.engine_process);

    var do_startup = !engine_is_up;
    MessageLog.trace("do_startup:" + do_startup);

    if (do_startup)
    {
        if (typeof(bootstrap_app.shotgun) === "undefined")
            bootstrap_app.shotgun = {};

        MessageLog.trace('-------------------------');
        MessageLog.trace('Shotgun startup started');
        MessageLog.trace('-------------------------');

        var python_exec  = System.getenv('SGTK_HARMONY_ENGINE_PYTHON');
        var boostrap_py  = System.getenv('SGTK_HARMONY_ENGINE_STARTUP');
        var engine_name  = 'tk-harmony';
        var engine_port  = System.getenv('SGTK_HARMONY_ENGINE_PORT');
        var app_id       = 'basic.*';
        // FIX: original had 'basic.*`' — a stray backtick that would break
        //      any shell or Python argument parsing on the receiving end.

        MessageLog.trace('Initializing Shotgun Harmony engine ...');
        MessageLog.trace('   engine name: '      + engine_name);
        MessageLog.trace('   engine port: '      + engine_port);
        MessageLog.trace('   engine app id: '    + app_id);
        MessageLog.trace('   engine python: '    + python_exec);
        MessageLog.trace('   engine bootstrap: ' + boostrap_py);

        var engine_process = new Process2(python_exec, boostrap_py, engine_port, engine_name, app_id);
        MessageLog.trace('About to execute: ');
        MessageLog.trace(engine_process.commandLine());

        var error = engine_process.launchAndDetach();
        MessageLog.trace('error ' + error);

        bootstrap_app.shotgun.window      = null;
        bootstrap_app.shotgun.engine_name = engine_name;

        bootstrap_app.shotgun.engine_process = engine_process;
        bootstrap_app.shotgun.engine_pid     = engine_process.pid();

        bootstrap_app.shotgun.engine_host = "localhost";
        bootstrap_app.shotgun.engine_port = parseInt(engine_port, 10);

        bootstrap_app.shotgun.debug = true;

        MessageLog.trace("Registered onAboutToQuit callback: " + bootstrap_app.aboutToQuit);
        bootstrap_app.aboutToQuit.connect(bootstrap_app, bootstrap_app.shotgun.engine_process.terminate);

        bootstrap_app.__SGTK_STARTUP_INIT__ = true;

        MessageLog.trace('Shotgun startup finished.');
        MessageLog.trace('-------------------------');
    }
    else
    {
        MessageLog.trace(bootstrap_app.__SGTK_STARTUP_INIT__);
    }
}

function init()
{
    MessageLog.trace("Shotgun Initialization...");
    Shotgun();
    MessageLog.trace("Shotgun Initialization... Done");
}


exports.configure = configure;
exports.init      = init;
