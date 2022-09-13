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

""" Create a Preferences dialog.
"""

from Qt.QtCore import Slot, QRegExp
from Qt.QtGui import QRegExpValidator
from Qt.QtWidgets import QAbstractButton, QDialog, QDialogButtonBox, QFontDialog, QLineEdit, QMessageBox, QVBoxLayout

from .constants import LINE_LIMIT
from .utils import icon, loadUiWidget


class PreferencesDialog(QDialog):
    """
    Preferences dialog
    """
    def __init__(self, parent, **kwargs):
        """ Initialize the dialog.

        :Parameters:
            parent : `UsdMngrWindow`
                Main window
        """
        super(PreferencesDialog, self).__init__(parent, **kwargs)

        self.docFont = parent.tabWidget.font()
        self.fileAssociations = {}
        self.lineEditProgs = []
        self.lineEditExts = []

        self.setupUi()
        self.connectSignals()

    def setupUi(self):
        """ Creates and lays out the widgets defined in the ui file.
        """
        self.baseInstance = loadUiWidget("preferences_dialog.ui", self)
        self.setWindowIcon(icon("preferences-system"))
        self.buttonFont.setIcon(icon("preferences-desktop-font"))
        self.buttonNewProg.setIcon(icon("list-add"))

        # ----- General tab -----
        # Set initial preferences.
        parent = self.parent()
        self.checkBox_parseLinks.setChecked(parent.preferences['parseLinks'])
        self.checkBox_newTab.setChecked(parent.preferences['newTab'])
        self.checkBox_syntaxHighlighting.setChecked(parent.preferences['syntaxHighlighting'])
        self.checkBox_teletypeConversion.setChecked(parent.preferences['teletype'])
        self.checkBox_lineNumbers.setChecked(parent.preferences['lineNumbers'])
        self.checkBox_showAllMessages.setChecked(parent.preferences['showAllMessages'])
        self.checkBox_showHiddenFiles.setChecked(parent.preferences['showHiddenFiles'])
        self.checkBox_autoCompleteAddressBar.setChecked(parent.preferences['autoCompleteAddressBar'])
        self.useSpacesCheckBox.setChecked(parent.preferences['useSpaces'])
        self.useSpacesSpinBox.setValue(parent.preferences['tabSpaces'])
        self.lineEditTextEditor.setText(parent.preferences['textEditor'])
        self.lineEditDiffTool.setText(parent.preferences['diffTool'])
        self.themeWidget.setChecked(parent.preferences['theme'] == "dark")
        self.lineLimitSpinBox.setValue(parent.preferences['lineLimit'])
        self.checkBox_autoIndent.setChecked(parent.preferences['autoIndent'])
        self.updateFontLabel()

        # ----- Programs tab -----
        self.progLayout = QVBoxLayout()
        self.extLayout = QVBoxLayout()

        # Extensions can only be: <optional .><alphanumeric><optional comma><optional space>
        #self.progValidator = QRegExpValidator(QRegExp("[\w,. ]+"), self)
        self.extValidator = QRegExpValidator(QRegExp(r"(?:\.?\w*,?\s*)+"), self)
        self.lineEdit.setValidator(self.extValidator)

        # Create the fields for programs and extensions.
        self.populateProgsAndExts(parent.programs)

    def connectSignals(self):
        """ Connect signals to slots.
        """
        self.buttonBox.clicked.connect(self.restoreDefaults)
        self.buttonNewProg.clicked.connect(self.newProgField)
        self.buttonBox.accepted.connect(self.validate)
        self.buttonFont.clicked.connect(self.selectFont)

    def deleteItems(self, layout):
        """ Delete all items in given layout.

        :Parameters:
            layout : `QLayout`
                Layout to delete items from
        """
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                else:
                    self.deleteItems(item.layout())

    def getPrefFont(self):
        """ Get the user preference for font.

        :Returns:
            Font selected for documents.
        :Rtype:
            `QFont`
        """
        return self.docFont

    def getPrefLineNumbers(self):
        """ Get the user preference for displaying line numbers.

        :Returns:
            State of "Show line numbers" check box.
        :Rtype:
            `bool`
        """
        return self.checkBox_lineNumbers.isChecked()

    def getPrefNewTab(self):
        """ Get the user preference for opening links in a new tab or not.

        :Returns:
            State of "Open links in new tabs" check box.
        :Rtype:
            `bool`
        """
        return self.checkBox_newTab.isChecked()

    def getPrefParseLinks(self):
        """ Get the user preference to enable link parsing.

        :Returns:
            Search for links in the opened file.
            Disable this for huge files that freeze the app.

        :Rtype:
            `bool`
        """
        return self.checkBox_parseLinks.isChecked()

    def getPrefPrograms(self):
        """ Get the user preference for file extensions and apps to open them with.

        :Returns:
            Dictionary of extension: program pairs of strings.
        :Rtype:
            `dict`
        """
        return self.fileAssociations

    def getPrefShowAllMessages(self):
        """ Get the user preference to display all messages or just errors.

        :Returns:
            State of "Show success messages" check box.
        :Rtype:
            `bool`
        """
        return self.checkBox_showAllMessages.isChecked()

    def getPrefShowHiddenFiles(self):
        """ Get the user preference for showing hidden files by default.

        :Returns:
            State of "Show hidden files" check box.
        :Rtype:
            `bool`
        """
        return self.checkBox_showHiddenFiles.isChecked()

    def getPrefAutoCompleteAddressBar(self):
        """ Get the user preference for enabling address bar auto-completion.

        :Returns:
            State of "Auto complete paths in address bar" check box.
        :Rtype:
            `bool`
        """
        return self.checkBox_autoCompleteAddressBar.isChecked()

    def getPrefLineLimit(self):
        """ Get the user preference for line limit before truncating files.

        :Returns:
            Number of lines to display before truncating a file.
        :Rtype:
            `int`
        """
        return self.lineLimitSpinBox.value()

    def getPrefSyntaxHighlighting(self):
        """ Get the user preference to enable syntax highlighting.

        :Returns:
            State of "Enable syntax highlighting" check box.
        :Rtype:
            `bool`
        """
        return self.checkBox_syntaxHighlighting.isChecked()

    def getPrefTeletypeConversion(self):
        """ Get the user preference to enable teletype character conversion.

        :Returns:
            State of "Display teletype colors" check box.
        :Rtype:
            `bool`
        """
        return self.checkBox_teletypeConversion.isChecked()

    def getPrefTextEditor(self):
        """ Get the user-preferred text editor.

        :Returns:
            Text in Text editor QTextEdit.
        :Rtype:
            `str`
        """
        return self.lineEditTextEditor.text()

    def getPrefTheme(self):
        """ Get the selected theme.

        We may eventually make this a combo box supporting multiple themes,
        so use the string name instead of just a boolean.

        :Returns:
            Selected theme name, or None if the default
        :Rtype:
            `str` | None
        """
        return "dark" if self.themeWidget.isChecked() else None

    def getPrefUseSpaces(self):
        """ Get the user preference for spaces vs. tabs.

        :Returns:
            State of "Use spaces instead of tabs" check box.
        :Rtype:
            `bool`
        """
        return self.useSpacesCheckBox.isChecked()

    def getPrefTabSpaces(self):
        """ Get the user preference for number of spaces equaling a tab.

        :Returns:
            Number of spaces to use instead of a tab.
            Only use this number of use spaces is also True.
        :Rtype:
            `int`
        """
        return self.useSpacesSpinBox.value()

    def getPrefAutoIndent(self):
        """ Get the user preference for auto-indentation.

        :Returns:
            State of "Use auto indentation" check box.
        :Rtype:
            `bool`
        """
        return self.checkBox_autoIndent.isChecked()

    def getPrefDiffTool(self):
        """ Get the user preference for diff tool.

        :Returns:
            Text in Diff tool QTextEdit.
        :Rtype:
            `str`
        """
        return self.lineEditDiffTool.text()

    @Slot(bool)
    def newProgField(self, *args):
        """ Add a new line to the programs list.
        """
        self.lineEditProgs.append(QLineEdit(self))
        self.progLayout.addWidget(self.lineEditProgs[len(self.lineEditProgs)-1])
        self.lineEditExts.append(QLineEdit(self))
        self.extLayout.addWidget(self.lineEditExts[len(self.lineEditExts)-1])

    def populateProgsAndExts(self, programs):
        """ Fill out the UI with the user preference for programs and extensions.

        :Parameters:
            programs : `dict`
                Dictionary of extension: program pairs of strings.
        """
        self.lineEditProgs = []
        self.lineEditExts = []

        # Get unique programs.
        tmpSet = set()
        progs = [x for x in programs.values() if x not in tmpSet and not tmpSet.add(x)]
        del tmpSet
        progs.sort()

        # Get extensions per program.
        exts = []
        for prog in progs:
            # Find each extension matching this program.
            progExts = ["."+x for x in programs if programs[x] == prog]
            progExts.sort()
            # Format in comma-separated list for display.
            exts.append(", ".join(progExts))

        # Put the files that should open with this app in their own place.
        # Then remove them from these lists.
        index = progs.index("")
        progs.pop(index)
        self.lineEdit.setText(exts[index])
        exts.pop(index)
        del index

        for i, prog in enumerate(progs):
            # Create and populate two QLineEdit objects per extension: program pair.
            self.lineEditProgs.append(QLineEdit(prog, self))
            #self.lineEditProgs[i].setValidator(self.progValidator)
            self.progLayout.addWidget(self.lineEditProgs[i])
            self.lineEditExts.append(QLineEdit(exts[i], self))
            self.lineEditExts[i].setValidator(self.extValidator)
            self.extLayout.addWidget(self.lineEditExts[i])
        self.progWidget.setLayout(self.progLayout)
        self.extWidget.setLayout(self.extLayout)

    @Slot(QAbstractButton)
    def restoreDefaults(self, btn):
        """ Restore the GUI to the program's default settings.
        Don't update the actual preferences (that happens if OK is pressed).
        """
        if btn == self.buttonBox.button(QDialogButtonBox.RestoreDefaults):
            # Delete old QLineEdit objects.
            self.deleteItems(self.progLayout)
            self.deleteItems(self.extLayout)

            # Set other preferences in the GUI.
            default = self.parent().window().app.DEFAULTS
            self.checkBox_parseLinks.setChecked(default['parseLinks'])
            self.checkBox_newTab.setChecked(default['newTab'])
            self.checkBox_syntaxHighlighting.setChecked(default['syntaxHighlighting'])
            self.checkBox_teletypeConversion.setChecked(default['teletype'])
            self.checkBox_lineNumbers.setChecked(default['lineNumbers'])
            self.checkBox_showAllMessages.setChecked(default['showAllMessages'])
            self.checkBox_showHiddenFiles.setChecked(default['showHiddenFiles'])
            self.checkBox_autoCompleteAddressBar.setChecked(default['autoCompleteAddressBar'])
            self.lineEditTextEditor.setText(default['textEditor'])
            self.lineEditDiffTool.setText(default['diffTool'])
            self.useSpacesCheckBox.setChecked(default['useSpaces'])
            self.useSpacesSpinBox.setValue(default['tabSpaces'])
            self.themeWidget.setChecked(False)
            self.docFont = default['font']
            self.updateFontLabel()
            self.lineLimitSpinBox.setValue(default['lineLimit'])
            self.checkBox_autoIndent.setChecked(default['autoIndent'])

            # Re-create file association fields with the default programs.
            self.populateProgsAndExts(self.parent().defaultPrograms)

    @Slot(bool)
    def selectFont(self, *args):
        """ Update the user's font preference.
        """
        font, ok = QFontDialog.getFont(self.docFont, self, "Select Font")
        if ok:
            self.docFont = font
            self.updateFontLabel()

    def updateFontLabel(self):
        """ Update the UI font label to show the user's selected font.
        """
        bold = "Bold " if self.docFont.bold() else ""
        italic = "Italic " if self.docFont.italic() else ""
        self.labelFont.setText("Document font: {}pt {}{}{}".format(self.docFont.pointSize(), bold, italic,
                                                                   self.docFont.family()))

    @Slot()
    def validate(self):
        """ Make sure everything has valid input.
        Make sure there are no duplicate extensions.
        Accepts or rejects accepted() signal accordingly.
        """
        for lineEdit in self.lineEditExts:
            if lineEdit.hasAcceptableInput():
                lineEdit.setStyleSheet("background-color:none")
            else:
                lineEdit.setStyleSheet("background-color:salmon")
                QMessageBox.warning(self, "Warning", "One or more extension is invalid.")
                return

        # Get file extensions for this app to handle.
        extText = self.lineEdit.text()
        # Strip out periods and spaces.
        extText = extText.replace(' ', '').replace('.', '')
        progList = [[x, ""] for x in extText.split(',') if x]

        for i in range(len(self.lineEditProgs)):
            extText = self.lineEditExts[i].text()
            progText = self.lineEditProgs[i].text()
            extText = extText.replace(' ', '').replace('.', '')
            for ext in extText.split(','):
                if ext:
                    progList.append([ext, progText])

        # Make sure there aren't any duplicate extensions.
        tmpSet = set()
        uniqueExt = [ext for ext, prog in progList if ext not in tmpSet and not tmpSet.add(ext)]
        if len(uniqueExt) == len(progList):
            self.fileAssociations = dict(progList)
        else:
            QMessageBox.warning(self, "Warning", "You have entered the same extension for two or more programs.")
            return

        # Accept if we made it this far.
        self.accept()
