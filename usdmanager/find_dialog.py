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
""" Create the Find or Find/Replace dialog.
"""
from Qt.QtCore import Slot
from Qt.QtWidgets import QDialog, QStatusBar
from Qt.QtGui import QTextDocument

from .utils import icon, loadUiWidget


class FindDialog(QDialog):
    """
    Find/Replace dialog
    """
    def __init__(self, parent=None, **kwargs):
        """ Initialize the dialog.

        :Parameters:
            parent : `QtWidgets.QWidget` | None
                Parent widget
        """
        super(FindDialog, self).__init__(parent, **kwargs)
        self.setupUi()
        self.connectSignals()

    def setupUi(self):
        """ Creates and lays out the widgets defined in the ui file.
        """
        self.baseInstance = loadUiWidget('find_dialog.ui', self)
        self.statusBar = QStatusBar(self)
        self.verticalLayout.addWidget(self.statusBar)
        self.findBtn.setIcon(icon("edit-find"))
        self.replaceBtn.setIcon(icon("edit-find-replace"))

    def connectSignals(self):
        """ Connect signals to slots.
        """
        self.findLineEdit.textChanged.connect(self.updateButtons)

    def searchFlags(self):
        """ Get find flags based on checked options.

        :Returns:
            Find flags
        :Rtype:
            `QTextDocument.FindFlags`
        """
        flags = QTextDocument.FindFlags()
        if self.caseSensitiveCheck.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        if self.wholeWordsCheck.isChecked():
            flags |= QTextDocument.FindWholeWords
        if self.searchBackwardsCheck.isChecked():
            flags |= QTextDocument.FindBackward
        return flags

    @Slot(str)
    def updateButtons(self, text):
        """
        Update enabled state of buttons as entered text changes.

        :Parameters:
            text : `str`
                Currently entered find text
        """
        enabled = bool(text)
        self.findBtn.setEnabled(enabled)
        self.replaceBtn.setEnabled(enabled)
        self.replaceFindBtn.setEnabled(enabled)
        self.replaceAllBtn.setEnabled(enabled)
        self.replaceAllOpenBtn.setEnabled(enabled)
        if not enabled:
            self.statusBar.clearMessage()
            self.setStyleSheet("QLineEdit#findLineEdit{background:none}")

    @Slot(bool)
    def updateForEditMode(self, edit):
        """
        Show/Hide text replacement options based on if we are editing or not.
        If editing, allow replacement of the found text.

        :Parameters:
            edit : `bool`
                If in edit mode or not
        """
        self.replaceLabel.setVisible(edit)
        self.replaceLineEdit.setVisible(edit)
        self.replaceBtn.setVisible(edit)
        self.replaceFindBtn.setVisible(edit)
        self.replaceAllBtn.setVisible(edit)
        self.replaceAllOpenBtn.setVisible(edit)
        self.buttonBox.setVisible(edit)
        self.buttonBox2.setVisible(not edit)
        if edit:
            self.setWindowTitle("Find/Replace")
            self.setWindowIcon(icon("edit-find-replace"))
        else:
            self.setWindowTitle("Find")
            self.setWindowIcon(icon("edit-find"))
