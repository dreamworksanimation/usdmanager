#
# Copyright 2018 DreamWorks Animation L.L.C.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""
Generic utility functions
"""
import importlib
import logging
import os
import re
import sys
import math
import subprocess
import tempfile
from contextlib import contextmanager
from glob import glob
from pkg_resources import resource_filename

from Qt import QtCore
from Qt.QtGui import QIcon
from Qt.QtWidgets import QApplication

from .constants import USD_EXTS, USD_AMBIGUOUS_EXTS, USD_ASCII_EXTS, USD_CRATE_EXTS


# Set up logging.
logger = logging.getLogger(__name__)
logging.basicConfig()

try:
    from pxr import Ar
    resolver = Ar.GetResolver()
except ImportError:
    logger.warn("Unable to create AssetResolver - Asset links may not work correctly")
    resolver = None

# This can be updated based on the config.json.
ICON_ALIASES = {
    "crystal_project": {
        "accessories-text-editor": "edit",
        "application-exit": "exit",
        "applications-internet": "Globe",
        "comment-add": "comment",
        "comment-remove": "removecomment",
        "dialog-information": "info",
        "document-open": "fileopen",
        "document-open-recent": "history",
        "document-print": "printer",
        "document-save": "filesave",
        "document-save-as": "filesaveas",
        "edit-copy": "editcopy",
        "edit-cut": "editcut",
        "edit-find": "find",
        "edit-find-next": ":/images/images/findNext.png",
        "edit-find-previous": ":/images/images/findPrev.png",
        "edit-paste": "editpaste",
        "edit-redo": "redo",
        "edit-select-all": "ark_selectall",
        "edit-undo": "undo",
        "file-diff": "kompare",
        "folder-home": "folder_home",
        "folder-up": "up",
        "format-indent-less": "format_decreaseindent",
        "format-indent-more": "format_increaseindent",
        "go-jump": "goto",
        "go-next": "next",
        "go-previous": "previous",
        "help-about": "14_star",
        "help-browser": "help",
        "media-playback-start": "1rightarrow",
        "preferences-system": "configure",
        "process-stop": "stop",
        "tab-new": "tab_new",
        "tab-remove": "tab_remove",
        "utilities-terminal": "terminal",
        "view-fullscreen": "window_fullscreen",
        "view-refresh": "reload",
        "window-close": "fileclose",
        "window-new": "new_window",
        "zoom-in": "viewmag+",
        "zoom-original": "viewmag1",
        "zoom-out": "viewmag-",
    }
}


def expandPath(path, parentPath=None, sdf_format_args=None, extractedDir=None):
    """ Expand and normalize a path that may have variables in it.
    Do not use this for URLs with query strings.
    
    :Parameters:
        path : `str`
            File path
        parentPath : `str` | None
            Parent file path this file is defined in relation to.
            Helps with asset resolution.
        sdf_format_args : `dict` | None
            Dictionary of key/value `str` pairs from a path's :SDF_FORMAT_ARGS:
        extractedDir: `str` | None
            If the file is part of an extracted usdz archive, this is the path
            to the extracted dir of the archive.
    :Returns:
        Normalized path with variables expanded.
    :Rtype:
        `str`
    """
    # Expand the ~ part of any path first. The asset resolver doesn't understand it.
    path = os.path.expanduser(os.path.normpath(path))
    
    if resolver is not None:
        try:
            # ConfigureResolverForAsset no longer exists under Ar 2.0;
            # this check is here for backwards compatibility with Ar 1.0
            if hasattr(resolver, "ConfigureResolverForAsset"):
                resolver.ConfigureResolverForAsset(path)
            context = resolver.CreateDefaultContextForAsset(path)
            with Ar.ResolverContextBinder(context):
                if parentPath is None:
                    anchoredPath = path
                elif hasattr(resolver, "CreateIdentifier"):
                    anchoredPath = resolver.CreateIdentifier(path)
                else:
                    anchoredPath = resolver.AnchorRelativePath(parentPath, path)
                resolved = resolver.Resolve(anchoredPath)
                
                # https://graphics.pixar.com/usd/docs/Usdz-File-Format-Specification.html#UsdzFileFormatSpecification-USDConstraints-AssetResolution
                # If resolving relative to the layer fails in a usdz archive,
                # try to resolve based on the archive's default layer path.
                if extractedDir and not os.path.exists(resolved):
                    default_layer = os.path.join(extractedDir, 'defaultLayer.usd')
                    if hasattr(resolver, "CreateIdentifier"):
                        anchoredPath = resolver.CreateIdentifier(default_layer, path)
                    else:
                        anchoredPath = resolver.AnchorRelativePath(default_layer, path)
                    resolved = resolver.Resolve(anchoredPath)
        except Exception as e:
            logger.warn("Failed to resolve Asset path %s with parent %s: %s", path, parentPath, e)
        else:
            if resolved:
                return str(resolved)
    
    # Return this best-attempt if all else fails.
    return QtCore.QDir.cleanPath(os.path.expandvars(path))


def expandUrl(path, parentPath=None):
    """ Expand and normalize a URL that may have variables in it and a query string after it.

    :Parameters:
        path : `str`
            File path
        parentPath : `str` | None
            Parent file path this file is defined in relation to.
            Helps with asset resolution.
    :Returns:
        URL with normalized path with variables expanded.
    :Rtype:
        `QtCore.QUrl`
    """
    sdf_format_args = {}
    path = stripFileScheme(path)
    if "?" in path:
        sdf_format_args.update(sdfQuery(QtCore.QUrl.fromLocalFile(path)))
        path, query = path.split("?", 1)
    else:
        query = None
    url = QtCore.QUrl.fromLocalFile(os.path.abspath(str(expandPath(path, parentPath, sdf_format_args))))
    if query:
        url.setQuery(query)
    return url


def strToUrl(path):
    """ Properly set the query parameter of a URL, which doesn't seem to set QUrl.hasQuery properly unless using
    .setQuery.
    
    Use this when a path might have a query string after it or start with file://. In all other cases.
    QUrl.fromLocalFile should work fine.
    
    :Parameters:
        path : `str`
            URL string
    :Returns:
        URL object
    :Rtype:
        `QtCore.QUrl`
    """
    if "?" in path:
        path, query = path.split("?", 1)
    else:
        query = None
    
    if path.startswith("file://"):
        url = QtCore.QUrl(path)
    else:
        url = QtCore.QUrl.fromLocalFile(path)
    
    if query:
        url.setQuery(query)
    return url


def stripFileScheme(path):
    """ Strip any file URI scheme from the beginning of a path.
    
    Parameters:
        path : `str`
            File path or file URL
    :Returns:
        File path
    :Rtype:
        `str`
    """
    return path[7:] if path.startswith("file://") else path


def findModules(subdir):
    """ Find and import all modules in a subdirectory of this project.
    Ignores any files starting with an underscore or tilde.
    
    :Parameters:
        subdir : `str`
            Subdirectory
    :Returns:
        Imported modules
    :Rtype:
        `list`
    """
    modules = []
    pluginPath = resource_filename(__name__, subdir)
    logger.info("Searching for *.py plugins in %s", pluginPath)
    for f in glob(os.path.join(pluginPath, "*.py")):
        moduleName = os.path.splitext(os.path.basename(f))[0]
        if moduleName.startswith('_') or moduleName.startswith('~'):
            continue
        module = importlib.import_module("..{}.{}".format(subdir, moduleName), __name__)
        modules.append(module)
    return modules


def generateTemporaryUsdFile(usdFileName, tmpDir=None):
    """ Generate a temporary ASCII USD file that the user can edit.
    
    :Parameters:
        usdFileName : `str`
            Binary USD file path
        tmpDir : `str` | None
            Temp directory to create the new file within
    :Returns:
        Temporary file name
    :Rtype:
        `str`
    :Raises OSError:
        If usdcat fails
    """
    fd, tmpFileName = mkstemp(suffix="." + USD_AMBIGUOUS_EXTS[0], dir=tmpDir)
    os.close(fd)
    usdcat(QtCore.QDir.toNativeSeparators(usdFileName), tmpFileName, format="usda")
    return tmpFileName


def mkdtemp(dir, **kwargs):
    """ Make a temp dir, safely ensuring the parent temp dir still exists.

    :Parameters:
        dir : `str`
            Parent directory
    :Returns:
        New temp directory
    :Rtype:
        `str`
    """
    try:
        destDir = tempfile.mkdtemp(dir=dir, **kwargs)
    except OSError:
        if dir is not None and not os.path.exists(dir):
            # Someone may have manually removed the temp dir while the app was open.
            os.mkdir(dir)
            return mkdtemp(dir, **kwargs)
        else:
            raise
    return destDir


def mkstemp(dir, **kwargs):
    """ Make a temp file, safely ensuring the parent temp dir still exists.

    :Parameters:
        dir : `str`
            Parent directory
    :Returns:
        New temp file
    :Rtype:
        `str`
    """
    try:
        fd, tmpFileName = tempfile.mkstemp(dir=dir, **kwargs)
    except OSError:
        if dir is not None and not os.path.exists(dir):
            # Someone may have manually removed the temp dir while the app was open.
            os.mkdir(dir)
            return mkstemp(dir, **kwargs)
        else:
            raise
    return fd, tmpFileName


def icon(name, fallback=None):
    """ Get an icon, using theme-based configs to look up icon name aliases.

    :Parameters:
        name : `str`
            Icon name or resource path
        fallback : `QIcon` | None
            Fallback icon if an icon for name (or it's alias) is not found.
    :Returns:
        Icon
    :Rtype:
        `QIcon`
    """
    try:
        alias = ICON_ALIASES[QIcon.themeName()][name]
    except KeyError:
        return QIcon.fromTheme(name) if fallback is None else QIcon.fromTheme(name, fallback)
    else:
        # Assume we passed in a resource path instead of a theme icon.
        if alias.startswith(":"):
            return QIcon(alias)
        if fallback is None:
            return QIcon.fromTheme(alias, QIcon.fromTheme(name))
        return QIcon.fromTheme(alias, QIcon.fromTheme(name, fallback))


def usdcat(inputFile, outputFile, format=None):
    """ Generate a temporary ASCII USD file that the user can edit.
    
    :Parameters:
        inputFile : `str`
            Input file name
        outputFile : `str`
            Output file name
        format : `str` | None
            Output USD format (e.g. usda or usdc)
            Only used if outputFile's extension is .usd
    :Raises OSError:
        If usdcat fails
    :Raises ValueError:
        If invalid format given compared to output file extension.
    """
    cmd = ['usdcat', inputFile, '-o', outputFile]
    if format and outputFile.endswith(".usd"):
        # For usdcat, use of --usdFormat requires output file end with '.usd' extension.
        cmd += ['--usdFormat', format]
    logger.debug(subprocess.list2cmdline(cmd))
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise OSError("Failed to convert file {}: {}".format(inputFile, e.output))


def usdzip(inputs, dest):
    """ Zip or unzip a usdz format file.
    
    :Parameters:
        inputs : `str` | `list`
            Input file name(s). String or list of strings
        dest : `str`
            Output directory (for unzip) or file name
    :Raises OSError:
        If usdzip fails
    """
    cmd = ["usdzip"]
    if type(inputs) is list:
        cmd += inputs
    else:
        cmd.append(inputs)
    cmd.append(dest)
    logger.debug(subprocess.list2cmdline(cmd))
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise OSError("Failed to zip: {}".format(e.output))


def unzip(path, tmpDir=None):
    """ Unzip a usdz format file to a temporary directory.
    
    :Parameters:
        path : `str`
            Input .usdz file
        tmpDir : `str` | None
            Temp directory to create the new unzipped directory within
    :Returns:
        Absolute path to destination directory for unzipped usdz
    :Rtype:
        `str`
    :Raises zipfile.BadZipfile:
        For bad ZIP files
    :Raises zipfile.LargeZipFile:
        When a ZIP file would require ZIP64 functionality but that has not been enabled
    """
    from zipfile import ZipFile
    
    destDir = mkdtemp(prefix="usdmanager_usdz_", dir=tmpDir)
    logger.debug("Extracting %s to %s", path, destDir)
    with ZipFile(QtCore.QDir.toNativeSeparators(path), 'r') as zipRef:
        zipRef.extractall(destDir)
    return destDir


def getUsdzLayer(usdzDir, layer=None, usdz=None):
    """ Get a layer from an unzipped usdz archive.
    
    :Parameters:
        usdzDir : `str`
            Unzipped directory path
        layer : `str`
            Default layer within file (e.g. the portion within the square brackets here:
            @foo.usdz[path/to/file/within/package.usd]@)
        usdz : `str`
            Original usdz file path
    :Returns:
        Layer file path
    :Rtype:
        `str`
    :Raises ValueError:
        If default layer not found
    """
    if layer is not None:
        destFile = os.path.join(usdzDir, layer)
        if os.path.exists(destFile):
            return destFile
        else:
            raise ValueError("Layer {} not found in usdz archive {}".format(layer, usdzDir))
    
    if usdz is not None:
        try:
            from pxr import Usd
        except ImportError:
            logger.debug("Unable to import pxr.Usd to find usdz default layer.")
        else:
            zipFile = Usd.ZipFile.Open(usdz)
            if zipFile:
                for fileName in zipFile.GetFileNames():
                    return os.path.join(usdzDir, fileName)
            raise ValueError("Default layer not found in usdz archive!")
    
    # Fallback to checking the files on disk instead of using USD.
    destFile = os.path.join(usdzDir, "defaultLayer.usd")
    if os.path.exists(destFile):
        return destFile
    files = []
    for ext in USD_AMBIGUOUS_EXTS + USD_ASCII_EXTS + USD_CRATE_EXTS:
        files += glob(os.path.join(usdzDir, "*." + ext))
    if files:
        if len(files) == 1:
            return files[0]
        raise ValueError("Ambiguous default layer in usdz archive!")
    raise ValueError("No default layer found in usdz archive!")


def humanReadableSize(size):
    """ Get a human-readable file size string from bytes.

    :Parameters:
        size : `int`
            File size, in bytes
    :Returns:
        Human-readable file size
    :Rtype:
        `str`
    """
    for unit in ("bytes", "kB", "MB", "GB"):
        if abs(size) < 1024:
            return "{:.1f} {}".format(size, unit)
        size /= 1024.0
    return "{:.1f} TB".format(size)


def isUsdCrate(path):
    """ Check if a file is a USD crate file by reading in the first line of
    the file. Doesn't check the file extension.
    
    :Parameters:
        path : `str`
            USD file path
    :Returns:
        If the USD file is a crate (binary) file.
    :Rtype:
        `bool`
    """
    with open(path, "rb") as f:
        return f.read(8).decode("utf-8") == "PXR-USDC"


def isPy3():
    """ Check if the application is running Python 3.
    
    :Returns:
        If the application is running Python 3.
    :Rtype:
        `bool`
    """
    return sys.version_info[0] == 3


def round(value, decimals=0):
    """ Python 2/3 compatible rounding function. Lifted from
    http://python3porting.com/differences.html#rounding-behavior

    :Parameters:
        value : `float`
            The value to perform the rounding operation on.
        decimals : `int`
            The number of decimal places to retain.
    :Returns:
        The rounded value.
    :Rtype:
        `float`
    """
    p = 10 ** decimals
    if value > 0:
        return float(math.floor((value * p) + 0.5)) / p
    else:
        return float(math.ceil((value * p) - 0.5)) / p


def isUsdExt(ext):
    """ Check if the given extension is an expected USD file extension.

    :Parameters:
        ext : `str`
    :Returns:
        If the file extension is a valid USD extension
    :Rtype:
        `bool`
    """
    return ext.lstrip('.') in USD_EXTS


def isUsdFile(path):
    """ Check if the given file is a USD file based on the file's extension.

    :Parameters:
        path : `str`
    :Returns:
        If the file extension is a valid USD extension
    :Rtype:
        `bool`
    """
    return isUsdExt(os.path.splitext(path)[1])


def loadUiWidget(path, parent=None, source_path=None):
    """ Load a Qt Designer .ui file and return an instance of the user interface
    
    :Parameters:
        path : `str`
            Absolute path to .ui file
        parent : `QtWidgets.QWidget`
            The widget into which UI widgets are loaded
        source_path : `str`
            File loading the UI file, if the UI file is relative and needs to be found in the same directory
    :Returns:
        The widget instance
    :Rtype:
        `QtWidgets.QWidget`
    """
    from Qt import QtCompat
    
    if not os.path.exists(path) and not os.path.isabs(path):
        # Assume the .ui file lives in this directory.
        if source_path is None:
            path = resource_filename(__name__, path)
        else:
            path = os.path.join(os.path.dirname(os.path.realpath(source_path)), path)
    ui = QtCompat.loadUi(path, parent)
    if parent:
        #ui.setParent(parent)
        for member in dir(ui):
            if not member.startswith('__') and member != 'staticMetaObject':
                setattr(parent, member, getattr(ui, member))
    return ui


@contextmanager
def overrideCursor(cursor=QtCore.Qt.WaitCursor):
    """ For use with the "with" keyword, so the override cursor is always
    restored via a try/finally block, even if the commands in-between fail.
    
    Example:
        with overrideCursor():
            # do something that may raise an error
    """    
    QApplication.setOverrideCursor(cursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


def queryItemValue(url, key, default=None):
    """ Qt.py compatibility, since Qt5 introduced QUrlQuery, but Qt.py doesn't support that.
    PyQt4 just uses QUrl for everything, including hasQueryItem and queryItemValue.
    
    :Parameters:
        url : `QtCore.QUrl`
            Full URL with query string
        key : `str`
            Query key
        default
            Value if key not found
    :Returns:
        Query value, or None
    :Rtype:
        `str` | None
    :Raises ValueError:
        If an invalid query string is given
    """
    if url.hasQuery():
        query = url.toString().split("?", 1)[1]
        for item in query.split(url.queryPairDelimiter()):
            if item:
                try:
                    k, v = item.split(url.queryValueDelimiter())
                except ValueError:
                    logger.error("Invalid query string: %s", query)
                else:
                    if k == key:
                        return v
    return default


def queryItemBoolValue(url, key, default=False):
    """ Get a boolean value from a query string.

    :Parameters:
        url : `QtCore.QUrl`
            Full URL with query string
        key : `str`
            Query key
        default
            Value if key not found
    :Returns:
        Query value
    :Rtype:
        `bool`
    """
    value = queryItemValue(url, key, default)
    return value and value != "0"


def sdfQuery(link):
    """ Process a link's query items to see if it has our special sdf entry.
    This is used to pass along :SDF_FORMAT_ARGS: key/value pairs to downstream files.
    
    :Parameters:
        link : `QtCore.QUrl`
            Link
    :Returns:
        Sdf format args
    :Rtype:
        `dict`
    """
    sdf_format_args = {}
    try:
        for kv in queryItemValue(link, "sdf", "").split("+"):  # TODO: Figure out something that works better as key=value& separators.
            k, v = kv.split(":", 1)
            sdf_format_args[k] = v
    except ValueError:
        # No sdf query parameter.
        pass
    except Exception:
        logger.exception("Invalid sdf query parameter")
    return sdf_format_args


def urlFragmentToQuery(url):
    """ Convert a URL with a fragment (e.g. url#?foo=bar) to a URL with a query string.

    Normally, this app treats that as a file to NOT reload, using the query string as a mechanism to modify the
    currently loaded file, such as jumping to a line number. We instead convert this to a "normal" URL with a query
    string if the URL needs to load in a new tab or new window, for example.

    :Parameters:
        url : `QtCore.QUrl`
            URL
    :Returns:
        Converted URL
    :Rtype:
        `QtCore.QUrl`
    """
    if url.hasFragment():
        fragment = url.fragment()
        url.setFragment(None)
        if fragment.startswith("?"):
            url.setQuery(fragment[1:])
    return url


def usdRegEx(exts):
    """ RegEx to find other file paths in USD-based text files.
    
    :Parameters:
        exts:
            Iterable of `str` file path extensions without the starting dot.
    """
    return re.compile(
        r'(?:[\'"@]+)'                    # 1 or more single quote, double quote, or at symbol.
        r'('                              # Group 1: Path. This is the main group we are looking for. Matches based on extension before the pipe, or variable after the pipe.
            r'[^\t\n\r\f\v\'"]*?'         # 0 or more (greedy) non-whitespace characters (regular spaces are ok) and no quotes followed by a period, then 1 of the acceptable file extensions. NOTE: Backslash exclusion removed for Windows support; make sure this doesn't negatively affect other systems.
            r'\.(?:'+'|'.join(exts)+r')'  # followed by a period, then 1 of the acceptable file extensions
            r'|\${[\w/${}:.-]+}'          # One or more of these characters -- A-Za-z0-9_-/${}:. -- inside the variable curly brackets -- ${}
        r')'                              # end group 1
        r'(?:\[(.*?)\])?'                 # Optional layer reference for a usdz file as group 2. TODO: Figure out how to only match this if the extension matched was .usdz (e.g. foo.usdz[path/to/file/within/package.usd])
        r'(?::SDF_FORMAT_ARGS:(.*?))?'    # Optional :SDF_FORMAT_ARGS:key=value&foo=bar, with the query string parameters as group 3
        r'(?:[\'"@]|\\\")'  # 1 of: single quote, double quote, backslash followed by double quote, or at symbol.
    )
