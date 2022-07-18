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
from __future__ import division

from Qt import QtCore
from Qt.QtCore import QRect, QSize, Slot
from Qt.QtGui import QColor, QFont, QPainter, QTextCharFormat, QTextFormat
from Qt.QtWidgets import QTextEdit, QWidget

# Shadow round for Python 3 compatibility
from .utils import round as round


class PlainTextLineNumbers(QWidget):
    """ Line number widget for `QPlainTextEdit` widgets.
    """
    def __init__(self, parent):
        """ Initialize the line numbers widget.

        :Parameters:
            parent : `QPlainTextEdit`
                Text widget
        """
        super(PlainTextLineNumbers, self).__init__(parent)
        self.textWidget = parent
        self._hiddenByUser = False
        self._highlightCurrentLine = True
        self._movePos = None

        # Monospaced font to keep width from shifting.
        font = QFont()
        font.setStyleHint(QFont.Courier)
        font.setFamily("Monospace")
        self.setFont(font)

        self.connectSignals()
        self.updateLineWidth()
        self.highlightCurrentLine()

    def blockCount(self):
        return self.textWidget.blockCount()

    def connectSignals(self):
        """ Connect signals from the text widget that affect line numbers.
        """
        self.textWidget.blockCountChanged.connect(self.updateLineWidth)
        self.textWidget.updateRequest.connect(self.updateLineNumbers)
        self.textWidget.cursorPositionChanged.connect(self.highlightCurrentLine)

    @Slot()
    def highlightCurrentLine(self):
        """ Highlight the line the cursor is on.

        :Returns:
            If highlighting was enabled or not.
        :Rtype:
            `bool`
        """
        if not self._highlightCurrentLine:
            return False

        extras = [x for x in self.textWidget.extraSelections() if x.format.property(QTextFormat.UserProperty) != "line"]
        selection = QTextEdit.ExtraSelection()
        lineColor = QColor(QtCore.Qt.darkGray).darker() if self.window().isDarkTheme() else \
                    QColor(QtCore.Qt.yellow).lighter(180)
        selection.format.setBackground(lineColor)
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.format.setProperty(QTextFormat.UserProperty, "line")
        selection.cursor = self.textWidget.textCursor()
        selection.cursor.clearSelection()
        # Put at the beginning of the list so we preserve any highlighting from Find's highlight all functionality.
        extras.insert(0, selection)
        '''
        if self.window().buttonHighlightAll.isChecked() and self.window().findBar.text():
            selection = QTextEdit.ExtraSelection()
            lineColor = QColor(QtCore.Qt.yellow)
            selection.format.setBackground(lineColor)
            selection.cursor = QtGui.QTextCursor(self.textWidget.document())
            selection.find(self.window().findBar.text())
        '''
        self.textWidget.setExtraSelections(extras)
        return True

    def lineWidth(self, count=0):
        """ Calculate the width of the widget based on the block count.

        :Parameters:
            count : `int`
                Block count. Defaults to current block count.
        """
        if self._hiddenByUser:
            return 0
        blocks = str(count or self.blockCount())
        try:
            # horizontalAdvance added in Qt 5.11.
            return 6 + self.fontMetrics().horizontalAdvance(blocks)
        except AttributeError:
            # Obsolete in Qt 5.
            return 6 + self.fontMetrics().width(blocks)

    def mouseMoveEvent(self, event):
        """ Track mouse movement to select more lines if press is active.

        :Parameters:
            event : `QMouseEvent`
                Mouse move event
        """
        if event.buttons() != QtCore.Qt.LeftButton:
            event.accept()
            return

        cursor = self.textWidget.textCursor()
        cursor2 = self.textWidget.cursorForPosition(event.pos())
        new = cursor2.position()
        if new == self._movePos:
            event.accept()
            return

        cursor.setPosition(self._movePos)
        if new > self._movePos:
            cursor.movePosition(cursor.StartOfLine)
            cursor2.movePosition(cursor2.EndOfLine)
        else:
            cursor.movePosition(cursor.EndOfLine)
            cursor2.movePosition(cursor2.StartOfLine)
        cursor.setPosition(cursor2.position(), cursor.KeepAnchor)
        self.textWidget.setTextCursor(cursor)
        event.accept()

    def mousePressEvent(self, event):
        """ Select the line that was clicked. If moved while pressed, select
        multiple lines as the mouse moves.

        :Parameters:
            event : `QMouseEvent`
                Mouse press event
        """
        if event.buttons() != QtCore.Qt.LeftButton:
            event.accept()
            return

        cursor = self.textWidget.cursorForPosition(event.pos())
        cursor.select(cursor.LineUnderCursor)

        # Allow Shift-selecting lines from the previous selection to new position.
        if self.textWidget.textCursor().hasSelection() and event.modifiers() == QtCore.Qt.ShiftModifier:
            cursor2 = self.textWidget.textCursor()
            self._movePos = cursor2.position()
            start = min(cursor.selectionStart(), cursor2.selectionStart())
            end = max(cursor.selectionEnd(), cursor2.selectionEnd())
            cursor.setPosition(start)
            cursor.setPosition(end, cursor.KeepAnchor)
        else:
            self._movePos = cursor.position()

        self.textWidget.setTextCursor(cursor)
        event.accept()

    def onEditorResize(self):
        """ Adjust line numbers size if the text widget is resized.
        """
        cr = self.textWidget.contentsRect()
        self.setGeometry(QRect(cr.left(), cr.top(), self.lineWidth(), cr.height()))

    def paintEvent(self, event):
        """ Draw the visible line numbers.
        """
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor(QtCore.Qt.darkGray).darker(300) if self.window().isDarkTheme() \
                         else QtCore.Qt.lightGray)

        textWidget = self.textWidget
        currBlock = textWidget.document().findBlock(textWidget.textCursor().position())

        block = textWidget.firstVisibleBlock()
        blockNumber = block.blockNumber() + 1
        geo = textWidget.blockBoundingGeometry(block).translated(textWidget.contentOffset())
        top = round(geo.top())
        bottom = round(geo.bottom())
        width = self.width() - 3  # 3 is magic padding number
        height = round(geo.height())
        flags = QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        font = painter.font()

        # Shrink the line numbers if we zoom out so numbers don't overlap, but don't increase the size, since we don't
        # (yet) account for that in this widget's width, leading to larger numbers cutting off the leading digits.
        size = max(1, min(width, height - 3))
        if size < font.pointSize():
            font.setPointSize(size)

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                # Make the line number for the selected line bold.
                font.setBold(block == currBlock)
                painter.setFont(font)
                painter.drawText(0, top, width, height, flags, str(blockNumber))

            block = block.next()
            top = bottom
            bottom = top + round(textWidget.blockBoundingRect(block).height())
            blockNumber += 1

    def setVisible(self, visible):
        super(PlainTextLineNumbers, self).setVisible(visible)
        self._hiddenByUser = not visible
        self.updateLineWidth()

    def sizeHint(self):
        return QSize(self.lineWidth(), self.textWidget.height())

    @Slot(QRect, int)
    def updateLineNumbers(self, rect, dY):
        """ Scroll the line numbers or repaint the visible numbers.
        """
        if dY:
            self.scroll(0, dY)
        else:
            self.update(0, rect.y(), self.width(), rect.height())
        if rect.contains(self.textWidget.viewport().rect()):
            self.updateLineWidth()

    @Slot(int)
    def updateLineWidth(self, count=0):
        """ Adjust display of text widget to account for the widget of the line numbers.

        :Parameters:
            count : `int`
                Block count of document.
        """
        self.textWidget.setViewportMargins(self.lineWidth(count), 0, 0, 0)


class LineNumbers(PlainTextLineNumbers):
    """ Line number widget for `QTextBrowser` and `QTextEdit` widgets.
    Currently does not support `QPlainTextEdit` widgets.
    """
    def blockCount(self):
        return self.textWidget.document().blockCount()

    def connectSignals(self):
        """ Connect relevant `QTextBrowser` or `QTextEdit` signals.
        """
        self.doc = self.textWidget.document()
        self.textWidget.verticalScrollBar().valueChanged.connect(self.update)
        self.textWidget.currentCharFormatChanged.connect(self.resizeAndUpdate)
        self.textWidget.cursorPositionChanged.connect(self.highlightCurrentLine)
        self.doc.blockCountChanged.connect(self.updateLineWidth)

    @Slot()
    def highlightCurrentLine(self):
        """ Make sure the active line number is redrawn in bold by calling update.
        """
        if super(LineNumbers, self).highlightCurrentLine():
            self.update()

    @Slot(QTextCharFormat)
    def resizeAndUpdate(self, *args):
        """ Resize bar if needed.
        """
        self.updateLineWidth()
        super(LineNumbers, self).update()

    def paintEvent(self, event):
        """ Draw line numbers.
        """
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor(QtCore.Qt.darkGray).darker(300) if self.window().isDarkTheme() \
                         else QtCore.Qt.lightGray)

        textWidget = self.textWidget
        doc = textWidget.document()
        vScrollPos = textWidget.verticalScrollBar().value()
        pageBtm = vScrollPos + textWidget.viewport().height()
        currBlock = doc.findBlock(textWidget.textCursor().position())

        width = self.width() - 3  # 3 is magic padding number
        height = textWidget.fontMetrics().height()
        flags = QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        font = painter.font()

        # Shrink the line numbers if we zoom out so numbers don't overlap, but don't increase the size, since we don't
        # (yet) account for that in this widget's width, leading to larger numbers cutting off the leading digits.
        size = max(1, min(width, height - 3))
        if size < font.pointSize():
            font.setPointSize(size)

        # Find roughly the current top-most visible block.
        block = doc.begin()
        layout = doc.documentLayout()
        lineHeight = layout.blockBoundingRect(block).height()

        block = doc.findBlockByNumber(int(vScrollPos / lineHeight))
        currLine = block.blockNumber()

        while block.isValid():
            currLine += 1

            # Check if the position of the block is outside the visible area.
            yPos = layout.blockBoundingRect(block).topLeft().y()
            if yPos > pageBtm:
                break

            # Make the line number for the selected line bold.
            font.setBold(block == currBlock)
            painter.setFont(font)
            painter.drawText(0, yPos - vScrollPos, width, height, flags, str(currLine))

            # Go to the next block.
            block = block.next()
