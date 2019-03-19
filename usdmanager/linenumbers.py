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
Line numbers widget for optimized display of line numbers on the left side of
a text widget.
"""
from Qt.QtCore import Slot
from Qt.QtWidgets import QFrame, QWidget
from Qt.QtGui import QFont, QPainter, QTextCharFormat


class LineNumbers(QWidget):
    """ Line number widget for `QTextBrowser` and `QTextEdit` widgets.
    Currently does not support `QPlainTextEdit` widgets.
    """
    def __init__(self, *args, **kwargs):
        super(LineNumbers, self).__init__(*args)

        self.textWidget = self.doc = None
        self.setTextWidget(kwargs.pop('widget', None))
        
        # Monospaced font to keep width from shifting.
        font = QFont()
        font.setStyleHint(QFont.Courier)
        font.setFamily("Monospace")
        self.setFont(font)
        
        self.updateAndResize()
    
    def connectSignals(self):
        """ Connect relevant `QTextBrowser` or `QTextEdit` signals.
        """
        self.textWidget.verticalScrollBar().valueChanged[int].connect(self.update)
        self.textWidget.currentCharFormatChanged[QTextCharFormat].connect(self.updateAndResize)
        self.textWidget.cursorPositionChanged.connect(self.update)
        self.textWidget.selectionChanged.connect(self.update)
        self.doc.blockCountChanged[int].connect(self.updateAndResize)
    
    def setTextWidget(self, widget):
        """ Set the current text widget.

        :Parameters:
            widget : `QTextBrowser` | `QTextEdit`
                The text widget that uses a QTextDocument
        """
        if widget is None:
            return
        self.textWidget = widget
        self.doc = self.textWidget.document()
        self.connectSignals()
    
    @Slot()
    @Slot(int)
    def update(self, *args):
        """ Just update. We know we don't need to resize with the signals that call this method.
        """
        super(LineNumbers, self).update()
    
    @Slot(int)
    @Slot(QTextCharFormat)
    def updateAndResize(self, *args):
        """ Resize bar if needed.
        """
        width = self.fontMetrics().width(str(self.doc.blockCount())) + 5
        if self.width() != width:
            self.setFixedWidth(width)
        super(LineNumbers, self).update()
    
    def paintEvent(self, event):
        """ Override the default paintEvent to add in line numbers.
        """
        vScrollPos = self.textWidget.verticalScrollBar().value()
        pageBtm = vScrollPos + self.textWidget.viewport().height()
        currBlock = self.doc.findBlock(self.textWidget.textCursor().position())
        
        fontMetric = self.fontMetrics()
        painter = QPainter(self)
        font = painter.font()
        
        # Find roughly the current top-most visible block.
        block = self.doc.begin()
        lineHeight = self.doc.documentLayout().blockBoundingRect(block).height()
        
        block = self.doc.findBlockByNumber(int(vScrollPos/lineHeight))
        currLine = block.blockNumber()
        
        while block.isValid():
            currLine += 1
            
            # Check if the position of the block is outside the visible area.
            yPos = self.doc.documentLayout().blockBoundingRect(block).topLeft().y()
            if yPos > pageBtm:
                break
            
            if block == currBlock:
                # Make the line number for the selected line bold.
                font.setBold(True)
                painter.setFont(font)
                # Draw the line number right justified at the y position of the line. 3 is a magic padding number.
                painter.drawText(self.width() - fontMetric.width(str(currLine)) - 3,
                                 round(yPos) - vScrollPos + fontMetric.ascent() + 3,
                                 str(currLine))
                font.setBold(False)
                painter.setFont(font)
            else:
                painter.drawText(self.width() - fontMetric.width(str(currLine)) - 3,
                                 round(yPos) - vScrollPos + fontMetric.ascent() + 3,
                                 str(currLine))
            
            # Go to the next block.
            block = block.next()
        
        painter.end()
        
        super(LineNumbers, self).paintEvent(event)
