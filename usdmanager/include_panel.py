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
""" Left-hand side file browser.
"""
import os

from Qt import QtCore, QtWidgets
from Qt.QtCore import Signal, Slot

from .utils import expandPath, icon, overrideCursor


class IncludePanel(QtWidgets.QWidget):
    """
    File browsing panel for the left side of the main UI.
    """
    openFile = Signal(str)
    
    def __init__(self, path="", filter="", selectedFilter="", parent=None):
        """ Initialize the panel.
        
        :Parameters:
            path : `str`
                default path to look in when creating or choosing the file.
            filter : `list`
                A list of strings denoting filename match filters. These strings
                are displayed in a user-selectable combobox. When selected,
                the file list is filtered by the pattern
                The format must follow:
                ["Descriptive text (pattern1  pattern2  ...)", ...]
                The glob matching pattern is in parens, and the entire string is
                displayed for the user.
            selectedFilter : `str`
                Set the current filename filter. Needs to be one of the entries
                specified in the "filter" parameter.
            parent : `QObject`
                Parent for this widget.
        """
        super(IncludePanel, self).__init__(parent)
        
        # Setup UI.
        self.lookInCombo = QtWidgets.QComboBox(self)
        self.toParentButton = QtWidgets.QToolButton(self)
        self.buttonHome = QtWidgets.QToolButton(self)
        self.buttonOriginal = QtWidgets.QPushButton("Original", self)
        self.fileNameEdit = QtWidgets.QLineEdit(self)
        self.fileNameLabel = QtWidgets.QLabel("File:", self)
        self.fileTypeCombo = QtWidgets.QComboBox(self)
        self.fileTypeLabel = QtWidgets.QLabel("Type:", self)
        self.stackedWidget = QtWidgets.QStackedWidget(self)
        self.listView = QtWidgets.QListView(self)
        self.fileTypeLabelFiller = QtWidgets.QLabel(self)
        self.fileTypeComboFiller = QtWidgets.QLabel(self)
        self.buttonOpen = QtWidgets.QPushButton(icon("document-open"), "Open", self)
        self.buttonOpen.setEnabled(False)
        
        # Item settings.
        self.buttonHome.setIcon(icon("folder-home", self.style().standardIcon(QtWidgets.QStyle.SP_DirHomeIcon)))
        self.buttonHome.setToolTip("User's home directory")
        self.buttonHome.setAutoRaise(True)
        self.buttonOriginal.setToolTip("Original directory")
        self.lookInCombo.setMinimumSize(50, 0)
        self.toParentButton.setIcon(icon("folder-up", self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogToParent)))
        self.toParentButton.setAutoRaise(True)
        self.toParentButton.setToolTip("Parent directory")
        self.listView.setDragEnabled(True)
        self.fileNameLabel.setToolTip("Selected file or directory")
        self.fileTypeLabel.setBuddy(self.fileTypeCombo)
        self.fileTypeLabel.setToolTip("File type filter")
        self.buttonOpen.setToolTip("Open selected file")
        
        # Focus policies.
        self.lookInCombo.setFocusPolicy(QtCore.Qt.NoFocus)
        self.toParentButton.setFocusPolicy(QtCore.Qt.NoFocus)
        self.buttonHome.setFocusPolicy(QtCore.Qt.NoFocus)
        self.buttonOriginal.setFocusPolicy(QtCore.Qt.NoFocus)
        self.buttonOpen.setFocusPolicy(QtCore.Qt.NoFocus)
        
        # Item size policies.
        self.lookInCombo.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.toParentButton.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.buttonHome.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.buttonOriginal.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.fileNameLabel.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.fileTypeCombo.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.fileTypeLabel.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.buttonOpen.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        
        # Layouts.
        self.include1Layout = QtWidgets.QHBoxLayout()
        self.include1Layout.setContentsMargins(0, 0, 0, 0)
        self.include1Layout.setSpacing(5)
        self.include1Layout.addWidget(self.buttonHome)
        self.include1Layout.addWidget(self.lookInCombo)
        self.include1Layout.addWidget(self.toParentButton)
        
        self.include2Layout = QtWidgets.QHBoxLayout()
        self.include2Layout.setContentsMargins(0, 0, 0, 0)
        self.include2Layout.setSpacing(5)
        self.include2Layout.addWidget(self.stackedWidget)
        
        self.include4Layout = QtWidgets.QGridLayout()
        self.include4Layout.setContentsMargins(0, 0, 0, 0)
        self.include4Layout.setSpacing(5)
        self.include4Layout.addWidget(self.fileNameLabel, 0, 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.include4Layout.addWidget(self.fileNameEdit, 0, 1)
        self.include4Layout.addWidget(self.fileTypeLabel, 1, 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.include4Layout.addWidget(self.fileTypeCombo, 1, 1)
        self.include4Layout.addWidget(self.fileTypeLabelFiller, 2, 0)
        self.include4Layout.addWidget(self.fileTypeComboFiller, 2, 1)
        
        self.include5Layout = QtWidgets.QHBoxLayout()
        self.include5Layout.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.include5Layout.setContentsMargins(0, 0, 0, 0)
        self.include5Layout.setSpacing(5)
        self.include5Layout.addWidget(self.buttonOriginal)
        spacer = QtWidgets.QSpacerItem(5, 0, QtWidgets.QSizePolicy.MinimumExpanding)
        self.include5Layout.addSpacerItem(spacer)
        self.include5Layout.addWidget(self.buttonOpen)
        
        self.includeLayout = QtWidgets.QVBoxLayout()
        self.includeLayout.setContentsMargins(0, 0, 0, 0)
        self.includeLayout.setSpacing(5)
        self.includeLayout.addLayout(self.include1Layout)
        self.includeLayout.addLayout(self.include2Layout)
        self.includeLayout.addLayout(self.include4Layout)
        line1 = QtWidgets.QFrame()
        line1.setFrameStyle(QtWidgets.QFrame.HLine | QtWidgets.QFrame.Sunken)
        self.includeLayout.addWidget(line1)
        self.includeLayout.addLayout(self.include5Layout)
        
        self.setLayout(self.includeLayout)
        self.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        
        self.buttonHome.clicked.connect(self.onHome)
        self.buttonOriginal.clicked.connect(self.onOriginal)
        self.lookInCombo.activated[int].connect(self.onPathComboChanged)
        self.fileTypeCombo.activated[int].connect(self._useNameFilter)
        
        self.fileModel = QtWidgets.QFileSystemModel(parent)
        self.fileModel.setReadOnly(True)
        self.fileModel.setNameFilterDisables(False)
        self.fileModel.setResolveSymlinks(True)
        self.fileModel.rootPathChanged.connect(self.pathChanged)
        
        self.listView.setModel(self.fileModel)
        
        self.listView.activated[QtCore.QModelIndex].connect(self.enterDirectory)
        
        # Set selection mode and behavior.
        self.listView.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.listView.setWrapping(False)
        self.listView.setResizeMode(QtWidgets.QListView.Adjust)
        
        selectionMode = QtWidgets.QAbstractItemView.SingleSelection
        self.listView.setSelectionMode(selectionMode)
        
        # Setup the completer.
        completer = QtWidgets.QCompleter(self.fileModel, self.fileNameEdit)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.fileNameEdit.setCompleter(completer)
        self.fileNameEdit.textChanged.connect(self.autoCompleteFileName)
        self.fileNameEdit.returnPressed.connect(self.accept)
        
        pathFile = None
        if not path:
            self.__path = os.getcwd()
        elif os.path.isfile(path):
            self.__path, pathFile = os.path.split(path)
        else:
            self.__path = path
        
        self.setPath(self.__path)
        
        if filter:
            self.setNameFilters(filter)
        
        if selectedFilter:
            self.selectNameFilter(selectedFilter)
        
        self.listPage = QtWidgets.QWidget(self.stackedWidget)
        self.stackedWidget.addWidget(self.listPage)
        listLayout = QtWidgets.QGridLayout(self.listPage)
        #listLayout.setMargin(0)
        listLayout.setContentsMargins(0, 0, 0, 0)
        listLayout.addWidget(self.listView, 0, 0, 1, 1)
        
        self.fileTypeLabelFiller.hide()
        self.fileTypeComboFiller.hide()

        # Selections
        selections = self.listView.selectionModel()
        selections.selectionChanged.connect(self.fileSelectionChanged)

        if pathFile is not None:
            idx = self.fileModel.index(self.fileModel.rootPath() + QtCore.QDir.separator() + pathFile)
            self.select(idx)
            self.fileNameEdit.setText(pathFile)
        
        # Connect signals.
        self.toParentButton.clicked.connect(self.onUp)
        self.buttonOpen.clicked.connect(self.accept)
        
        self.listView.scheduleDelayedItemsLayout()
        self.stackedWidget.setCurrentWidget(self.listPage)
        self.fileNameEdit.setFocus()
    
    def setNameFilters(self, filters):
        self._nameFilters = filters

        self.fileTypeCombo.clear()
        if len(self._nameFilters) == 0:
            return
        for filter in self._nameFilters:
            self.fileTypeCombo.addItem(filter)
        self.selectNameFilter(filters[0])
    
    def selectNameFilter(self, filter):
        i = self.fileTypeCombo.findText(filter)
        if i >= 0:
            self.fileTypeCombo.setCurrentIndex(i)
            self._useNameFilter(i)
    
    @Slot(int)
    def _useNameFilter(self, index):
        filter = self.fileTypeCombo.itemText(index)
        filter = [f.strip() for f in filter.split(" (", 1)[1][:-1].split(" ")]
        self.fileModel.setNameFilters(filter)
    
    def setDirectory(self, directory):
        with overrideCursor():
            directory = str(directory) # it may be a ResolvedPath; convert to str
            if not (directory.endswith('/') or directory.endswith('\\')):
                directory += '/'
            self.fileNameEdit.completer().setCompletionPrefix(directory)
            root = self.fileModel.setRootPath(directory)
            self.listView.setRootIndex(root)
            self.fileNameEdit.setText('')
            self.fileNameEdit.clear()
            self.listView.selectionModel().clear()
    
    @Slot(str)
    def pathChanged(self, path):
        pass
    
    @Slot(QtCore.QModelIndex)
    def enterDirectory(self, index):
        fname = str(index.data(QtWidgets.QFileSystemModel.FileNameRole))
        isDirectory = self.fileModel.isDir(index)
        if isDirectory:
            self.appendToPath(fname, isDirectory)
        else:
            self.accept()
    
    def showAll(self, checked):
        """ Show hidden files
        
        :Parameters:
            checked : `bool`
                If True, show hidden files
        """
        dirFilters = self.fileModel.filter()
        if checked:
            dirFilters |= QtCore.QDir.Hidden
        else:
            dirFilters &= ~QtCore.QDir.Hidden
        self.fileModel.setFilter(dirFilters)
    
    @Slot(bool)
    def onUp(self, *args):
        path = os.path.abspath(self.path)
        if not os.path.isdir(path):
            path = os.path.dirname(path)
        dirName = os.path.dirname(path)
        self.setPath(dirName)
    
    @Slot(bool)
    def onHome(self, *args):
        self.setPath(QtCore.QDir.homePath())
        self.setFileDisplay()
    
    @Slot(bool)
    def onOriginal(self, *args):
        self.setPath(self.__path)
        self.setFileDisplay()
    
    @Slot(int)
    def onPathComboChanged(self, index):
        self.setPath(str(self.lookInCombo.itemData(index)))
    
    def setPath(self, path):
        self.setDirectory(expandPath(path))
        self.path = path
        self.lookInCombo.clear()
        p = path
        dirs = []
        while True:
            p1, p2 = os.path.split(p)
            if not p2:
                break
            dirs.insert(0, (p2, p))
            p = p1
        for d, dp in dirs:
            self.lookInCombo.addItem("%s%s" % (self.lookInCombo.count()*"  ", d), dp)
        self.lookInCombo.setCurrentIndex(self.lookInCombo.count() - 1)
    
    def appendToPath(self, filename, isDirectory):
        """
        :Parameters:
            filename : `str`
            isDirectory : `bool`
        """
        self.path = os.path.join(self.path, filename)
        if isDirectory:
            self.setDirectory(expandPath(self.path))
            self.lookInCombo.addItem("%s%s" % (self.lookInCombo.count()*"  ", filename), self.path)
            self.lookInCombo.setCurrentIndex(self.lookInCombo.count() - 1)
        return self.path
    
    def getPath(self):
        return self.path
    
    def setFileDisplay(self):
        self.stackedWidget.setCurrentWidget(self.listPage)
        self.fileNameLabel.show()
        self.fileNameEdit.show()
        self.fileNameEdit.setFocus()
        self.fileTypeLabel.show()
        self.fileTypeCombo.show()
        self.fileTypeLabelFiller.hide()
        self.fileTypeComboFiller.hide()
        self.toParentButton.setEnabled(True)
    
    @Slot()
    @Slot(bool)
    def accept(self, *args):
        indexes = self.listView.selectionModel().selectedRows()
        if indexes:
            index = indexes[0]
            if self.fileModel.isDir(index):
                self.enterDirectory(index)
                return
            fname = str(index.data())
        else:
            fname = self.fileNameEdit.text().strip()
            if not fname:
                return
            info = QtCore.QFileInfo(fname)
            if info.isDir():
                self.setPath(info.absoluteFilePath())
                return
        self.openFile.emit(os.path.join(self.getPath(), fname))
    
    @Slot(str)
    def autoCompleteFileName(self, text):
        if not text.strip():
            return
        if text.strip().startswith("/"):
            self.listView.selectionModel().clearSelection()
            return
        idx = self.fileModel.index(self.fileModel.rootPath() + QtCore.QDir.separator() + text)
        if self.fileNameEdit.hasFocus():
            self.listView.selectionModel().clear()
        self.select(idx)
    
    def select(self, index):
        if index.isValid():
            self.listView.selectionModel().select(index,
                QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
            self.listView.scrollTo(index, self.listView.EnsureVisible)
        return index
    
    @Slot(QtCore.QItemSelection, QtCore.QItemSelection)
    def fileSelectionChanged(self, one, two):
        indexes = self.listView.selectionModel().selectedRows()
        if indexes:
            idx = indexes[0]
            self.fileNameEdit.setText(str(idx.data()))
            self.buttonOpen.setEnabled(True)
        else:
            self.buttonOpen.setEnabled(False)
