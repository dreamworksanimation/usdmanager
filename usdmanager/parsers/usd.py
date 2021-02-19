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
import re
from os.path import sep, splitext

from Qt.QtCore import QFileInfo, Slot

from .. import utils
from ..constants import FILE_FORMAT_USD, FILE_FORMAT_USDA, FILE_FORMAT_USDC
from ..parser import AbstractExtParser


# Set up logging.
logger = logging.getLogger(__name__)
logging.basicConfig()


class UsdAsciiParser(AbstractExtParser):
    """ USD ASCII files.
    
    Treat as plain text. This is the simplest of the Usd parsers, which other USD parsers should inherit from.
    """
    exts = ("usda",)
    fileFormat = FILE_FORMAT_USDA
    
    def __init__(self, *args, **kwargs):
        super(UsdAsciiParser, self).__init__(*args, **kwargs)
        self.regex = None
        self.usdArrayRegEx = re.compile(
            "((?:\s*(?:\w+\s+)?\w+\[\]\s+[\w:]+\s*=|\s*\d+:)\s*\[)"  # Array attribute definition and equal sign, or a frame number and colon, plus the opening bracket.
            "\s*(.*)\s*"  # Everything inside the square brackets.
            "(\].*)$"  # Closing bracket to the end of the line.
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
            for kv in match.group(3).split("&amp;"):
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
        
        # Make the HTML link.
        if self.exists[fullPath]:
            _, fullPathExt = splitext(fullPath)
            if fullPathExt == ".usdc" or (fullPathExt == ".usd" and utils.isUsdCrate(fullPath)):
                queryParams.insert(0, "binary=1")
                return '<a class="binary" href="file://{}?{}">{}</a>'.format(fullPath, "&".join(queryParams), linkPath)
            
            queryStr = "?" + "&".join(queryParams) if queryParams else ""
            return '<a href="file://{}{}">{}</a>'.format(fullPath, queryStr, linkPath)
        elif '*' in linkPath or '&lt;UDIM&gt;' in linkPath or '.#.' in linkPath:
            # Create an orange link for files with wildcards in the path,
            # designating zero or more files may exist.
            queryStr = "?" + "&".join(queryParams) if queryParams else ""
            return '<a title="Multiple files may exist" class="mayNotExist" href="file://{}{}">{}</a>'.format(
                   fullPath, queryStr, linkPath)
        
        queryStr = "?" + "&".join(queryParams) if queryParams else ""
        return '<a title="File not found" class="badLink" href="file://{}{}">{}</a>'.format(
               fullPath, queryStr, linkPath)
    
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
    exts = ("usdc",)
    fileFormat = FILE_FORMAT_USDC
    
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
        return ext in self.exts or (ext == "usd" and utils.queryItemBoolValue(link, "binary"))
    
    def read(self, path):
        return self.parent().readUsdCrateFile(path)


class UsdParser(UsdAsciiParser):
    """ Parse ambiguous USD files that may be ASCII or crate.
    """
    exts = ("usd",)
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
    
    def read(self, path):
        with open(path) as f:
            # Read in the first line. If it's a binary USD file,
            # convert it to a temp ASCII file for viewing/editing.
            if f.readline().startswith("PXR-USDC"):
                self.fileFormat = FILE_FORMAT_USDC
                return self.parent().readUsdCrateFile(path)
            
            self.fileFormat = FILE_FORMAT_USDA
            # Read in the full file.
            f.seek(0)
            return f.readlines()
