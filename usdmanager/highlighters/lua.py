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
Lua syntax highlighter
"""
from Qt import QtCore, QtGui

from ..highlighter import MasterHighlighter


class MasterLuaHighlighter(MasterHighlighter):
    """ Lua syntax highlighter.
    """
    extensions = ["lua"]
    comment = "--"
    multilineComment = ("--[[", "]]")

    def getRules(self):
        return [
            [   # Symbols
                "[(){}[\]]",
                QtCore.Qt.darkMagenta,
                QtCore.Qt.magenta,
                QtGui.QFont.Bold
            ],
            [
                # Keywords
                r"\b(?:and|break|do|else|elseif|end|for|function|if|in|local|not|or|repeat|return|then|until|while)\b",
                QtGui.QColor("#4b7029"),
                QtGui.QColor("#4b7029"),
                QtGui.QFont.Bold
            ],
            [
                # Built-in constants
                r"\b(?:true|false|nil|_G|_VERSION)\b",
                QtGui.QColor("#997500"),
                QtGui.QColor("#997500"),
                QtGui.QFont.Bold
            ],
            [
                # Built-in functions
                r"\b(?:abs|acos|asin|assert|atan|atan2|byte|ceil|char|clock|close|collectgarbage|concat|config|"
                "coroutine|cos|cosh|cpath|create|date|debug|debug|deg|difftime|dofile|dump|error|execute|exit|exp|"
                "find|floor|flush|fmod|foreach|foreachi|format|frexp|gcinfo|getenv|getfenv|getfenv|gethook|getinfo|"
                "getlocal|getmetatable|getmetatable|getn|getregistry|getupvalue|gfind|gmatch|gsub|huge|input|insert|"
                "io|ipairs|ldexp|len|lines|load|loaded|loaders|loadfile|loadlib|loadstring|log|log10|lower|match|math|"
                "max|maxn|min|mod|modf|module|newproxy|next|open|os|output|package|pairs|path|pcall|pi|popen|pow|"
                "preload|print|rad|random|randomseed|rawequal|rawget|rawset|read|remove|remove|rename|rep|require|"
                "resume|reverse|running|seeall|select|setfenv|setfenv|sethook|setlocal|setlocale|setmetatable|"
                "setmetatable|setn|setupvalue|sin|sinh|sort|sqrt|status|stderr|stdin|stdout|string|sub|table|tan|tanh|"
                r"time|tmpfile|tmpname|tonumber|tostring|traceback|type|type|unpack|upper|wrap|write|xpcall|yield)\b",
                QtGui.QColor("#678CB1"),
                QtGui.QColor("#678CB1")
            ],
            [
                # Standard libraries
                r"\b(?:coroutine|debug|io|math|os|package|string|table)\b",
                QtGui.QColor("#8080FF"),
                QtGui.QColor("#8080FF")
            ],
            [   # Operators
                '(?:[\-+*/%=!<>&|^~]|\.\.)',
                QtGui.QColor("#990000"),
                QtGui.QColor("#990000")
            ],
            self.ruleNumber,
            self.ruleDoubleQuote,
            self.ruleSingleQuote,
            self.ruleLink,
            self.ruleComment
        ]
