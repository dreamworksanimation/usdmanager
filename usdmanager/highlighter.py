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
Custom syntax highlighters.
"""

import inspect
import re

from Qt import QtCore, QtGui

from .constants import LINE_CHAR_LIMIT
from .utils import findModules


# Enabled when running in a theme with a dark background color.
DARK_THEME = False


def createRule(pattern, color=None, darkColor=None, weight=None, italic=False, cs=QtCore.Qt.CaseSensitive):
    """ Create a single-line syntax highlighting rule.
    
    :Parameters:
        pattern : `str`
            RegEx to match
        color : `QtGui.QColor`
            Color to highlight matches when in a light background theme
        darkColor : `QtGui.QColor`
            Color to highlight matches when in a dark background theme.
            Defaults to color if not given.
        weight : `int` | None
            Optional font weight for matches
        italic : `bool`
            Set the font to italic
        cs : `int`
            Case sensitivity for RegEx matching
    :Returns:
        Tuple of `QtCore.QRegExp` and `QtGui.QTextCharFormat` objects.
    :Rtype:
        tuple
    """
    frmt = QtGui.QTextCharFormat()
    if DARK_THEME and darkColor is not None:
        frmt.setForeground(darkColor)
    elif color is not None:
        frmt.setForeground(color)
    if weight is not None:
        frmt.setFontWeight(weight)
    if italic:
        frmt.setFontItalic(True)
    return QtCore.QRegExp(pattern, cs), frmt


def createMultilineRule(startPattern, endPattern, color=None, darkColor=None, weight=None, italic=False, cs=QtCore.Qt.CaseSensitive):
    """ Create a multiline syntax highlighting rule.
    
    :Parameters:
        startPattern : `str`
            RegEx to match for the start of the block of lines.
        endPattern : `str`
            RegEx to match for the end of the block of lines.
        color : `QtGui.QColor`
            Color to highlight matches
        darkColor : `QtGui.QColor`
            Color to highlight matches when in a dark background theme.
        weight : `int` | None
            Optional font weight for matches
        italic : `bool`
            Set the font to italic
        cs : `int`
            Case sensitivity for RegEx matching
    :Returns:
        Tuple of `QtCore.QRegExp` and `QtGui.QTextCharFormat` objects.
    :Rtype:
        tuple
    """
    start, frmt = createRule(startPattern, color, darkColor, weight, italic, cs)
    end = QtCore.QRegExp(endPattern, cs)
    return start, end, frmt


def findHighlighters():
    """ Get the installed highlighter classes.
    
    :Returns:
        List of `MasterHighlighter` objects
    :Rtype:
        `list`
    """
    # Find all available "MasterHighlighter" subclasses within the highlighters module.
    classes = []
    for module in findModules("highlighters"):
        for _, cls in inspect.getmembers(module, lambda x: inspect.isclass(x) and issubclass(x, MasterHighlighter)):
            classes.append(cls)
    return classes


class MasterHighlighter(QtCore.QObject):
    """ Master object containing shared highlighting rules.
    """
    dirtied = QtCore.Signal()
    
    # List of file extensions (without the starting '.') to register this
    # highlighter for. The MasterHighlighter class is explicity set to [None]
    # as the default highlighter when a matching file extension is not found.
    extensions = [None]
    
    # Character(s) to start a single-line comment, or None for no comment support.
    comment = "#"
    
    # Tuple of start and end strings for a multiline comment (e.g. ("--[[", "]]") for Lua),
    # or None for no multiline comment support.
    multilineComment = None
    
    def __init__(self, parent, enableSyntaxHighlighting=False, programs=None):
        """ Initialize the master highlighter, used once per language and shared among tabs.
        
        :Parameters:
            parent : `QtCore.QObject`
                Can install to a `QTextEdit` or `QTextDocument` to apply highlighting.
            enableSyntaxHighlighting : `bool`
                Whether or not to enable syntax highlighting.
            programs : `dict`
                extension: program pairs of strings. This is used to contruct a syntax rule
                to undo syntax highlighting on links so that we see their original colors.
        """
        super(MasterHighlighter, self).__init__(parent)
        
        # Highlighting rules. Rules farther down take priority.
        self.highlightingRules = []
        self.multilineRules = []
        self.rules = []

        # Match everything for clearing syntax highlighting.
        self.blankRules = [createRule(".+")]
        self.enableSyntax = None
        self.findPhrase = None
        
        # Undo syntax highlighting on at least some of our links so the assigned colors show.
        self.ruleLink = createRule("*")
        self.highlightingRules.append(self.ruleLink)
        self.setLinkPattern(programs or {}, dirty=False)
        
        # Some general single-line rules that apply to many file formats.
        # Numeric literals
        self.ruleNumber = [
            r'\b[+-]?(?:[0-9]+[lL]?|0[xX][0-9A-Fa-f]+[lL]?|[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\b',
            QtCore.Qt.darkBlue,
            QtCore.Qt.cyan
        ]
        # Double-quoted string, possibly containing escape sequences.
        self.ruleDoubleQuote = [
            r'"[^"\\]*(?:\\.[^"\\]*)*"',
            QtCore.Qt.darkGreen,
            QtGui.QColor(25, 255, 25)
        ]
        # Single-quoted string, possibly containing escape sequences.
        self.ruleSingleQuote = [
            r"'[^'\\]*(?:\\.[^'\\]*)*'",
            QtCore.Qt.darkGreen,
            QtGui.QColor(25, 255, 25)
        ]
        # Matches a comment from the starting point to the end of the line,
        # if not part of a single- or double-quoted string.
        if self.comment:
            self.ruleComment = [
                "^(?:[^\"']|\"[^\"]*\"|'[^']*')*(" + re.escape(self.comment) + ".*)$",  # TODO: This should probably be language-specific instead of assumed for all.
                QtCore.Qt.gray,
                QtCore.Qt.gray,
                None,  # Not bold
                True  # Italic
            ]
        
        # Create the rules specific to this syntax.
        self.createRules()
        
        # If createRules didn't place the link rule in a specific place, put it at the end.
        if self.ruleLink not in self.highlightingRules:
            self.highlightingRules.append(self.ruleLink)
        
        self.setSyntaxHighlighting(enableSyntaxHighlighting)
    
    def getRules(self):
        """ Syntax rules specific to this highlighter class.
        """
        # Operators.
        return [
            [   # Operators
                r'[\-+*/%=!<>&|^~]',
                QtCore.Qt.red,
                QtGui.QColor("#F33")
            ],
            self.ruleNumber,
            self.ruleDoubleQuote,
            self.ruleSingleQuote,
            self.ruleLink,  # Undo syntax highlighting on at least some of our links so the assigned colors show.
            self.ruleComment
        ]
    
    def createRules(self):
        for r in self.getRules():
            self.highlightingRules.append(createRule(*r) if type(r) is list else r)
        
        # Multi-line comment.
        if self.multilineComment:
            self.multilineRules.append(createMultilineRule(
                # Make sure the start of the comment isn't inside a single- or double-quoted string.
                # TODO: This should probably be language-specific instead of assumed for all.
                "^(?:[^\"']|\"[^\"]*\"|'[^']*')*(" + re.escape(self.multilineComment[0]) + ")",
                re.escape(self.multilineComment[1]),
                QtCore.Qt.gray,
                italic=True))
    
    def dirty(self):
        """ Let highlighters that subscribe to this know a rule has changed.
        """
        self.dirtied.emit()
    
    def setLinkPattern(self, programs, dirty=True):
        """ Set the rules to search for files based on file extensions, quotes, etc.
        
        :Parameters:
            programs : `dict`
                extension: program pairs of strings.
            dirty : `bool`
                If we should trigger a rehighlight or not.
        """
        # This is slightly different than the main program's RegEx because Qt doesn't support all the same things.
        # TODO: Not allowing a backslash here might break Windows file paths if/when we try to support that. 
        self.ruleLink[0].setPattern(r'(?:[^\'"@()\t\n\r\f\v\\]*\.)(?:' + '|'.join(programs.keys()) + r')(?=(?:[\'")@]|\\\"))')
        if dirty:
            self.dirty()
    
    def setSyntaxHighlighting(self, enable, force=True):
        """ Enable/Disable syntax highlighting.
        If enabling, dirties the state of this highlighter so highlighting runs again.
        
        :Parameters:
            enable : `bool`
                Whether or not to enable syntax highlighting.
            force : `bool`
                Force re-enabling syntax highlighting even if it was already enabled.
                Allows force rehighlighting even if nothing has really changed.
        """
        if force or enable != self.enableSyntax:
            self.enableSyntax = enable
            self.rules = self.highlightingRules if enable else self.blankRules
            self.dirty()


class Highlighter(QtGui.QSyntaxHighlighter):
    masterClass = MasterHighlighter
    
    def __init__(self, parent=None, master=None):
        """ Syntax highlighter for an individual document in the app.
        
        :Parameters:
            parent : `QtCore.QObject`
                Can install to a `QTextEdit` or `QTextDocument` to apply highlighting.
            master : `MasterHighlighter` | None
                Master object containing shared highlighting rules.
        """
        super(Highlighter, self).__init__(parent)
        self.master = master or self.masterClass(self)
        self.findPhrase = None
        self.dirty = False
        
        # Connect this directly to self.rehighlight if we can ever manage to thread or speed that up.
        self.master.dirtied.connect(self.setDirty)
    
    def isDirty(self):
        return self.dirty
    
    def setDirty(self):
        self.dirty = True
    
    def highlightBlock(self, text):
        """ Override this method only if needed for a specific language. """
        # Really long lines like timeSamples in Crate files don't play nicely with RegEx.
        # Skip them for now.
        if len(text) > LINE_CHAR_LIMIT:
            # TODO: Do we need to reset the block state or anything else here?
            return
        
        # Reduce name lookups for speed, since this is one of the slowest parts of the app.
        setFormat = self.setFormat
        currentBlockState = self.currentBlockState
        setCurrentBlockState = self.setCurrentBlockState
        previousBlockState = self.previousBlockState

        for pattern, frmt in self.master.rules:
            i = pattern.indexIn(text)
            while i >= 0:
                # If we have a grouped match, only highlight that first group and not the chars before it.
                pos1 = pattern.pos(1)
                if pos1 != -1:
                    length = pattern.matchedLength() - (pos1 - i)
                    i = pos1
                else:
                    length = pattern.matchedLength()
                setFormat(i, length, frmt)
                i = pattern.indexIn(text, i + length)
        
        setCurrentBlockState(0)
        for state, (startExpr, endExpr, frmt) in enumerate(self.master.multilineRules, 1):
            if previousBlockState() == state:
                # We're already inside a match for this rule. See if there's an ending match.
                startIndex = 0
                add = 0
            else:
                # Look for the start of the expression.
                startIndex = startExpr.indexIn(text)
                # If we have a grouped match, only highlight that first group and not the chars before it.
                pos1 = startExpr.pos(1)
                if pos1 != -1:
                    add = startExpr.matchedLength() - (pos1 - startIndex)
                    startIndex = pos1
                else:
                    add = startExpr.matchedLength()
            
            # If we're inside the match, look for the end expression.
            while startIndex >= 0:
                endIndex = endExpr.indexIn(text, startIndex + add)
                if endIndex >= add:
                    # We found the end of the multiline rule.
                    length = endIndex - startIndex + add + endExpr.matchedLength()
                    # Since we're at the end of this rule, reset the state so other multiline rules can try to match.
                    setCurrentBlockState(0)
                else:
                    # Still inside the multiline rule.
                    length = len(text) - startIndex + add
                    setCurrentBlockState(state)
                
                # Highlight the portion of this line that's inside the multiline rule.
                # TODO: This doesn't actually ensure we hit the closing expression before highlighting.
                setFormat(startIndex, length, frmt)
                
                # Look for the next match.
                startIndex = startExpr.indexIn(text, startIndex + length)
                pos1 = startExpr.pos(1)
                if pos1 != -1:
                    add = startExpr.matchedLength() - (pos1 - startIndex)
                    startIndex = pos1
                else:
                    add = startExpr.matchedLength()
            
            if currentBlockState() == state:
                break
        
        self.dirty = False
