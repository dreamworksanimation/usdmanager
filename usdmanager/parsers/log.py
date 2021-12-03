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
Log file parser
"""
import re
from xml.sax.saxutils import escape

from Qt.QtCore import QFileInfo, Slot

from ..constants import TTY2HTML
from ..parser import AbstractExtParser
from ..utils import expandPath


class LogParser(AbstractExtParser):
    """ Used for log files that may contain terminal color code characters.
    """
    exts = ("log", "txt")
    
    @staticmethod
    def convertTeletype(t):
        """ Convert teletype codes to HTML styles.
        This method assumes you have already escaped any necessary HTML characters.
        
        :Parameters:
            t : `str`
                Original text
        :Returns:
            String with teletype codes converted to HTML styles.
        :Rtype:
            `str`
        """
        for (code, style) in TTY2HTML:
            t = t.replace(code, style)
        return "<span>{}</span>".format(t)
    
    @Slot()
    def compile(self):
        super(LogParser, self).compile()
        # Optionally match ", line " followed by a number (often found in tracebacks).
        # This number is used for attaching the query string ?line= to the URL
        self.regex = re.compile(self.regex.pattern + r'(?:, line (\d+))?')
    
    def htmlFormat(self, text):
        if self.parent().preferences['teletype']:
            text = self.convertTeletype(text)
        return super(LogParser, self).htmlFormat(text)
    
    def parseMatch(self, match, linkPath, nativeAbsPath, fileInfo):
        """ Parse a RegEx match of a patch to another file.
        
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
        # This group number must be carefully kept in sync based on the default RegEx from the parent class. 
        queryStr = "?line=" + match.group(2) if match.group(2) is not None else ""
        
        if QFileInfo(linkPath).isAbsolute():
            fullPath = QFileInfo(expandPath(linkPath, nativeAbsPath)).absoluteFilePath()
        else:
            # Relative path from the current file to the link.
            fullPath = fileInfo.dir().absoluteFilePath(expandPath(linkPath, nativeAbsPath))
        
        # Make the HTML link.
        if self.exists[fullPath]:
            return '<a href="file://{}{}">{}</a>'.format(fullPath, queryStr, escape(linkPath))
        elif '*' in linkPath or '<UDIM>' in linkPath or '.#.' in linkPath:
            # Create an orange link for files with wildcards in the path,
            # designating zero or more files may exist.
            return '<a title="Multiple files may exist" class="mayNotExist" href="file://{}{}">{}</a>'.format(
                   fullPath, queryStr, escape(linkPath))
        return '<a title="File not found" class="badLink" href="file://{}{}">{}</a>'.format(
               fullPath, queryStr, escape(linkPath))
