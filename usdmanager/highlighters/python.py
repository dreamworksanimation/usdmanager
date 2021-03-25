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
from Qt import QtCore, QtGui

from ..highlighter import createMultilineRule, MasterHighlighter


class MasterPythonHighlighter(MasterHighlighter):
    """ Python syntax highlighter.
    """
    extensions = ["py"]
    comment = "#"
    multilineComment = ('"""', '"""')
    
    def getRules(self):
        return [
            [   # Symbols
                "[(){}\[\]]",
                QtCore.Qt.darkMagenta,
                QtCore.Qt.magenta,
                QtGui.QFont.Bold
            ],
            [
                # Keywords
                r"\b(?:and|as|assert|break|class|continue|def|del|elif|else|except|exec|finally|for|from|global|if|"
                r"import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b",
                QtGui.QColor("#4b7029"),
                QtGui.QColor("#4b7029"),
                QtGui.QFont.Bold
            ],
            [
                # Built-ins
                r"\b(?:ArithmeticError|AssertionError|AttributeError|BaseException|BufferError|BytesWarning|"
                "DeprecationWarning|EOFError|Ellipsis|EnvironmentError|Exception|False|FloatingPointError|"
                "FutureWarning|GeneratorExit|IOError|ImportError|ImportWarning|IndentationError|IndexError|KeyError|"
                "KeyboardInterrupt|LookupError|MemoryError|NameError|None|NotImplemented|NotImplementedError|OSError|"
                "OverflowError|PendingDeprecationWarning|ReferenceError|RuntimeError|RuntimeWarning|StandardError|"
                "StopIteration|SyntaxError|SyntaxWarning|SystemError|SystemExit|TabError|True|TypeError|"
                "UnboundLocalError|UnicodeDecodeError|UnicodeEncodeError|UnicodeError|UnicodeTranslateError|"
                "UnicodeWarning|UserWarning|ValueError|Warning|ZeroDivisionError|__debug__|__doc__|__import__|"
                "__name__|__package__|abs|all|any|apply|basestring|bin|bool|buffer|bytearray|bytes|callable|chr|"
                "classmethod|cmp|coerce|compile|complex|copyright|credits|delattr|dict|dir|divmod|dreload|enumerate|"
                "eval|execfile|file|filter|float|format|frozenset|get_ipython|getattr|globals|hasattr|hash|help|hex|"
                "id|input|int|intern|isinstance|issubclass|iter|len|license|list|locals|long|map|max|memoryview|min|"
                "next|object|oct|open|ord|pow|print|property|range|raw_input|reduce|reload|repr|reversed|round|set|"
                r"setattr|slice|sorted|staticmethod|str|sum|super|tuple|type|unichr|unicode|vars|xrange|zip)\b",
                QtGui.QColor("#678CB1"),
                QtGui.QColor("#678CB1")
            ],
            [   # Operators
                '[\-+*/%=!<>&|^~]',
                QtGui.QColor("#990000"),
                QtGui.QColor("#990000")
            ],
            self.ruleNumber,
            self.ruleDoubleQuote,
            self.ruleSingleQuote,
            self.ruleLink,
            self.ruleComment
        ]
    
    def createRules(self):
        super(MasterPythonHighlighter, self).createRules()
        
        # Support single-quote triple quotes in additional the the double quote triple quotes.
        self.multilineRules.append(createMultilineRule("'''", "'''", QtCore.Qt.gray, italic=True))
