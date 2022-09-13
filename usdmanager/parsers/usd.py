#
# Copyright 2020 DreamWorks Animation L.L.C.
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
USD file parsers
"""
import logging
import os
from os.path import sep, splitext
import re
import traceback
from xml.sax.saxutils import escape, unescape

from Qt.QtCore import QDir, QFile, QFileInfo, Slot
from Qt.QtGui import QIcon

from .. import utils
from ..constants import FILE_FORMAT_USD, FILE_FORMAT_USDA, FILE_FORMAT_USDC, FILE_FORMAT_USDZ,\
    USD_AMBIGUOUS_EXTS, USD_ASCII_EXTS, USD_CRATE_EXTS, USD_ZIP_EXTS
from ..parser import AbstractExtParser, SaveFileError


# Set up logging.
logger = logging.getLogger(__name__)
logging.basicConfig()


NT = os.name == "nt"
NT_REGEX = re.compile(r'^[a-zA-Z]:[/\\]')


class UsdAsciiParser(AbstractExtParser):
    """ USD ASCII files.

    Treat as plain text. This is the simplest of the Usd parsers, which other USD parsers should inherit from.
    """
    exts = USD_ASCII_EXTS
    fileFormat = FILE_FORMAT_USDA

    def __init__(self, *args, **kwargs):
        super(UsdAsciiParser, self).__init__(*args, **kwargs)
        self.regex = None
        self.plugins.append((QIcon(":/images/images/usd.png"), "Open with usdview...", self.parent().launchUsdView))
        self.usdArrayRegEx = re.compile(
            r"((?:\s*(?:\w+\s+)?\w+\[\]\s+[\w:]+\s*=|\s*\d+:)\s*\[)"  # Array attribute definition and equal sign, or a frame number and colon, plus the opening bracket.
            r"\s*(.*)\s*"  # Everything inside the square brackets.
            r"(\].*)$"  # Closing bracket to the end of the line.
        )

    @Slot()
    def compile(self):
        """ Compile regular expression to find links in USD files.
        """
        self.regex = utils.usdRegEx(self.parent().programs.keys())

    def parse(self, nativeAbsPath, fileInfo, link):
        """ Parse a file for links, generating a plain text version and HTML version of the file text.

        :Parameters:
            nativeAbsPath : `str`
                OS-native absolute file path
            fileInfo : `QFileInfo`
                File info object
            link : `QUrl`
                Full file path URL
        """
        # Preserve any :SDF_FORMAT_ARGS: parameters from the current link.
        self.sdf_format_args = utils.sdfQuery(link)
        self.extractedDir = utils.queryItemValue(link, "extractedDir")
        return super(UsdAsciiParser, self).parse(nativeAbsPath, fileInfo, link)

    def parseMatch(self, match, linkPath, nativeAbsPath, fileInfo):
        """ Parse a RegEx match of a path to another file.

        Override for specific language parsing.

        :Parameters:
            match
                RegEx match object
            linkPath : `str`
                Displayed file path matched by the RegEx
            nativeAbsPath : `str`
                OS-native absolute file path for the file being parsed
            fileInfo : `QFileInfo`
                File info object for the file being parsed
        :Returns:
            HTML link
        :Rtype:
            `str`
        :Raises ValueError:
            If path does not exist or cannot be resolved.
        """
        # Since we had to escape all potential HTML-related characters before finding links, undo any replaced
        # by escape if part of the linkPath itself. URIs may have & as part of the path for query parameters.
        # We then have to re-escape the path before inserting it into HTML.
        linkPath = unescape(linkPath)
        expanded_path = utils.expandPath(
            linkPath, nativeAbsPath,
            self.sdf_format_args,
            extractedDir=self.extractedDir)
        if QFileInfo(linkPath).isAbsolute():
            fullPath = QFileInfo(expanded_path).absoluteFilePath()
            logger.debug("Parsed link is absolute (%s). Expanded to %s", linkPath, fullPath)
        else:
            # Relative path from the current file to the link.
            fullPath = fileInfo.dir().absoluteFilePath(expanded_path)
            logger.debug("Parsed link is relative (%s). Expanded to %s", linkPath, fullPath)

        # Override any previously set sdf format args.
        local_sdf_args = self.sdf_format_args.copy()
        if match.group(3):
            for kv in match.group(3).split("&"):
                k, v = kv.split("=", 1)
                expanded_path = utils.expandPath(
                    v, nativeAbsPath, self.sdf_format_args,
                    extractedDir=self.extractedDir)
                local_sdf_args[k] = expanded_path.replace("&", "+").replace("=", ":")
        if local_sdf_args:
            queryParams = ["sdf=" + "+".join("{}:{}".format(k, v) for k, v in
                           sorted(local_sdf_args.items(), key=lambda x: x[0]))]
        else:
            queryParams = []

        # .usdz file references (e.g. @set.usdz[foo/bar.usd]@)
        if match.group(2):
            queryParams.append("layer=" + match.group(2))

        # Propogate the extracted archive if this resolved file is in the same archive
        if self.extractedDir and fullPath.startswith(self.extractedDir + sep):
            queryParams.append("extractedDir=" + self.extractedDir)

        def pathForLink(path):
            """Need three slashes before drive letter on Windows; this prepends one, so
            with the usual two URL slashes we'll get the proper format."""
            return '/' + path if NT and NT_REGEX.match(fullPath) else path

        # Make the HTML link.
        if self.exists[fullPath]:
            _, fullPathExt = splitext(fullPath)
            if fullPathExt[1:] in USD_CRATE_EXTS or (fullPathExt[1:] in USD_AMBIGUOUS_EXTS and
                                                     utils.isUsdCrate(fullPath)):
                queryParams.insert(0, "binary=1")
                link = '<a class="binary" href="file://{}?{}">{}</a>'.format(pathForLink(fullPath),
                                                                             "&".join(queryParams), escape(linkPath))
                logger.debug('parseMatch: created binary link <%s> for path <%s>', link, linkPath)
            else:
                queryStr = "?" + "&".join(queryParams) if queryParams else ""
                link = '<a href="file://{}{}">{}</a>'.format(pathForLink(fullPath), queryStr, escape(linkPath))
                logger.debug('parseMatch: created link <%s> for path <%s>', link, linkPath)
            return link
        elif '*' in linkPath or '<UDIM>' in linkPath or '.#.' in linkPath:
            # Create an orange link for files with wildcards in the path,
            # designating zero or more files may exist.
            queryStr = "?" + "&".join(queryParams) if queryParams else ""
            return '<a title="Multiple files may exist" class="mayNotExist" href="file://{}{}">{}</a>'.format(
                pathForLink(fullPath), queryStr, escape(linkPath))

        queryStr = "?" + "&".join(queryParams) if queryParams else ""
        return '<a title="File not found" class="badLink" href="file://{}{}">{}</a>'.format(
            pathForLink(fullPath), queryStr, escape(linkPath))

    def parseLongLine(self, line):
        """ Process a long line. Link parsing is skipped, and long USD arrays are truncated in the middle.

        :Parameters:
            line : `str`
                Line of text
        :Returns:
            Line of text
        :Rtype:
            `str`
        """
        match = self.usdArrayRegEx.match(line)
        if match:
            # Try to display just the first and last items in the long array with an ellipsis in the middle.
            # This drastically improves text browser interactivity and syntax highlighting time.
            logger.debug("Hiding long array")

            # Try to split to the first true item based on open parentheses.
            # This is hacky and prone to error if users have hand-edited the files.
            innerData = match.group(2)
            if innerData.startswith("(("):
                split = ")),"
            elif innerData.startswith("("):
                split = "),"
            else:
                split = ","
            innerData = innerData.split(split, 1)[0] + split +\
                        "<span title='Long array truncated for display performance'> &hellip; </span>" +\
                        innerData.rsplit(split, 1)[-1].lstrip()

            return "{}{}{}\n".format(match.group(1), innerData, match.group(3))
        return super(UsdAsciiParser, self).parseLongLine(line)


class UsdCrateParser(UsdAsciiParser):
    """ Parse USD file assuming it is a crate file.

    Don't bother checking the fist line for PXR-USDC. If this is a valid ASCII USD file and not binary, but we use this
    parser accidentally, the file will load slower (since we do a usdcat conversion) but won't break anything.
    """
    binary = True
    exts = USD_CRATE_EXTS
    fileFormat = FILE_FORMAT_USDC
    icon = utils.icon("binary")

    def acceptsFile(self, fileInfo, link):
        """ Accept .usdc files, or .usd files that do have a true binary query string value (i.e. .usd files we've
        already confirmed are crate).

        :Parameters:
            fileInfo : `QFileInfo`
                File info object
            link : `QtCore.QUrl`
                Full URL, potentially with query string
        """
        ext = fileInfo.suffix()
        return ext in self.exts or (ext in USD_AMBIGUOUS_EXTS and utils.queryItemBoolValue(link, "binary"))

    @staticmethod
    def generateTempFile(fileName, tmpDir=None):
        """ Generate a temporary ASCII USD file that the user can edit.

        :Parameters:
            fileName : `str`
                Binary USD file path
            tmpDir : `str` | None
                Temp directory to create the new file within
        :Returns:
            Temporary file name
        :Rtype:
            `str`
        :Raises OSError:
            If USD conversion fails
        """
        return utils.generateTemporaryUsdFile(fileName, tmpDir)

    def read(self, path):
        return self.parent().readBinaryFile(path, self)

    def write(self, qFile, filePath, tab, tmpDir):
        """ Write out the text to an ASCII file, then convert it to crate.

        :Parameters:
            qFile : `QtCore.QFile`
                Object representing the file to write to
            filePath : `str`
                File path to write to
            tab : `str`
                Tab being written
            tmpDir : `str`
                Temporary directory, if needed for any write operations.
        :Raises SaveFileError:
            If the file write fails.
        """
        fd, tmpPath = utils.mkstemp(suffix="." + USD_AMBIGUOUS_EXTS[0], dir=tmpDir)
        os.close(fd)
        super(UsdCrateParser, self).write(QFile(tmpPath), tmpPath, tab, tmpDir)
        try:
            logger.debug("Converting back to USD crate file")
            utils.usdcat(tmpPath, QDir.toNativeSeparators(filePath), format="usdc")
        except Exception:
            logger.exception("Save failed on USD crate conversion")
            raise SaveFileError("The file could not be saved due to a usdcat error!", traceback.format_exc())
        tab.parser = self
        tab.fileFormat = self.fileFormat
        os.remove(tmpPath)


class UsdParser(UsdAsciiParser):
    """ Parse ambiguous USD files that may be ASCII or crate.
    """
    exts = USD_AMBIGUOUS_EXTS
    fileFormat = FILE_FORMAT_USD

    def acceptsFile(self, fileInfo, link):
        """ Accept .usd files that do not have a true binary query string in the URL (i.e. we haven't yet opened this
        file to determine if it is crate, or we have checked and it wasn't crate).

        :Parameters:
            fileInfo : `QFileInfo`
                File info object
            link : `QtCore.QUrl`
                Full URL, potentially with query string
        """
        return fileInfo.suffix() in self.exts and not utils.queryItemBoolValue(link, "binary")

    def setBinary(self, binary):
        """ Set if the parser is currently parsing a binary or ASCII file.

        :Parameters:
            binary : `bool`
                If the current file is binary or ASCII.
        """
        self.binary = binary
        if binary:
            self.fileFormat = FILE_FORMAT_USDC
            self.icon = UsdCrateParser.icon
        else:
            self.fileFormat = FILE_FORMAT_USDA
            self.icon = UsdAsciiParser.icon

    def read(self, path):
        with open(path) as f:
            # Read in the first line. If it's a binary USD file,
            # convert it to a temp ASCII file for viewing/editing.
            if f.readline().startswith("PXR-USDC"):
                self.setBinary(True)
                return self.parent().readBinaryFile(path, UsdCrateParser)

            self.setBinary(False)
            # Read in the full file.
            f.seek(0)
            return f.readlines()

    def write(self, *args, **kwargs):
        """ Write out the text to an ASCII or crate file.

        :Parameters:
            qFile : `QtCore.QFile`
                Object representing the file to write to
            filePath : `str`
                File path to write to
            tab : `str`
                Tab being written
            tmpDir : `str`
                Temporary directory, if needed for any write operations.
        :Raises SaveFileError:
            If the file write fails.
        """
        if self.binary:
            UsdCrateParser.write(self, *args, **kwargs)
        else:
            super(UsdParser, self).write(*args, **kwargs)


class UsdzParser(UsdParser):
    """ Parse zipped USD archives.
    """
    exts = USD_ZIP_EXTS
    fileFormat = FILE_FORMAT_USDZ
    icon = utils.icon("zip", utils.icon("package-x-generic"))

    def read(self, path, layer=None, cache=None, tmpDir=None):
        """ Read in a USD zip (.usdz) file via usdzip, uncompressing to a temp directory.

        :Parameters:
            path : `str`
                USDZ file path
            layer : `str` | None
                Default layer within file (e.g. the portion within the square brackets here:
                @foo.usdz[path/to/file/within/package.usd]@)
            cache : `dict` | None
                Dictionary of cached (e.g. unzipped) files
            tmpDir : `str` | None
                Temporary directory to use for unzipping
        :Returns:
            Destination file
        :Rtype:
            `str`
        :Raises zipfile.BadZipfile:
            For bad ZIP files
        :Raises zipfile.LargeZipFile:
            When a ZIP file would require ZIP64 functionality but that has not been enabled
        :Raises ValueError:
            If default layer not found
        """
        cache = cache or {}

        # Cache the unzipped directory so we can use it again later without reconversion if it's still newer.
        if (path in cache and
                QFileInfo(cache[path]).lastModified() > QFileInfo(path).lastModified()):
            usdPath = cache[path]
            logger.debug("Reusing cached directory %s for zip file %s", usdPath, path)
        else:
            logger.debug("Uncompressing usdz file...")
            usdPath = utils.unzip(path, tmpDir)
            cache[path] = usdPath

        # Check for a nested usdz reference (e.g. @set.usdz[areas/shire.usdz[architecture/BilboHouse/Table.usd]]@)
        if layer and '[' in layer:
            # Get the next level of .usdz file and unzip it.
            layer1, layer2 = layer.split('[', 1)
            dest = utils.getUsdzLayer(usdPath, layer1, path)
            return self.readUsdzFile(dest, layer2)

        args = "?extractedDir={}".format(usdPath)
        return utils.getUsdzLayer(usdPath, layer, path) + args

    def write(self, *args, **kwargs):
        """ Write out a USD zip file.

        :Parameters:
            qFile : `QtCore.QFile`
                Object representing the file to write to
            filePath : `str`
                File path to write to
            tab : `str`
                Tab being written
            tmpDir : `str`
                Temporary directory, if needed for any write operations.
        :Raises SaveFileError:
            If the file write fails.
        """
        raise SaveFileError("Writing usdz files is not yet supported!")
