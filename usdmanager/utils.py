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
import subprocess
import tempfile
from contextlib import contextmanager
from glob import glob
from pkg_resources import resource_filename

import Qt
from Qt import QtCore, QtWidgets
if Qt.IsPySide:
    import pysideuic as uic
elif Qt.IsPySide2:
    import pyside2uic as uic
else:
    uic = Qt._uic

from .constants import USD_EXTS


# Set up logging.
logger = logging.getLogger(__name__)
logging.basicConfig()

try:
    from pxr import Ar
    resolver = Ar.GetResolver()
except ImportError:
    logger.warn("Unable to create AssetResolver - Asset links may not work correctly")
    resolver = None


def expandPath(path, parentPath=None, sdf_format_args=None):
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
    :Returns:
        Normalized path with variables expanded.
    :Rtype:
        `str`
    """
    path = os.path.expanduser(os.path.normpath(path))
    
    if resolver is not None:
        try:
            resolver.ConfigureResolverForAsset(path)
            context = resolver.CreateDefaultContextForAsset(path)
            with Ar.ResolverContextBinder(context):
                anchoredPath = path if parentPath is None else resolver.AnchorRelativePath(parentPath, path)
                resolved = resolver.Resolve(anchoredPath)
        except Exception:
            logger.warn("Failed to resolve Asset path {} with parent {}".format(path, parentPath))
        else:
            if resolved:
                return resolved
    
    # Return this best-attempt if all else fails.
    return os.path.expandvars(path)


def expandUrl(path, parentPath=None):
    """ Expand and normalize a URL that may have variables in it and a query string after it.

    :Parameters:
        path : `str`
            File path
        parentPath : `str` | None
            Parent file path this file is defined in relation to.
            Helps with asset resolution.
    :Returns:
        Normalized path with variables expanded.
    :Rtype:
        `str`
    """
    sdf_format_args = {}
    if "?" in path:
        sdf_format_args.update(sdfQuery(QtCore.QUrl(path)))
        path, query = path.split("?", 1)
        query = "?" + query
    else:
        query = ""
    return QtCore.QUrl(os.path.abspath(expandPath(path, parentPath, sdf_format_args)) + query)


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
    logger.info("Searching for *.py plugins in {}".format(pluginPath))
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
    fd, tmpFileName = tempfile.mkstemp(suffix=".usd", dir=tmpDir)
    os.close(fd)
    usdcat(usdFileName, tmpFileName, format="usda")
    return tmpFileName


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
    if os.name == "nt":
        # Files with spaces have to be double-quoted on Windows.
        cmd = 'usdcat "{}" -o "{}"'.format(inputFile, outputFile)
    else:
        cmd = 'usdcat {} -o {}'.format(inputFile, outputFile)
    
    if format and outputFile.endswith(".usd"):
        # For usdcat, use of --usdFormat requires output file end with '.usd' extension.
        cmd += " --usdFormat {}".format(format)
    logger.debug(cmd)
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
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
    if os.name == "nt":
        # Files with spaces have to be double-quoted on Windows.
        if type(inputs) is list:
            inputs = '" "'.join(inputs)
        cmd = 'usdzip "{}" "{}"'.format(inputs, dest)
        logger.debug(cmd)
    else:
        cmd = ["usdzip"]
        if type(inputs) is list:
            cmd += inputs
        else:
            cmd.append(inputs)
        cmd.append(dest)
        logger.debug(subprocess.list2cmdline(cmd))
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
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
    
    destDir = tempfile.mkdtemp(prefix="usdmanager_usdz_", dir=tmpDir)
    logger.debug("Extracting {} to {}".format(path, destDir))
    with ZipFile(path, 'r') as zipRef:
        zipRef.extractall(destDir)
    return destDir


def getUsdzLayer(usdzDir, layer=None):
    """ Get a layer from an unzipped usdz archive.
    
    :Parameters:
        usdzDir : `str`
            Unzipped directory path
        layer : `str`
            Default layer within file (e.g. the portion within the square brackets here:
            @foo.usdz[path/to/file/within/package.usd]@)
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
    
    # TODO: Figure out if this is really the proper way to get the default layer.
    destFile = os.path.join(usdzDir, "defaultLayer.usd")
    if os.path.exists(destFile):
        return destFile
    files = glob(os.path.join(usdzDir, "*.usd")) + glob(os.path.join(usdzDir, "*.usd[ac]"))
    if files:
        if len(files) == 1:
            return files[0]
        else:
            raise ValueError("Ambiguous default layer in usdz archive!")
    else:
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
    for unit in ["bytes", "kB", "MB", "GB"]:
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
    with open(path) as f:
        return f.readline().startswith("PXR-USDC")


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


def loadUiType(uiFile, sourceFile=None, className="DefaultWidgetClass"):
    """ Used to define a custom widget's class.
    
    :Parameters:
        uiFile : `str`
            UI file path. Can be relative if loading from the same directory as sourceFile.
        sourceFile : `str`
            File path of loading module.
            Used to help find embedded resources and to find uiFile when the file path is relative.
        className : `str`
            Class name
    :Returns:
        Class type
    :Rtype:
        `type`
    """
    import sys
    import xml.etree.ElementTree as xml
    from StringIO import StringIO
    from Qt import QtWidgets
    
    if not os.path.exists(uiFile) and not os.path.isabs(uiFile):
        if sourceFile is None:
            uiFile = resource_filename(__name__, uiFile)
            sourceDir = os.path.dirname(uiFile)
        else:
            sourceDir = os.path.dirname(sourceFile)
            uiFile = os.path.join(sourceDir, uiFile)
    else:
        sourceDir = os.path.dirname(uiFile)
    
    # Search for resources in this tool's directory.
    if sourceDir not in sys.path:
        sys.path.insert(0, sourceDir)
    
    parsed = xml.parse(uiFile)
    widget_class = parsed.find('widget').get('class')
    form_class = parsed.find('class').text
    
    with open(uiFile) as f:
        o = StringIO()
        frame = {}
        uic.compileUi(f, o, indent=0)
        pyc = compile(o.getvalue(), "<string>", "exec")
        exec pyc in frame
        
        # Fetch the base_class and form class based on their type.
        form_class = frame["Ui_{}".format(form_class)]
        base_class = eval("QtWidgets.{}".format(widget_class))
    return type("{}Base".format(className), (form_class, base_class), {})


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
            if not member.startswith('__') and member is not 'staticMetaObject':
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
    from Qt.QtWidgets import QApplication
    
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
    url = url.toString()
    if "?" in url:
        query = url.split("?", 1)[1]
        for item in query.split("&"):
            if item:
                try:
                    k, v = item.split("=")
                except ValueError:
                    logger.error("Invalid query string: {}".format(query))
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
    except Exception as e:
        logger.error("Invalid sdf query parameter: {}".format(e))
    return sdf_format_args


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
