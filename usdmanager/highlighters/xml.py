#
# Copyright 2018-2023 DreamWorks Animation L.L.C.
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
from __future__ import absolute_import
from Qt import QtCore, QtGui

from ..highlighter import MasterHighlighter


class MasterXMLHighlighter(MasterHighlighter):
    """ XML syntax highlighter
    """
    extensions = ["html", "xml"]
    comment = None
    multilineComment = ("<!--", "-->")
    
    def getRules(self):
        """ XML syntax highlighting rules """
        return [
            [   # XML element. Since we can't do a look behind in Qt to check for < or </, put this before the <>
                # symbols for tags get colored.
                r"</?\w+",
                QtCore.Qt.GlobalColor.darkRed,
                QtCore.Qt.GlobalColor.red
            ],
            [
                # XML symbols
                r"(?:/>|\?>|>|</?|<\?xml\b)",
                #(?:/>|\?>|<(?:/|\?xml)?)\\b)",
                QtCore.Qt.GlobalColor.darkMagenta,
                QtCore.Qt.GlobalColor.magenta,
                QtGui.QFont.Bold
            ],
            [   # XML attribute
                r"\b\w+(?==)",
                None,
                None,
                None,
                True  # Italic
            ],
            self.ruleNumber,
            self.ruleDoubleQuote,
            self.ruleSingleQuote,
        ]
