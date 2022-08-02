#!/usr/bin/env python
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
Application module for usdmanager.

Class hierarchy:

- App

  - UsdMngrWindow (multiple windows allowed)

    - AddressBar
    - TabWidget

      - TabBar
      - BrowserTab (one tab per file)

        - TextBrowser

            - LineNumbers

        - TextEdit

            - PlainTextLineNumbers

"""
from __future__ import absolute_import, division, print_function

import argparse
import inspect
import json
import logging
import os
import re
import shlex
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
import warnings
from contextlib import contextmanager
from functools import partial
from glob import glob
from pkg_resources import resource_filename

# To lock down or prefer a specific Qt version:
#if "QT_PREFERRED_BINDING" not in os.environ:
#    os.environ["QT_PREFERRED_BINDING"] = os.pathsep.join(["PyQt5", "PySide2", "PyQt4", "PySide"])

import Qt
from Qt import QtCore, QtGui, QtWidgets
from Qt.QtCore import Signal, Slot

# Qt.py versions before 1.1.0 may not support this.
QtPrintSupport = None
try:
    from Qt import QtPrintSupport
except ImportError:
    pass

from . import highlighter, images_rc, utils
from .constants import (
    LINE_LIMIT, FILE_FILTER, FILE_FORMAT_NONE, FILE_FORMAT_TXT, FILE_FORMAT_USD, FILE_FORMAT_USDA, FILE_FORMAT_USDC,
    FILE_FORMAT_USDZ, HTML_BODY, RECENT_FILES, RECENT_TABS, USD_AMBIGUOUS_EXTS, USD_ASCII_EXTS, USD_CRATE_EXTS,
    USD_ZIP_EXTS, USD_EXTS)
from .file_dialog import FileDialog
from .file_status import FileStatus
from .find_dialog import FindDialog
from .linenumbers import LineNumbers, PlainTextLineNumbers
from .include_panel import IncludePanel
from .parser import AbstractExtParser, FileParser, SaveFileError
from .plugins import images_rc as plugins_rc
from .plugins import Plugin
from .preferences_dialog import PreferencesDialog


# Set up logging.
logger = logging.getLogger(__name__)
logging.basicConfig()


# Qt.py compatibility.
if Qt.IsPySide2 or Qt.IsPyQt5:
    if Qt.IsPySide2:
        # Add QUrl.path missing in PySide2 build.
        if not hasattr(QtCore.QUrl, "path"):
            def qUrlPath(self):
                """ Get the decoded URL without any query string.

                :Returns:
                    Decoded URL without query string
                :Rtype:
                    `str`
                """
                return self.toString(QtCore.QUrl.PrettyDecoded | QtCore.QUrl.RemoveQuery)

            QtCore.QUrl.path = qUrlPath

    # Add query pair/value delimiters until we move fully onto Qt5 and switch to the QUrlQuery class.
    def queryPairDelimiter(self):
        """ Get the query pair delimiter character.

        :Returns:
            Query pair delimiter character
        :Rtype:
            `str`
        """
        try:
            return self._queryPairDelimiter
        except AttributeError:
            self._queryPairDelimiter = "&"
            return self._queryPairDelimiter

    def queryValueDelimiter(self):
        """ Get the query value delimiter character.

        :Returns:
            Query value delimiter character
        :Rtype:
            `str`
        """
        try:
            return self._queryValueDelimiter
        except AttributeError:
            self._queryValueDelimiter = "="
            return self._queryValueDelimiter

    def setQueryDelimiters(self, valueDelimiter, pairDelimiter):
        """ Set the query pair and value delimiter characters.

        :Parameters:
            valueDelimiter : `str`
                Query value delimiter character
            pairDelimiter : `str`
                Query pair delimiter character
        """
        self._queryValueDelimiter = valueDelimiter
        self._queryPairDelimiter = pairDelimiter

    QtCore.QUrl.queryPairDelimiter = queryPairDelimiter
    QtCore.QUrl.queryValueDelimiter = queryValueDelimiter
    QtCore.QUrl.setQueryDelimiters = setQueryDelimiters
elif Qt.IsPySide or Qt.IsPyQt4:
    # Add basic support for QUrl.setQuery to PySide and PyQt4 (added in Qt5).
    def qUrlSetQuery(self, query, mode=QtCore.QUrl.TolerantMode):
        """
        :Parameters:
            query : `str`
                Query string (without the leading '?' character)
            mode : `QtCore.QUrl.ParsingMode`
                Ignored for now. For Qt5 method signature compatibility only.
        """
        return self.setQueryItems(
            [x.split(self.queryValueDelimiter(), 1) for x in query.split(self.queryPairDelimiter())]
        )

    QtCore.QUrl.setQuery = qUrlSetQuery


class UsdMngrWindow(QtWidgets.QMainWindow):
    """
    File Browser/Text Editor for quick navigation and editing among text-based files that reference other files.
    Normal links are colored blue (USD Crate files are a different shade of blue). The linked file exists.
    Links to multiple files are colored yellow. Files may or may not exist.
    Links that cannot be resolved or confirmed as valid files are colored red.

    Ideas (in no particular order):

    - Better usdz support (https://graphics.pixar.com/usd/docs/Usdz-File-Format-Specification.html)

      - Ability to write and repackage as usdz

    - Different extensions to search for based on file type.
    - Add customized print options like name of file and date headers, similar to printing a web page.
    - Move setSource link parsing to a thread?
    - Move file status to a thread?
    - Dark theme syntax highlighting could use work. The bare minimum to get this working was done.
    - Going from Edit mode back to Browse mode shouldn't reload the document if the file on disk hasn't changed.
      Not sure why this is slower than just loading the browse tab in the first place...
    - More detailed history that persists between sessions.
    - Cross-platform testing:

      - Windows mostly untested.
      - Mac could use more testing and work with icons and theme.

    - Remember scroll position per file so going back in history jumps you to approximately where you were before.
    - Add Browse... buttons to select default applications.
    - Set consistent cross-platform read/write/execute permissions when saving new files.

    Known issues:

        - AddressBar file completer has problems occasionally.
        - Find with text containing a new line character does not work due to QTextDocument storing these as separate
          blocks.
        - Line numbers width not always immediately updated after switching to new class.
        - If a file loses edit permissions, it can stay in edit mode and let you make changes that can't be saved.
        - Qt bug: QPushButton dark theme hover/press color not respected.

    """

    compileLinkRegEx = Signal()
    editModeChanged = Signal(bool)
    updatingButtons = Signal()

    def __init__(self, parent=None, **kwargs):
        """ Create and initialize the main window.

        :Parameters:
            parent : `QtWidgets.QWidget` | None
                Parent object
        """
        super(UsdMngrWindow, self).__init__(parent, **kwargs)

        # This window class has access to these member variables:
        # self.app, self.config.

        # Set default programs to a dictionary of extension: program pairs, where the extension is launched with the
        # given program. This is useful for adding custom programs to view things like .exr images or .abc models. A
        # blank string is opened by this app, not launched externally. The user's preferred programs are stored in
        # self.programs.
        self.defaultPrograms = {x: "" for x in USD_EXTS}
        self.defaultPrograms.update(self.app.DEFAULTS['defaultPrograms'])
        self.programs = self.defaultPrograms
        self.masterHighlighters = {}
        self.preferences = {}

        self._darkTheme = False
        self.contextMenuPos = None
        self.findDlg = None
        self.lastOpenFileDir = self.app.opts['dir']
        self.linkHighlighted = QtCore.QUrl("")
        self.quitting = False  # If the app is in the process of shutting down
        self._prevParser = None  # Previous file parser, used for menu updates
        self.currTab = None  # Currently selected tab

        # Track changes to files on disk.
        self.fileSystemWatcher = QtCore.QFileSystemWatcher(self)
        self.fileSystemModified = set()

        self.setupUi()
        self.connectSignals()

        # Find and initialize plugins.
        self.plugins = []
        for module in utils.findModules("plugins"):
            for name, cls in inspect.getmembers(module, lambda x: inspect.isclass(x) and issubclass(x, Plugin)):
                try:
                    plugin = cls(self)
                except Exception:
                    logger.exception("Failed to initialize plugin %s", name)
                else:
                    logger.debug("Initialized plugin %s", name)
                    self.plugins.append(plugin)

    def _initFileParser(self, cls, name):
        """ Initialize a file parser.

        :Parameters:
            cls : `FileParser`
                Parser class to instantiate
            name : `str`
                Class name
        :Returns:
            File parser instance
        :Rtype:
            `FileParser`
        """
        try:
            parser = cls(self)
            parser.compile()
        except Exception:
            logger.exception("Failed to initialize parser %s", name)
        else:
            logger.debug("Initialized parser %s", name)
            return parser

    def setupUi(self):
        """ Create and lay out the widgets defined in the ui file, then add additional modifications to the UI.
        """
        self.baseInstance = utils.loadUiWidget('main_window.ui', self)

        # You now have access to the widgets defined in the ui file.
        # Update some app defaults that required the GUI to be created first.
        self.setWindowIcon(QtGui.QIcon(":images/images/logo.png"))
        defaultDocFont = QtGui.QFont()
        defaultDocFont.setStyleHint(QtGui.QFont.Courier)
        defaultDocFont.setFamily("Monospace")
        defaultDocFont.setPointSize(9)
        defaultDocFont.setBold(False)
        defaultDocFont.setItalic(False)
        self.app.DEFAULTS['font'] = defaultDocFont

        self.readSettings()

        # Changing the theme while the app is already running doesn't work well.
        # Currently, we set this once, and the user must restart the application to see changes.
        userThemeName = self.app.opts['theme'] or self.preferences['theme']
        if userThemeName == "dark":
            self._darkTheme = True
            # Set usdview-based stylesheet.
            logger.debug("Setting dark theme")
            
            iconThemeName = self.app.DEFAULTS['iconThemes'][userThemeName]
            logger.debug("Icon theme name: %s", iconThemeName)
            QtGui.QIcon.setThemeName(iconThemeName)
            del iconThemeName
            
            stylesheet = resource_filename(__name__, "usdviewstyle.qss")
            with open(stylesheet) as f:
                # Qt style sheet accepts only forward slashes as path separators.
                sheetString = f.read().replace('RESOURCE_DIR', os.path.dirname(stylesheet).replace("\\", "/"))
            self.setStyleSheet(sheetString)

        # Do some additional adjustments for any dark theme, even if it's coming from the system settings.
        # TODO: Be able to make these adjustments on the fly if the user changes the system theme.
        if self.isDarkTheme():
            highlighter.DARK_THEME = True

            # Change some more stuff that the stylesheet doesn't catch.
            p = QtWidgets.QApplication.palette()
            p.setColor(p.Link, QtGui.QColor(0, 205, 250))
            QtWidgets.QApplication.setPalette(p)

            # Redefine some colors for the dark theme.
            global HTML_BODY
            HTML_BODY = \
"""<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" "http://www.w3.org/TR/REC-html40/strict.dtd">
<html><head><style type="text/css">
a.mayNotExist {{color:#CC6}}
a.binary {{color:#69F}}
.badLink {{color:#F33}}
</style></head><body style="white-space:pre">{}</body></html>"""

        # Try to adhere to the freedesktop icon standards:
        # https://standards.freedesktop.org/icon-naming-spec/icon-naming-spec-latest.html
        # Some icons are preferred from the crystal_project set, which sadly follows different naming standards.
        # While we can define theme icons in the .ui file, it doesn't give us the fallback option.
        # Additionally, it doesn't work in Qt 4.8.6 but does work in Qt 5.10.0.
        # If you don't have the proper icons installed, the actions simply won't have an icon. It's non-critical.
        icon = utils.icon
        self.menuOpenRecent.setIcon(icon("document-open-recent"))
        self.actionPrintPreview.setIcon(icon("document-print-preview"))
        self.menuRecentlyClosedTabs.setIcon(icon("document-open-recent"))
        self.aboutAction.setIcon(icon("help-about"))
        self.exitAction.setIcon(icon("application-exit"))
        self.actionIndent.setIcon(icon("format-indent-more"))
        self.actionUnindent.setIcon(icon("format-indent-less"))
        self.documentationAction.setIcon(icon("help-browser"))
        self.actionBrowse.setIcon(icon("applications-internet"))
        self.actionFileInfo.setIcon(icon("dialog-information"))
        self.actionFind.setIcon(icon("edit-find"))
        self.actionFindPrev.setIcon(icon("edit-find-previous"))
        self.actionFindNext.setIcon(icon("edit-find-next"))
        self.actionPreferences.setIcon(icon("preferences-system"))
        self.actionZoomIn.setIcon(icon("zoom-in"))
        self.actionZoomOut.setIcon(icon("zoom-out"))
        self.actionNormalSize.setIcon(icon("zoom-original"))
        textEdit = icon("accessories-text-editor")
        self.actionEdit.setIcon(textEdit)
        self.actionTextEditor.setIcon(textEdit)
        self.buttonGo.setIcon(icon("media-playback-start"))
        self.actionFullScreen.setIcon(icon("view-fullscreen"))
        self.browserReloadIcon = icon("view-refresh")
        self.actionRefresh.setIcon(self.browserReloadIcon)
        self.browserStopIcon = icon("process-stop")
        self.actionStop.setIcon(self.browserStopIcon)
        self.actionOpen.setIcon(icon("document-open"))
        self.buttonFindPrev.setIcon(icon("go-previous"))
        self.buttonFindNext.setIcon(icon("go-next"))
        self.actionNewWindow.setIcon(icon("window-new"))
        self.actionOpenWith.setIcon(icon("utilities-terminal"))
        self.actionPrint.setIcon(icon("document-print"))
        self.actionUndo.setIcon(icon("edit-undo"))
        self.actionRedo.setIcon(icon("edit-redo"))
        self.actionCut.setIcon(icon("edit-cut"))
        self.actionCopy.setIcon(icon("edit-copy"))
        self.actionPaste.setIcon(icon("edit-paste"))
        self.actionSelectAll.setIcon(icon("edit-select-all"))
        self.actionSave.setIcon(icon("document-save"))
        self.actionSaveAs.setIcon(icon("document-save-as"))
        self.actionBack.setIcon(icon("go-previous"))
        self.actionForward.setIcon(icon("go-next"))
        self.actionGoToLineNumber.setIcon(icon("go-jump"))
        newTab = icon("tab-new")
        self.actionNewTab.setIcon(newTab)
        self.buttonNewTab.setIcon(newTab)
        removeTab = icon("tab-remove", icon("window-close"))
        self.actionCloseTab.setIcon(removeTab)
        self.buttonClose.setIcon(removeTab)
        close = icon("window-close")
        if close.isNull():
            self.buttonCloseFind.setText("x")
        else:
            self.buttonCloseFind.setIcon(close)

        # These icons have non-standard names and may only be available in crystal_project icons or a similar set.
        self.actionCommentOut.setIcon(icon("comment-add"))
        self.actionUncomment.setIcon(icon("comment-remove"))
        self.actionDiffFile.setIcon(icon("file-diff"))
        self.buttonHighlightAll.setIcon(icon("highlight"))

        self.aboutQtAction.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_TitleBarMenuButton))

        self.actionBrowse.setVisible(False)
        self.actionSelectAll.setEnabled(True)
        self.findWidget.setVisible(False)
        self.labelFindStatus.setVisible(False)

        # Some of our objects still need to be modified.
        # Remove them from the layout so everything can be added and placed properly.
        self.verticalLayout.removeWidget(self.buttonGo)
        self.verticalLayout.removeWidget(self.findWidget)

        self.includeWidget = IncludePanel(path=self.app.opts['dir'], filter=FILE_FILTER,
                                          selectedFilter=FILE_FILTER[FILE_FORMAT_NONE], parent=self)
        self.includeWidget.showAll(self.preferences['showHiddenFiles'])
        self.addressBar = AddressBar(self)

        # Toolbars
        self.navToolbar.addWidget(self.addressBar)
        self.navToolbar.addWidget(self.buttonGo)
        self.menuToolbars.addAction(self.editToolbar.toggleViewAction())
        self.menuToolbars.addAction(self.navToolbar.toggleViewAction())

        # Status Bar
        self.fileStatusButton = QtWidgets.QPushButton(self.statusbar)
        self.fileStatusButton.setFlat(True)
        self.fileStatusButton.setFocusPolicy(QtCore.Qt.NoFocus)
        self.fileStatusButton.setIconSize(QtCore.QSize(16, 16))
        self.fileStatusButton.setStyleSheet("QPushButton {background-color: none; border: none; margin:0; padding:0;}")
        self.statusbar.addPermanentWidget(self.fileStatusButton)

        # Tabbed browser
        self.menuTabList = QtWidgets.QMenu(self)
        self.buttonTabList.setMenu(self.menuTabList)

        self.tabWidget = TabWidget(self)
        self.tabWidget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tabWidget.setFont(self.preferences['font'])
        self.tabWidget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.tabWidget.setStyleSheet(
            "QPushButton:hover{border:1px solid #8f8f91; border-radius:3px; background-color:qlineargradient(x1:0, "
            "y1:0, x2:0, y2:1, stop:0 #f6f7fa, stop:1 #dadbde);}"
            "QPushButton:pressed{background-color:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #dadbde, "
            "stop:1 #f6f7fa);}")
        self.tabWidget.setCornerWidget(self.buttonNewTab, QtCore.Qt.TopLeftCorner)
        self.tabWidget.setCornerWidget(self.tabTopRightWidget, QtCore.Qt.TopRightCorner)
        self.tabLayout = QtWidgets.QHBoxLayout(self.tabWidget)
        self.tabLayout.setContentsMargins(0, 0, 0, 0)
        self.tabLayout.setSpacing(5)

        # Edit
        self.editWidget = QtWidgets.QWidget(self)
        self.editLayout = QtWidgets.QVBoxLayout(self.editWidget)
        self.editLayout.setContentsMargins(0, 0, 0, 0)
        self.editLayout.addWidget(self.tabWidget)
        self.editLayout.addWidget(self.findWidget)

        # Main
        self.verticalLayout.removeWidget(self.mainWidget)
        self.mainWidget = QtWidgets.QSplitter(self)
        self.mainWidget.setContentsMargins(0, 0, 0, 0)
        self.mainWidget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.mainWidget.addWidget(self.includeWidget)
        self.mainWidget.addWidget(self.editWidget)
        self.toggleInclude(self.preferences['includeVisible'])
        self.verticalLayout.addWidget(self.mainWidget)

        # Extra context menu actions
        self.actionOpenLinkNewWindow = QtWidgets.QAction(self.actionNewWindow.icon(), "Open Link in New &Window", self)
        self.actionOpenLinkNewTab = QtWidgets.QAction(self.actionNewTab.icon(), "Open Link in New &Tab", self)
        self.actionOpenLinkWith = QtWidgets.QAction(self.actionOpenWith.icon(), "&Open Link With...", self)
        self.actionSaveLinkAs = QtWidgets.QAction(self.actionSaveAs.icon(), "Save Lin&k As...", self)
        self.actionCloseOther = QtWidgets.QAction(self.actionCloseTab.icon(), "Close Other Tabs", self)
        self.actionCloseRight = QtWidgets.QAction(self.actionCloseTab.icon(), "Close Tabs to the Right", self)
        self.actionRefreshTab = QtWidgets.QAction(self.actionRefresh.icon(), "&Refresh", self)
        self.actionDuplicateTab = QtWidgets.QAction(icon("tab_duplicate"), "&Duplicate", self)
        self.actionViewSource = QtWidgets.QAction(icon("html"), "View Page So&urce", self)

        # Extra keyboard shortcuts
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+="), self, self.increaseFontSize)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+F"), self, self.toggleFind)
        QtWidgets.QShortcut(QtGui.QKeySequence("Backspace"), self, self.onBackspace)
        QtWidgets.QShortcut(QtGui.QKeySequence("F5"), self, self.refreshTab)

        # Set up master highlighter objects that we will share rules among.
        # These objects don't actually do any highlighting. The individual
        # instances of the Highlighter class we create later does the work.
        self.masterHighlighters[None] = self.createHighlighter(highlighter.MasterHighlighter)
        highlighterClasses = highlighter.findHighlighters()
        # TODO: Create these on demand instead of all when the app launches.
        for highlighterCls in highlighterClasses:
            self.createHighlighter(highlighterCls)

        self.loadingProgressBar = QtWidgets.QProgressBar(self.statusbar)
        self.loadingProgressBar.setMaximumHeight(16)
        self.loadingProgressBar.setMaximumWidth(200)
        self.loadingProgressBar.setMaximum(100)
        self.loadingProgressBar.setTextVisible(False)
        self.loadingProgressBar.setVisible(False)
        self.loadingProgressLabel = QtWidgets.QLabel(self.statusbar)
        self.loadingProgressLabel.setVisible(False)
        self.statusbar.addWidget(self.loadingProgressBar)
        self.statusbar.addWidget(self.loadingProgressLabel)

        # Find and initialize file parsers.
        # Signals require some of the UI to be created already, but we need to do this before a tab is created.
        self.fileParsers = []
        # Don't include the default parser in the list we iterate through to find compatible custom parsers,
        # since we only use it as a fallback.
        self.fileParserDefault = self._initFileParser(FileParser, FileParser.__name__)
        self._prevParser = None
        for module in utils.findModules("parsers"):
            for name, cls in inspect.getmembers(module, lambda x: inspect.isclass(x) and
                                                issubclass(x, FileParser) and
                                                x not in (FileParser, AbstractExtParser)):
                parser = self._initFileParser(cls, name)
                if parser is not None:
                    self.fileParsers.append(parser)

        # Add one of our special tabs.
        self.currTab = self.newTab()
        self.setNavigationMenus()

        # Adjust tab order.
        self.setTabOrder(self.addressBar, self.includeWidget.listView)
        self.setTabOrder(self.includeWidget.listView, self.includeWidget.fileNameEdit)
        self.setTabOrder(self.includeWidget.fileNameEdit, self.includeWidget.fileTypeCombo)
        self.setTabOrder(self.includeWidget.fileTypeCombo, self.findBar)
        self.setTabOrder(self.findBar, self.buttonFindNext)
        self.setTabOrder(self.buttonFindNext, self.buttonFindPrev)
        self.setTabOrder(self.buttonFindPrev, self.buttonHighlightAll)
        self.setTabOrder(self.buttonHighlightAll, self.checkBoxMatchCase)

        self.toggleInclude(self.preferences['includeVisible'])

        # OS-specific hacks.
        # QSysInfo doesn't have productType until Qt5.
        if (Qt.IsPySide2 or Qt.IsPyQt5) and QtCore.QSysInfo.productType() in ("osx", "macos"):
            self.buttonTabList.setIcon(icon("1downarrow1"))
            
            # OSX likes to add its own Enter/Exit Full Screen item, not recognizing we already have one.
            self.actionFullScreen.setEnabled(False)
            self.menuView.removeAction(self.actionFullScreen)

            # Make things look more cohesive on Mac (Qt5).
            try:
                self.setUnifiedTitleAndToolBarOnMac(True)
            except AttributeError:
                pass

    def createHighlighter(self, highlighterClass):
        """ Create a language-specific master highlighter to be used for any file of that language.

        :Parameters:
            highlighterClass : `highlighter.MasterHighlighter`
                Master highlighter or subclass
        :Returns:
            Highlighter instance
        :Rtype:
            `highlighter.MasterHighlighter`
        """
        h = highlighterClass(self, self.preferences['syntaxHighlighting'], self.programs)
        for ext in h.extensions:
            self.masterHighlighters[ext] = h
        return h

    def setHighlighter(self, ext=None, tab=None):
        """ Set the current tab's highlighter based on the current file extension.

        :Parameters:
            ext : `str` | None
                File extension (language) to highlight.
            tab : `BrowserTab` | None
                Tab to set highlighter on. Defaults to current tab.
        """
        if ext not in self.masterHighlighters:
            logger.debug("Using default highlighter")
            ext = None
        master = self.masterHighlighters[ext]
        tab = tab or self.currTab
        if type(tab.highlighter.master) is not master:
            logger.debug("Setting highlighter to %s", ext)
            tab.highlighter.deleteLater()
            tab.highlighter = highlighter.Highlighter(tab.getCurrentTextWidget().document(), master)

    @Slot(QtCore.QPoint)
    def customTextBrowserContextMenu(self, pos):
        """ Slot for the right-click context menu when in Browse mode.

        :Parameters:
            pos : `QtCore.QPoint`
                Position of the right-click
        """
        # Position workaround for https://bugreports.qt.io/browse/QTBUG-89439.
        customPos = pos + QtCore.QPoint(self.currTab.textBrowser.horizontalScrollBar().value(),
                                        self.currTab.textBrowser.verticalScrollBar().value())
        menu = self.currTab.textBrowser.createStandardContextMenu(customPos)
        actions = menu.actions()
        self.linkHighlighted = QtCore.QUrl(self.currTab.textBrowser.anchorAt(pos))
        if self.linkHighlighted.isValid():
            menu.insertAction(actions[0], self.actionOpenLinkNewWindow)
            menu.insertAction(actions[0], self.actionOpenLinkNewTab)
            # If this is a self-referential link, don't add certain actions.
            if not self.linkHighlighted.hasFragment():
                menu.insertAction(actions[0], self.actionOpenLinkWith)
                menu.insertSeparator(actions[0])
                menu.addAction(self.actionSaveLinkAs)
        else:
            menu.insertAction(actions[0], self.actionBack)
            menu.insertAction(actions[0], self.actionForward)
            menu.insertAction(actions[0], self.actionRefresh)
            menu.insertAction(actions[0], self.actionStop)
            menu.insertSeparator(actions[0])
            menu.addAction(self.actionSaveAs)
            path = self.currTab.getCurrentPath()
            if path:
                menu.addSeparator()
                for args in self.currTab.parser.plugins:
                    menu.addAction(*args)
                menu.addAction(self.actionTextEditor)
                menu.addAction(self.actionOpenWith)
                menu.addSeparator()
                menu.addAction(self.actionFileInfo)
                menu.addAction(self.actionViewSource)
        actions[0].setIcon(self.actionCopy.icon())
        actions[3].setIcon(self.actionSelectAll.icon())
        menu.exec_(self.currTab.textBrowser.mapToGlobal(
            pos + QtCore.QPoint(self.currTab.textBrowser.lineNumbers.width(), 0)))
        del actions, menu

    @Slot(QtCore.QPoint)
    def customTextEditorContextMenu(self, pos):
        """ Slot for the right-click context menu when in Edit mode.

        :Parameters:
            pos : `QtCore.QPoint`
                Position of the right-click
        """
        # Add icons to standard context menu.
        menu = self.currTab.textEditor.createStandardContextMenu()
        actions = menu.actions()
        actions[0].setIcon(self.actionUndo.icon())
        actions[1].setIcon(self.actionRedo.icon())
        actions[3].setIcon(self.actionCut.icon())
        actions[4].setIcon(self.actionCopy.icon())
        actions[5].setIcon(self.actionPaste.icon())
        actions[6].setIcon(utils.icon("edit-delete"))
        actions[8].setIcon(self.actionSelectAll.icon())
        path = self.currTab.getCurrentPath()
        if path:
            menu.addSeparator()
            for args in self.currTab.parser.plugins:
                menu.addAction(*args)
            menu.addAction(self.actionTextEditor)
            menu.addAction(self.actionOpenWith)
            menu.addSeparator()
            menu.addAction(self.actionFileInfo)
        menu.exec_(self.currTab.textEditor.mapToGlobal(pos))
        del actions, menu

    @Slot(QtCore.QPoint)
    def customTabWidgetContextMenu(self, pos):
        """ Slot for the right-click context menu for the tab widget.

        :Parameters:
            pos : `QtCore.QPoint`
                Position of the right-click
        """
        menu = QtWidgets.QMenu(self)
        menu.addAction(self.actionNewTab)
        menu.addSeparator()
        menu.addAction(self.actionRefreshTab)
        menu.addAction(self.actionDuplicateTab)
        menu.addSeparator()
        menu.addAction(self.actionCloseTab)
        menu.addAction(self.actionCloseOther)
        menu.addAction(self.actionCloseRight)

        self.contextMenuPos = self.tabWidget.tabBar.mapFromParent(pos)
        indexOfClickedTab = self.tabWidget.tabBar.tabAt(self.contextMenuPos)

        # Save the original state so we don't mess with the menu action, since this one action is re-used.
        # TODO: Maybe make a new action instead of reusing this.
        state = self.actionCloseTab.isEnabled()

        if indexOfClickedTab == -1:
            self.actionCloseTab.setEnabled(False)
            self.actionCloseOther.setEnabled(False)
            self.actionCloseRight.setEnabled(False)
            self.actionRefreshTab.setEnabled(False)
            self.actionDuplicateTab.setEnabled(False)
        else:
            self.actionCloseTab.setEnabled(True)
            self.actionCloseOther.setEnabled(self.tabWidget.count() > 1)
            self.actionCloseRight.setEnabled(indexOfClickedTab < self.tabWidget.count() - 1)
            self.actionRefreshTab.setEnabled(bool(self.tabWidget.widget(indexOfClickedTab).getCurrentPath()))
            self.actionDuplicateTab.setEnabled(True)

        menu.exec_(self.tabWidget.mapToGlobal(pos))
        del menu
        self.contextMenuPos = None

        # Restore previous action state.
        self.actionCloseTab.setEnabled(state)

    def readSettings(self):
        """ Read in user config settings.
        """
        logger.debug("Reading user settings from %s", self.config.fileName())
        default = self.app.DEFAULTS
        self.preferences = {
            'parseLinks': self.config.boolValue("parseLinks", default['parseLinks']),
            'newTab': self.config.boolValue("newTab", default['newTab']),
            'syntaxHighlighting': self.config.boolValue("syntaxHighlighting", default['syntaxHighlighting']),
            'teletype': self.config.boolValue("teletype", default['teletype']),
            'lineNumbers': self.config.boolValue("lineNumbers", default['lineNumbers']),
            'showAllMessages': self.config.boolValue("showAllMessages", default['showAllMessages']),
            'showHiddenFiles': self.config.boolValue("showHiddenFiles", default['showHiddenFiles']),
            'font': self.config.value("font", default['font']),
            'fontSizeAdjust': int(self.config.value("fontSizeAdjust", default['fontSizeAdjust'])),
            'findMatchCase': self.config.boolValue("findMatchCase", default['findMatchCase']),
            'includeVisible': self.config.boolValue("includeVisible", default['includeVisible']),
            'lastOpenWithStr': self.config.value("lastOpenWithStr", default['lastOpenWithStr']),
            'textEditor': self.config.value("textEditor", default['textEditor']),
            'diffTool': self.config.value("diffTool", default['diffTool']),
            'autoCompleteAddressBar': self.config.boolValue("autoCompleteAddressBar",
                                                            default['autoCompleteAddressBar']),
            'useSpaces': self.config.boolValue("useSpaces", default['useSpaces']),
            'tabSpaces': int(self.config.value("tabSpaces", default['tabSpaces'])),
            'theme': self.config.value("theme", default['theme']),
            'lineLimit': int(self.config.value("lineLimit", default['lineLimit'])),
            'autoIndent': self.config.boolValue("autoIndent", default['autoIndent']),
        }

        # Read 'programs' settings object into self.programs.
        progs = []
        size = self.config.beginReadArray("programs")
        for i in range(size):
            self.config.setArrayIndex(i)
            progs.append([self.config.value("extension"),
                          self.config.value("program")])
        self.config.endArray()
        if not progs:
            # If no programs exist, use the default ones.
            logger.debug("Setting default programs.")
        else:
            self.programs = dict(progs)

            # Unfortunately, the programs setting was designed so it would save out the setting
            # the first time the user opened the programs. That meant that any new file types added
            # would not get picked up by the user. This isn't a perfect solution, since a user may
            # have intentionally removed a file type, but add back any keys from the defaults that
            # are not in the user's settings.
            for key in self.defaultPrograms:
                if key not in self.programs:
                    logger.debug("Restoring program for file type %s", key)
                    self.programs[key] = self.defaultPrograms[key]

        # Set toolbar visibility and positioning.
        standardVis = self.config.boolValue("standardToolbarVisible", True)
        self.editToolbar.setVisible(standardVis)
        self.editToolbar.toggleViewAction().setChecked(standardVis)

        # Nav toolbar.
        navVis = self.config.boolValue("navToolbarVisible", True)
        self.navToolbar.setVisible(navVis)

        # Get recent files list.
        for path in self.getRecentFilesFromSettings():
            action = RecentFile(utils.strToUrl(path), self.menuOpenRecent, self.openRecent)
            self.menuOpenRecent.addAction(action)
        if self.menuOpenRecent.actions():
            self.menuOpenRecent.setEnabled(True)

        # Update GUI to match preferences.
        self.checkBoxMatchCase.setChecked(self.preferences['findMatchCase'])
        self.actionIncludePanel.setChecked(self.preferences['includeVisible'])

        # Restore window state.
        geometry = self.config.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        windowState = self.config.value("windowState")
        if windowState is not None:
            self.restoreState(windowState)

    def writeSettings(self):
        """ Write out user config settings to disk.

        This should only write settings modified via the Preferences dialog, as other preferences like "recentFiles"
        will be written immediately as they're modified. Some settings like window state are only saved on exit.
        """
        logger.debug("Writing user settings to %s", self.config.fileName())
        self.config.setValue("parseLinks", self.preferences['parseLinks'])
        self.config.setValue("newTab", self.preferences['newTab'])
        self.config.setValue("syntaxHighlighting", self.preferences['syntaxHighlighting'])
        self.config.setValue("teletype", self.preferences['teletype'])
        self.config.setValue("lineNumbers", self.preferences['lineNumbers'])
        self.config.setValue("showAllMessages", self.preferences['showAllMessages'])
        self.config.setValue("showHiddenFiles", self.preferences['showHiddenFiles'])
        self.config.setValue("font", self.preferences['font'])
        self.config.setValue("textEditor", self.preferences['textEditor'])
        self.config.setValue("diffTool", self.preferences['diffTool'])
        self.config.setValue("autoCompleteAddressBar", self.preferences['autoCompleteAddressBar'])
        self.config.setValue("useSpaces", self.preferences['useSpaces'])
        self.config.setValue("tabSpaces", self.preferences['tabSpaces'])
        self.config.setValue("theme", self.preferences['theme'])
        self.config.setValue("lineLimit", self.preferences['lineLimit'])
        self.config.setValue("autoIndent", self.preferences['autoIndent'])

        # Write self.programs to settings object
        self.config.beginWriteArray("programs")
        for i, (ext, prog) in enumerate(self.programs.items()):
            self.config.setArrayIndex(i)
            self.config.setValue("extension", ext)
            self.config.setValue("program", prog)
        self.config.endArray()

    def getRecentFilesFromSettings(self):
        """ Get recent files from user settings.

        :Returns:
            Recent files as `str` paths
        :Rtype:
            `list`
        """
        paths = []
        size = min(self.config.beginReadArray("recentFiles"), RECENT_FILES)
        for i in range(size):
            self.config.setArrayIndex(i)
            path = self.config.value("path")
            if path:
                paths.append(path)
        self.config.endArray()
        return paths

    def writeRecentFilesToSettings(self, paths):
        """ Write recent files list to user settings.

        :Parameters:
            paths : `list`
                List of `str` file paths
        """
        self.config.beginWriteArray("recentFiles")
        for i, path in enumerate(paths):
            if i == RECENT_FILES:
                break
            self.config.setArrayIndex(i)
            self.config.setValue("path", path)
        self.config.endArray()

    def addRecentFileToSettings(self, path):
        """ Add a recent file to the user settings.

        Re-read the user settings from disk to get the latest (in case there are any other open instances of this app
        updating the list), then just prepend the one latest file.

        :Parameters:
            path : `str`
                File path
        """
        # Strip the URL file scheme from the head of the path for consistency with legacy settings.
        path = utils.stripFileScheme(path)
        paths = [x for x in self.getRecentFilesFromSettings() if x != path]
        paths.insert(0, path)
        self.writeRecentFilesToSettings(paths)

    def connectSignals(self):
        """ Connect signals to slots.
        """
        # Include Panel
        self.includeWidget.openFile.connect(self.onOpen)
        self.mainWidget.splitterMoved.connect(self.setIncludePanelActionState)
        # Editors.
        self.actionOpenLinkNewWindow.triggered.connect(self.onOpenLinkNewWindow)
        self.actionOpenLinkNewTab.triggered.connect(self.onOpenLinkNewTab)
        self.actionSaveLinkAs.triggered.connect(self.saveLinkAs)
        self.tabWidget.currentChanged.connect(self.currentTabChanged)
        # File Menu
        self.actionNewWindow.triggered.connect(self.newWindow)
        self.actionNewTab.triggered.connect(self.newTab)
        self.actionOpen.triggered.connect(self.openFileDialogToCurrentPath)
        self.actionSave.triggered.connect(self.saveTab)
        self.actionSaveAs.triggered.connect(self.saveFileAs)
        self.actionPrintPreview.triggered.connect(self.printPreview)
        self.actionPrint.triggered.connect(self.printDialog)
        self.actionCloseTab.triggered.connect(self.closeTab)
        self.actionCloseOther.triggered.connect(self.closeOtherTabs)
        self.actionCloseRight.triggered.connect(self.closeRightTabs)
        # Edit Menu
        self.actionEdit.triggered.connect(self.toggleEdit)
        self.actionBrowse.triggered.connect(self.toggleEdit)
        self.actionUndo.triggered.connect(self.undo)
        self.actionRedo.triggered.connect(self.redo)
        self.actionCut.triggered.connect(self.cut)
        self.actionCopy.triggered.connect(self.copy)
        self.actionPaste.triggered.connect(self.paste)
        self.actionSelectAll.triggered.connect(self.selectAll)
        self.actionFind.triggered.connect(self.showFindReplaceDlg)
        self.actionFindPrev.triggered.connect(self.findPrev)
        self.actionFindNext.triggered.connect(self.find)
        self.actionGoToLineNumber.triggered.connect(self.goToLineNumberDlg)
        self.actionPreferences.triggered.connect(self.editPreferences)
        # View Menu
        self.actionIncludePanel.toggled.connect(self.toggleInclude)
        self.actionRefresh.triggered.connect(self.refreshTab)
        self.actionZoomIn.triggered.connect(self.increaseFontSize)
        self.actionZoomOut.triggered.connect(self.decreaseFontSize)
        self.actionNormalSize.triggered.connect(self.defaultFontSize)
        self.actionFullScreen.toggled.connect(self.toggleFullScreen)
        # History Menu
        self.actionBack.triggered.connect(self.browserBack)
        self.actionForward.triggered.connect(self.browserForward)
        # Commands Menu
        self.actionDiffFile.triggered.connect(self.diffFile)
        self.actionFileInfo.triggered.connect(self.fileInfo)
        self.actionCommentOut.triggered.connect(self.commentTextRequest)
        self.actionUncomment.triggered.connect(self.uncommentTextRequest)
        self.actionIndent.triggered.connect(self.indentText)
        self.actionUnindent.triggered.connect(self.unindentText)
        self.actionTextEditor.triggered.connect(self.launchTextEditor)
        self.actionOpenWith.triggered.connect(self.launchProgramOfChoice)
        self.actionOpenLinkWith.triggered.connect(self.onOpenLinkWith)
        # Help Menu
        self.aboutAction.triggered.connect(self.showAboutDialog)
        self.aboutQtAction.triggered.connect(self.showAboutQtDialog)
        self.documentationAction.triggered.connect(self.desktopOpenUrl)
        # Miscellaneous buttons, checkboxes, etc.
        self.addressBar.textEdited.connect(self.validateAddressBar)
        self.addressBar.openFile.connect(self.onOpen)
        self.addressBar.goPressed.connect(self.goPressed)
        self.buttonGo.clicked.connect(self.goPressed)
        self.breadcrumb.linkActivated.connect(self.onBreadcrumbActivated)
        self.breadcrumb.linkHovered.connect(self.onBreadcrumbHovered)
        self.tabWidget.customContextMenuRequested.connect(self.customTabWidgetContextMenu)
        self.buttonNewTab.clicked.connect(self.newTab)
        self.buttonClose.clicked.connect(self.closeTab)
        self.tabWidget.tabBar.tabMoveRequested.connect(self.moveTab)
        self.tabWidget.tabBar.crossWindowTabMoveRequested.connect(self.moveTabAcrossWindows)
        self.actionDuplicateTab.triggered.connect(self.duplicateTab)
        self.actionRefreshTab.triggered.connect(self.refreshSelectedTab)
        self.actionViewSource.triggered.connect(self.viewSource)
        self.fileSystemWatcher.fileChanged.connect(self.onFileChange)
        # Find
        self.buttonCloseFind.clicked.connect(self.toggleFindClose)
        self.findBar.textEdited.connect(self.validateFindBar)
        self.findBar.returnPressed.connect(self.find)
        self.buttonFindPrev.clicked.connect(self.findPrev)
        self.buttonFindNext.clicked.connect(self.find)
        self.buttonHighlightAll.clicked.connect(self.findHighlightAll)
        self.checkBoxMatchCase.clicked.connect(self.updatePreference_findMatchCase)

    def closeEvent(self, event):
        """ Override the default closeEvent called on exit.
        """
        # Check if we want to save any dirty tabs.
        self.quitting = True
        for _ in range(self.tabWidget.count()):
            if not self.closeTab(index=0):
                # Don't quit.
                event.ignore()
                self.quitting = False
                self.findRehighlightAll()
                return

        # Ok to quit.
        # Save user settings that don't get controlled by the Preferences dialog and don't already write to the config.
        self.config.setValue("standardToolbarVisible", self.editToolbar.isVisible())
        self.config.setValue("navToolbarVisible", self.navToolbar.isVisible())
        self.config.setValue("geometry", self.saveGeometry())
        self.config.setValue("windowState", self.saveState())

        event.accept()

    ###
    # File Menu Methods
    ###

    @Slot()
    def newWindow(self):
        """ Create a new window.

        :Returns:
            New main window widget
        :Rtype:
            `QtWidgets.QWidget`
        """
        return self.app.newWindow()

    @Slot(bool)
    def newTab(self, checked=False, focus=True):
        """ Create a new tab.

        :Parameters:
            checked : `bool`
                For signal only
            focus : `bool`
                If True, change focus to this tab
        :Returns:
            New tab
        :Rtype:
            `BrowserTab`
        """
        newTab = BrowserTab(self.tabWidget)
        newTab.highlighter = highlighter.Highlighter(newTab.getCurrentTextWidget().document(),
                                                     self.masterHighlighters[None])
        newTab.parser = self.fileParserDefault
        newTab.textBrowser.zoomIn(self.preferences['fontSizeAdjust'])
        newTab.textEditor.zoomIn(self.preferences['fontSizeAdjust'])
        idx = self.tabWidget.addTab(newTab, "(Untitled)")
        if focus:
            self.tabWidget.setCurrentIndex(idx)
        self.addressBar.setFocus()

        # Add to menu of tabs.
        self.menuTabList.addAction(newTab.action)
        self.connectTabSignals(newTab)
        return newTab

    def connectTabSignals(self, tab):
        """ Connect signals for a new tab.

        :Parameters:
            tab : `BrowserTab`
                Tab widget
        """
        # Keep in sync with signals in disconnectTabSignals.
        tab.openFile.connect(self.onOpen)
        tab.openOldUrl.connect(self.onOpenOldUrl)
        tab.changeTab.connect(self.changeTab)
        tab.restoreTab.connect(self.restoreTab)
        tab.textBrowser.anchorClicked.connect(self.setSource)
        tab.textBrowser.highlighted[QtCore.QUrl].connect(self.hoverUrl)
        tab.textBrowser.customContextMenuRequested.connect(self.customTextBrowserContextMenu)
        tab.textEditor.customContextMenuRequested.connect(self.customTextEditorContextMenu)
        tab.textBrowser.copyAvailable.connect(self.actionCopy.setEnabled)
        tab.tabNameChanged.connect(self._changeTabName)
        tab.textEditor.undoAvailable.connect(self.actionUndo.setEnabled)
        tab.textEditor.redoAvailable.connect(self.actionRedo.setEnabled)
        tab.textEditor.copyAvailable.connect(self.actionCopy.setEnabled)
        tab.textEditor.copyAvailable.connect(self.actionCut.setEnabled)

    def disconnectTabSignals(self, tab):
        """ Disconnect signals for a tab.

        :Parameters:
            tab : `BrowserTab`
                Tab widget
        """
        # Keep in sync with signals in connectTabSignals.
        tab.openFile.disconnect(self.onOpen)
        tab.openOldUrl.disconnect(self.onOpenOldUrl)
        tab.changeTab.disconnect(self.changeTab)
        tab.restoreTab.disconnect(self.restoreTab)
        tab.textBrowser.anchorClicked.disconnect(self.setSource)
        tab.textBrowser.highlighted[QtCore.QUrl].disconnect(self.hoverUrl)
        tab.textBrowser.customContextMenuRequested.disconnect(self.customTextBrowserContextMenu)
        tab.textEditor.customContextMenuRequested.disconnect(self.customTextEditorContextMenu)
        tab.textBrowser.copyAvailable.disconnect(self.actionCopy.setEnabled)
        tab.tabNameChanged.disconnect(self._changeTabName)
        tab.textEditor.undoAvailable.disconnect(self.actionUndo.setEnabled)
        tab.textEditor.redoAvailable.disconnect(self.actionRedo.setEnabled)
        tab.textEditor.copyAvailable.disconnect(self.actionCopy.setEnabled)
        tab.textEditor.copyAvailable.disconnect(self.actionCut.setEnabled)

    def openFileDialog(self, path=None, tab=None):
        """ Show the Open File dialog and open any selected files.

        :Parameters:
            path : `str` | None
                File path to pre-select on open
            tab : `BrowserTab` | None
                Tab to open files for. Defaults to current tab.
        """
        tab = tab or self.currTab
        startFilter = FILE_FILTER[tab.fileFormat]
        fd = FileDialog(self, "Open File(s)", self.lastOpenFileDir, FILE_FILTER, startFilter,
                        self.preferences['showHiddenFiles'])
        fd.setFileMode(fd.ExistingFiles)
        if path:
            fd.selectFile(path)
        if fd.exec_() == fd.Accepted:
            paths = fd.selectedFiles()
            if paths:
                self.lastOpenFileDir = QtCore.QFileInfo(paths[0]).absoluteDir().path()
                self.setSources(paths, tab=tab)

    @Slot()
    def openFileDialogToCurrentPath(self):
        """ Show the Open File dialog and open any selected files, pre-selecting the current file (if any).
        """
        self.openFileDialog(self.currTab.getCurrentPath())

    @Slot(QtCore.QUrl)
    def openRecent(self, url):
        """ Open an item from the Open Recent menu in a new tab.

        :Parameters:
            url : `QtCore.QUrl`
                File URL
        """
        self.setSource(url, newTab=True)

    def saveFile(self, filePath, fileFormat=FILE_FORMAT_NONE, tab=None):
        """ Save the current file as the given filePath.

        :Parameters:
            filePath : `str`
                Path to save file as.
            fileFormat : `int`
                File format when saving as a generic extension
            tab : `BrowserTab` | None
                Tab to save. Defaults to current tab.
        :Returns:
            If saved or not.
        :Rtype:
            `bool`
        """
        try:
            logger.debug("Checking file status: %s", filePath)
            qFile = QtCore.QFile(filePath)
            fileInfo = QtCore.QFileInfo(qFile)
            if qFile.exists() and not fileInfo.isWritable():
                self.showCriticalMessage("The file is not writable.\n{}".format(filePath), title="Save File")
                return False
            logger.debug("Writing file")
            self.setOverrideCursor()
            tab = tab or self.currTab

            _, ext = os.path.splitext(filePath)
            if ext[1:] in USD_AMBIGUOUS_EXTS and (fileFormat == FILE_FORMAT_USDC or (
                    fileFormat == FILE_FORMAT_NONE and tab.fileFormat == FILE_FORMAT_USDC)):
                # Saving as crate file with generic (i.e. .usd, not .usdc) extension.
                # Set the URL to ensure we pick up the crate parser instead of the generic USD parser.
                url = utils.strToUrl(filePath + "?binary=1")
            else:
                url = utils.strToUrl(filePath)

            for parser in self.fileParsers:
                if parser.acceptsFile(fileInfo, url):
                    break
            else:
                parser = self.fileParserDefault

            # Don't monitor changes to this file while we save it.
            self.fileSystemWatcher.removePath(filePath)

            parser.write(qFile, filePath, tab, self.app.tmpDir)
            # This sometimes triggers too early if we're saving the file, prompting you to reload your own changes.
            # Delay re-watching the file by a millisecond.
            # Don't watch the file if this is a temp .usd file for crate conversion.
            QtCore.QTimer.singleShot(10, partial(self.fileSystemWatcher.addPath, filePath))
            tab.setDirty(False)
        except SaveFileError as e:
            self.restoreOverrideCursor()
            self.showCriticalMessage(str(e), e.details, title="Save File")
            return False
        except Exception:
            self.restoreOverrideCursor()
            self.showCriticalMessage("Failed to save file!", traceback.format_exc(), title="Save File")
            return False

        # TODO: Saving .txt as .rdlb doesn't update binary icon until refreshing, but .txt to .usdc does.
        self.restoreOverrideCursor()
        return True

    def updateTabParser(self, tab, fileInfo, link, fileFormat=None):
        """ Update the file parser a tab is using based on the given file.
        
        :Parameters:
            tab : `BrowserTab`
                Tab
            fileInfo : `QtCore.QFileInfo`
                File info object
            link : `QtCore.QUrl`
                Link to file, potentially with query parameters
            fileFormat : `int` | None
                The parser must match this file format, if not None.
        """
        if tab == self.currTab:
            self._prevParser = tab.parser

        for parser in self.fileParsers:
            # TODO: Improve UsdParser so the FILE_FORMAT_USDC check isn't needed here.
            if parser.acceptsFile(fileInfo, link) and (
                    fileFormat is None or fileFormat == parser.fileFormat or
                    (fileFormat == FILE_FORMAT_USDC and parser.fileFormat in (FILE_FORMAT_USD, FILE_FORMAT_USDA))):
                logger.debug("Using parser %s", parser.__class__.__name__)
                tab.parser = parser
                break
        else:
            # No matching file parser found.
            logger.debug("Using default parser")
            tab.parser = self.fileParserDefault

    def getSaveAsPath(self, path=None, tab=None, fileFilter=None):
        """ Get a path from the user to save an arbitrary file as.

        :Parameters:
            path : `str` | None
                Path to use for selecting default file extension filter.
            tab : `BrowserTab` | None
                Tab that path is for.
            fileFilter : `str` | None
                File name filter to pre-select
        :Returns:
            Tuple of the absolute path user wants to save file as (or None if no file was selected or an error occurred)
            and the file format if explicitly set for USD files (e.g. usda)
        :Rtype:
            (`str`|None, `int`)
        """
        if path and fileFilter is None:
            # Find the first file filter that matches the current file extension.
            _, ext = os.path.splitext(path)
            extRe = re.compile(r'\*\.{}\b'.format(ext))
            for nameFilter in FILE_FILTER:
                if extRe.search(nameFilter):
                    fileFilter = nameFilter
                    break
            else:
                fileFilter = FILE_FILTER[FILE_FORMAT_NONE]
        else:
            tab = tab or self.currTab
            path = tab.getCurrentPath()
            if fileFilter is None:
                fileFilter = FILE_FILTER[tab.fileFormat]

        dlg = FileDialog(self, "Save File As", path or self.lastOpenFileDir, FILE_FILTER, fileFilter,
                         self.preferences['showHiddenFiles'])
        dlg.setAcceptMode(dlg.AcceptSave)
        dlg.setFileMode(dlg.AnyFile)
        if dlg.exec_() != dlg.Accepted:
            return None, FILE_FORMAT_NONE

        filePaths = dlg.selectedFiles()
        if not filePaths or not filePaths[0]:
            return None, FILE_FORMAT_NONE

        filePath = filePaths[0]
        selectedFilter = dlg.selectedNameFilter()

        modifiedExt = False
        _, ext = os.path.splitext(filePath)
        # Find the file format based on the selected file filter.
        fileFormat = FILE_FILTER.index(selectedFilter)
        if fileFormat == FILE_FORMAT_USD:
            if ext[1:] in USD_AMBIGUOUS_EXTS + USD_ASCII_EXTS:
                # Default .usd to ASCII for now.
                # TODO: Make that a user preference? usdcat defaults .usd to usdc.
                fileFormat = FILE_FORMAT_USDA
            elif ext[1:] in USD_CRATE_EXTS:
                fileFormat = FILE_FORMAT_USDC
            elif ext[1:] in USD_ZIP_EXTS:
                fileFormat = FILE_FORMAT_USDZ
            else:
                self.showCriticalMessage("Please enter a valid extension for {}".format(selectedFilter))
                return self.getSaveAsPath(filePath, tab, selectedFilter)
        elif fileFormat != FILE_FORMAT_NONE:
            validExts = [x.lstrip("*") for x in selectedFilter.rsplit("(", 1)[1].rsplit(")", 1)[0].split()]
            if ext not in validExts:
                if len(validExts) == 1 and validExts[0]:
                    # Just add the extension since it can't be anything else.
                    filePath += validExts[0]
                    modifiedExt = True
                elif fileFormat == FILE_FORMAT_TXT:
                    # Allow any (or no) extension for plain text files.
                    # Set the file format back to none since we don't treat these any differently yet.
                    fileFormat = FILE_FORMAT_NONE
                else:
                    self.showCriticalMessage("Please enter a valid extension for {}".format(selectedFilter))
                    return self.getSaveAsPath(filePath, tab, selectedFilter)

        info = QtCore.QFileInfo(filePath)
        self.lastOpenFileDir = info.absoluteDir().path()

        # Only needed if we're modifying the extension ourselves; otherwise, Qt handles this.
        # If this file already exists, make sure we want to overwrite it.
        if modifiedExt and info.exists():
            dlg = QtWidgets.QMessageBox.question(
                self, "Save File As",
                "The file already exists. Are you sure you wish to overwrite it?\n{}".format(filePath),
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel)
            if dlg != QtWidgets.QMessageBox.Save:
                # Re-open this dialog to get a new path.
                return self.getSaveAsPath(path, tab, selectedFilter)

        # Now we have a valid path to save as.
        return filePath, fileFormat

    @Slot(bool)
    def saveFileAs(self, checked=False, tab=None):
        """ Save the current file with a new filename.

        :Parameters:
            checked : `bool`
                For signal only
            tab : `BrowserTab` | None
                Tab to save. Defaults to current tab.
        :Returns:
            If saved or not.
        :Rtype:
            `bool`
        """
        tab = tab or self.currTab
        filePath, fileFormat = self.getSaveAsPath(tab=tab)
        if filePath is not None:
            # Save file and apply new name where needed.
            if self.saveFile(filePath, fileFormat, tab=tab):
                idx = self.tabWidget.indexOf(tab)
                fileInfo = QtCore.QFileInfo(filePath)
                fileName = fileInfo.fileName()
                ext = fileInfo.suffix()
                self.tabWidget.setTabText(idx, fileName)
                url = QtCore.QUrl.fromLocalFile(filePath)
                tab.updateHistory(url)
                tab.updateFileStatus()
                self.updateRecentMenus(url, url.toString())
                self.setHighlighter(ext, tab=tab)

                # Get the new parser if we changed from usdc to usda, usd(a) to usdc, etc.
                self.updateTabParser(tab, fileInfo, url, fileFormat)

                # Update UI items that depend on the parser or file format.
                if tab.parser.binary:
                    self.tabWidget.setTabToolTip(idx, "{} - {} (binary)".format(fileName, filePath))
                elif tab.fileFormat == FILE_FORMAT_USDZ:
                    self.tabWidget.setTabToolTip(idx, "{} - {} (zip)".format(fileName, filePath))
                else:
                    self.tabWidget.setTabToolTip(idx, "{} - {}".format(fileName, filePath))
                self.tabWidget.setTabIcon(idx, tab.parser.icon)
                if tab == self.currTab:
                    self.updateButtons()
                return True
        return False

    @Slot()
    def saveLinkAs(self):
        """ The user right-clicked a link and wants to save it as a new file.
        Get a new file path with the Save As dialog and copy the original file to the new file,
        opening the new file in a new tab.
        """
        path = self.linkHighlighted.toLocalFile()
        if "*" in path or "<UDIM>" in path:
            self.showWarningMessage("Link could not be resolved as it may point to multiple files.")
            return

        qFile = QtCore.QFile(path)
        if qFile.exists():
            saveAsPath, fileFormat = self.getSaveAsPath(path)
            if saveAsPath is not None:
                try:
                    url = QtCore.QUrl.fromLocalFile(saveAsPath)
                    if fileFormat == self.currTab.fileFormat:
                        qFile.copy(saveAsPath)
                        self.setSource(url, newTab=True)
                    else:
                        # Open the link first, so it's easier to use the saveFile functionality to handle format
                        # conversion.
                        self.setSource(self.linkHighlighted, newTab=True)
                        self.saveFile(saveAsPath, fileFormat)
                        self.setSource(url)
                except Exception:
                    self.showCriticalMessage("Unable to save {} as {}.".format(path, saveAsPath),
                                             traceback.format_exc(), "Save Link As")
        else:
            self.showWarningMessage("Selected file does not exist.")

    @Slot(bool)
    def saveTab(self, checked=False, tab=None):
        """ If the file already has a name, save it; otherwise, get a filename and save it.

        :Parameters:
            checked : `bool`
                For signal only
            tab : `BrowserTab` | None
                Tab to save. Defaults to current tab.
        :Returns:
            If saved or not.
        :Rtype:
            `bool`
        """
        tab = tab or self.currTab
        filePath = tab.getCurrentPath()
        if filePath:
            return self.saveFile(filePath, tab=tab)
        return self.saveFileAs(tab=tab)

    @Slot(bool)
    def printDialog(self, checked=False):
        """ Open a print dialog.

        :Parameters:
            checked : `bool`
                For signal only
        """
        if QtPrintSupport is None:
            self.showWarningMessage("Printing is not supported on your system, as Qt.QtPrintSupport could not be "
                                    "imported.")
            return
        dlg = QtPrintSupport.QPrintDialog(self)
        if self.currTab.getCurrentTextWidget().textCursor().hasSelection():
            dlg.setOption(dlg.PrintSelection)
        if dlg.exec_() == dlg.Accepted:
            self.currTab.getCurrentTextWidget().print_(dlg.printer())

    @Slot(bool)
    def printPreview(self, checked=False):
        """ Open a print preview dialog.

        :Parameters:
            checked : `bool`
                For signal only
        """
        if QtPrintSupport is None:
            self.showWarningMessage("Printing is not supported on your system, as Qt.QtPrintSupport could not be "
                                    "imported.")
            return
        dlg = QtPrintSupport.QPrintPreviewDialog(self)
        if self.currTab.getCurrentTextWidget().textCursor().hasSelection():
            # TODO: Is there a way to expose this as a toggle in the print
            # preview dialog, since it might not always be desired?
            dlg.printer().setPrintRange(QtPrintSupport.QPrinter.Selection)
        dlg.paintRequested.connect(self.currTab.getCurrentTextWidget().print_)
        dlg.exec_()

    @Slot(bool)
    def closeTab(self, checked=False, index=None):
        """ Close the current tab.

        :Parameters:
            checked : `bool`
                For signal only
            index : `int` | None
                Try to close this specific tab instead of where the context menu originated.
        :Returns:
            If the tab was closed or not.
            If the tab needed to be saved, for example, and the user cancelled, this returns False.
        :Rtype:
            `bool`
        """
        prevTab = None
        if index is None:
            prevTab = None
            if self.contextMenuPos is not None:
                # Grab tab at the position of latest context menu.
                tab = self.tabWidget.tabBar.tabAt(self.contextMenuPos)
                if tab != -1:
                    # Store previous tab so we can switch back to it.
                    prevTab = self.tabWidget.currentWidget()
                    self.tabWidget.setCurrentIndex(tab)
                else:
                    # Don't close anything.
                    # Clicked somewhere on the tab bar where there isn't a tab.
                    return False
        else:
            if index != self.tabWidget.currentIndex():
                prevTab = self.tabWidget.currentWidget()
            self.tabWidget.setCurrentIndex(index)

        # Check if the current tab is dirty. Saves if needed.
        if not self.dirtySave():
            return False
        # Closing the last of our tabs.
        if self.tabWidget.count() == 1:
            self.newTab()
            self.removeTab(0)
        # Closing a tab, but not the last one.
        else:
            self.removeTab(self.tabWidget.currentIndex())
            # Switch back to the previous tab.
            if prevTab is not None:
                self.changeTab(prevTab)
        return True

    @Slot(bool)
    def closeOtherTabs(self, *args):
        """ Close all tabs except the current tab.
        """
        # Grab tab at the position of latest context menu.
        # This is the one tab we'll keep. All others will be closed.
        if self.contextMenuPos is None:
            return

        indexToKeep = self.tabWidget.tabBar.tabAt(self.contextMenuPos)
        if indexToKeep == -1:
            # The user clicked on the tab bar where there isn't a tab.
            return

        indexToRm = 0
        while indexToRm < self.tabWidget.count():
            if indexToRm < indexToKeep:
                if self.closeTab(index=indexToRm):
                    # We successfully removed another tab, so the index of the
                    # one we want to keep decreases.
                    indexToKeep -= 1
                else:
                    # We did not remove a tab (maybe the user didn't want to
                    # save it yet), so up the index we're trying to remove.
                    indexToRm += 1
            elif indexToRm == indexToKeep:
                # Skip this one.
                indexToRm += 1
            elif not self.closeTab(index=indexToRm):
                indexToRm += 1

    @Slot(bool)
    def closeRightTabs(self, *args):
        """ Close all tabs to the right of the current tab.
        """
        # Grab tab at the position of latest context menu.
        # This is the one tab we'll keep. All others will be closed.
        if self.contextMenuPos is None:
            return

        indexToKeep = self.tabWidget.tabBar.tabAt(self.contextMenuPos)
        if indexToKeep == -1:
            # The user clicked on the tab bar where there isn't a tab.
            return

        indexToRm = indexToKeep + 1
        while indexToRm < self.tabWidget.count():
            if not self.closeTab(index=indexToRm):
                indexToRm += 1

    @Slot(int, int)
    def moveTab(self, fromIndex, toIndex):
        """ Rearrange tabs in menu after a drag/drop event.
        This isn't moving the tab itself. That's handled in the TabWidget class.

        :Parameters:
            fromIndex : `int`
                Original tab position
            toIndex : `int`
                New tab position
        """
        actions = self.menuTabList.actions()
        action = actions[fromIndex]
        self.menuTabList.removeAction(action)
        # Moving to a higher index.
        if toIndex > fromIndex:
            # Insert before another action.
            if toIndex+1 < len(actions):
                beforeAction = actions[toIndex+1]
                self.menuTabList.insertAction(beforeAction, action)
            # Add to end of actions.
            else:
                self.menuTabList.addAction(action)
        # Moving to a lower index.
        else:
            beforeAction = actions[toIndex]
            self.menuTabList.insertAction(beforeAction, action)

    @Slot(int, int, int, int)
    def moveTabAcrossWindows(self, fromIndex, toIndex, fromWindow, toWindow):
        """ Rearrange tabs in menu after a drag/drop event.
        This isn't moving the tab itself. That's handled in the TabWidget class.

        :Parameters:
            fromIndex : `int`
                Original tab position
            toIndex : `int`
                New tab position
        """
        logger.debug("moveTabAcrossWindows %d %d %d %d", fromIndex, toIndex, fromWindow, toWindow)

        srcWindow = self.app._windows[fromWindow]
        dstWindow = self.app._windows[toWindow]

        # Remove from the source window's current tab list.
        action = srcWindow.menuTabList.actions()[fromIndex]
        srcWindow.menuTabList.removeAction(action)

        # Remove from the source window's tab widget.
        tab = srcWindow.tabWidget.widget(fromIndex)
        text = srcWindow.tabWidget.tabText(fromIndex)
        icon = srcWindow.tabWidget.tabIcon(fromIndex)
        if srcWindow.tabWidget.count() == 1:
            # We're removing the last tab. Add a new, blank tab first.
            srcWindow.newTab()
        srcWindow.tabWidget.removeTab(fromIndex)
        srcWindow.disconnectTabSignals(tab)

        # Add to the destination window.
        dstWindow.tabWidget.setCurrentIndex(dstWindow.tabWidget.insertTab(toIndex, tab, icon, text))

        # Update menu actions in destination window.
        actions = dstWindow.menuTabList.actions()
        if toIndex >= len(actions):
            dstWindow.menuTabList.addAction(action)
        else:
            beforeAction = actions[toIndex]
            dstWindow.menuTabList.insertAction(beforeAction, action)
        dstWindow.connectTabSignals(tab)

        # Use the new window's syntax highlighter.
        fileInfo = QtCore.QFileInfo(tab.getCurrentPath())
        ext = fileInfo.suffix()
        dstWindow.setHighlighter(ext, tab=tab)

    def removeTab(self, index):
        """ Stores as recently closed tab, then closes it.

        :Parameters:
            index : `int`
                Index of tab to remove.
        """
        # Get tab we're about to remove.
        tab = self.tabWidget.widget(index)

        # Remove from tab widget.
        self.tabWidget.removeTab(index)

        # Remove from current tab list.
        action = self.menuTabList.actions()[index]
        self.menuTabList.removeAction(action)

        if tab.isNewTab:
            # Clear memory
            del tab
        else:
            # Set tab inactive.
            tab.isActive = False
            # Get rid of the oldest tab if we already have the max.
            tabActions = self.menuRecentlyClosedTabs.actions()
            if len(tabActions) > RECENT_TABS - 1:
                self.menuRecentlyClosedTabs.removeAction(tabActions[0])
            del tabActions
            # Add to recently closed tab list.
            self.menuRecentlyClosedTabs.addAction(action)
            self.menuRecentlyClosedTabs.setEnabled(True)

    ###
    # Edit Menu Methods
    ###

    @Slot(bool)
    def toggleEdit(self, checked=False, tab=None):
        """ Switch between Browse mode and Edit mode.

        :Parameters:
            checked : `bool`
                Unused. For signal/slot only
            tab : `BrowserTab`
                Tab to toggle edit mode on
        :Returns:
            True if we switched modes; otherwise, False.
            This only returns False if we were in Edit mode and the user cancelled due to unsaved changes.
        :Rtype:
            `bool`
        """
        tab = tab or self.currTab

        # Don't change between browse and edit mode if dirty. Saves if needed.
        if not self.dirtySave(tab=tab):
            return False

        refreshed = False

        # Toggle edit mode
        tab.inEditMode = not tab.inEditMode
        if tab.inEditMode:
            # Set editor's scroll position to browser's position.
            hScrollPos = tab.textBrowser.horizontalScrollBar().value()
            vScrollPos = tab.textBrowser.verticalScrollBar().value()
            tab.textBrowser.setVisible(False)
            tab.textEditor.setVisible(True)
            tab.textEditor.setFocus()
            tab.textEditor.horizontalScrollBar().setValue(hScrollPos)
            tab.textEditor.verticalScrollBar().setValue(vScrollPos)
        else:
            # Set browser's scroll position to editor's position.
            hScrollPos = tab.textEditor.horizontalScrollBar().value()
            vScrollPos = tab.textEditor.verticalScrollBar().value()

            # TODO: If we edited the file (or it changed on disk since we loaded it, even if the user ignored the
            # prompt to reload it?), make sure we reload it in the browser tab. Currently, we just always reload it to
            # be safe, but this can be slow.
            refreshed = self.refreshTab(tab=tab)

            tab.textEditor.setVisible(False)
            tab.textBrowser.setVisible(True)
            tab.textBrowser.setFocus()
            tab.textBrowser.horizontalScrollBar().setValue(hScrollPos)
            tab.textBrowser.verticalScrollBar().setValue(vScrollPos)

        # Don't double-up the below commands if we already refreshed the tab.
        if not refreshed:
            # Update highlighter.
            tab.highlighter.setDocument(tab.getCurrentTextWidget().document())
            if tab == self.currTab:
                self.updateEditButtons()

        self.findRehighlightAll()
        if tab == self.currTab:
            self.editModeChanged.emit(tab.inEditMode)
        return True

    @Slot()
    def undo(self):
        """ Undo last change in the current text editor.
        """
        self.currTab.textEditor.undo()

    @Slot()
    def redo(self):
        """ Redo last change in the current text editor.
        """
        self.currTab.textEditor.redo()

    @Slot()
    def cut(self):
        """ Cut selected text in the current text editor.
        """
        self.currTab.textEditor.cut()
        if self.currTab.inEditMode:
            self.actionPaste.setEnabled(True)

    @Slot()
    def copy(self):
        """ Copy selected text in the current text editor.
        """
        self.currTab.getCurrentTextWidget().copy()
        if self.currTab.inEditMode:
            self.actionPaste.setEnabled(True)

    @Slot()
    def paste(self):
        """ Paste selected text in the current text editor.
        """
        self.currTab.textEditor.paste()

    @Slot()
    def selectAll(self):
        """ Select all text in the current focused widget.
        """
        if self.addressBar.hasFocus():
            self.addressBar.selectAll()
        elif self.findBar.hasFocus():
            self.findBar.selectAll()
        elif self.includeWidget.fileNameEdit.hasFocus():
            self.includeWidget.fileNameEdit.selectAll()
        else:
            self.currTab.getCurrentTextWidget().selectAll()

    @Slot()
    def toggleFind(self):
        """ Show/Hide the Find bar.
        """
        self.findWidget.setVisible(True)
        self.findBar.selectAll()
        self.findBar.setFocus()

        # Pre-populate the Find field with the current selection, if any.
        text = self.currTab.getCurrentTextWidget().textCursor().selectedText()
        if text:
            # Currently, find doesn't work with line breaks, so use the last line that contains any text.
            text = [x for x in text.split(u'\u2029') if x][-1]
            self.findBar.setText(text)
            self.findBar.selectAll()
            self.validateFindBar(text)

    @Slot()
    def toggleFindClose(self):
        """ Hide the Find bar.
        """
        self.findWidget.setVisible(False)

    @Slot()
    @Slot(bool)
    def find(self, checked=False, flags=None, startPos=3, loop=True):
        """ Find next hit for the search text.

        :Parameters:
            checked : `bool`
                For signal only
            flags
                Options for document().find().
            startPos : `int`
                Position from which the search should begin.
                0=Start of document
                1=End of document
                2=Start of selection
                3=End of selection (default)
            loop : `bool`
                True lets us loop through the beginning or end of a document
                if the phrase was not found from the current position.
                False limits that behavior so that we don't endlessly loop.
        """
        # Set options.
        if flags is None:
            searchFlags = QtGui.QTextDocument.FindFlags()
        else:
            searchFlags = flags
        if self.preferences['findMatchCase']:
            searchFlags |= QtGui.QTextDocument.FindCaseSensitively

        currTextWidget = self.currTab.getCurrentTextWidget()

        # Set where to start searching from.
        if startPos == 0:
            currPos = 0
        elif startPos == 1:
            # Moving our current cursor doesn't work, so create a temporary one to find the end of the document.
            tmpCursor = QtGui.QTextCursor(currTextWidget.document())
            tmpCursor.movePosition(QtGui.QTextCursor.End)
            currPos = tmpCursor.position()
            del tmpCursor
        elif startPos == 2:
            currPos = currTextWidget.textCursor().selectionStart()
        else:  # startPos == 3
            currPos = currTextWidget.textCursor().selectionEnd()

        # Find text.
        cursor = currTextWidget.document().find(self.findBar.text(), currPos, searchFlags)

        if cursor.hasSelection():
            # Found phrase. Set cursor and formatting.
            currTextWidget.setTextCursor(cursor)
            self.findBar.setStyleSheet("QLineEdit{{background:{}}}".format("inherit" if self.isDarkTheme() else "none"))
            if loop:
                # Didn't just loop through the document, so hide any messages.
                self.labelFindPixmap.setVisible(False)
                self.labelFindStatus.setVisible(False)
        elif loop:
            self.labelFindPixmap.setPixmap(self.browserReloadIcon.pixmap(16, 16))
            self.labelFindStatus.setText("Search wrapped")
            self.labelFindPixmap.setVisible(True)
            self.labelFindStatus.setVisible(True)
            # loop = False because we don't want to create an infinite recursive search.
            if searchFlags & QtGui.QTextDocument.FindBackward:
                self.find(flags=QtGui.QTextDocument.FindBackward, startPos=1, loop=False)
            else:
                self.find(startPos=0, loop=False)
        else:
            # If nothing was still found, set formatting.
            self.labelFindPixmap.setPixmap(self.browserStopIcon.pixmap(16, 16))
            self.labelFindStatus.setText("Phrase not found")
            self.labelFindPixmap.setVisible(True)
            self.labelFindStatus.setVisible(True)
            self.findBar.setStyleSheet("QLineEdit{background:salmon}")
        if self.buttonHighlightAll.isChecked():
            self.findHighlightAll()

    @Slot()
    def findPrev(self):
        """ Find previous hit for the search text.
        """
        self.find(flags=QtGui.QTextDocument.FindBackward, startPos=2)

    @Slot(bool)
    def findHighlightAll(self, checked=True):
        """ Highlight all hits for the search text.

        :Parameters:
            checked : `bool`
                If True, highlight all occurrences of the current find phrase.
        """
        findText = self.findBar.text()
        textWidget = self.currTab.getCurrentTextWidget()
        extras = [x for x in textWidget.extraSelections() if
                  x.format.property(QtGui.QTextFormat.UserProperty) != "find"]
        if checked and findText:
            flags = QtGui.QTextDocument.FindFlags()
            if self.preferences['findMatchCase']:
                flags |= QtGui.QTextDocument.FindCaseSensitively
            doc = textWidget.document()
            cursor = QtGui.QTextCursor(doc)
            lineColor = QtGui.QColor(QtCore.Qt.yellow)
            count = 0
            while True:
                cursor = doc.find(findText, cursor, flags)
                if cursor.isNull():
                    break
                selection = QtWidgets.QTextEdit.ExtraSelection()
                selection.format.setBackground(lineColor)
                selection.format.setProperty(QtGui.QTextFormat.UserProperty, "find")
                selection.cursor = cursor
                extras.append(selection)
                count += 1
            logger.debug("Find text found %s time%s", count, '' if count == 1 else 's')
        textWidget.setExtraSelections(extras)

    def findRehighlightAll(self):
        """ Rehighlight all occurrences of the find phrase when the active document changes.
        """
        if self.buttonHighlightAll.isEnabled() and self.buttonHighlightAll.isChecked():
            self.findHighlightAll()

    @Slot()
    def showFindReplaceDlg(self):
        """ Show the Find/Replace dialog.
        """
        if self.findDlg is not None:
            self.findDlg.deleteLater()
        self.findDlg = FindDialog(self)

        # Connect signals.
        self.findDlg.findBtn.clicked.connect(self.find2)
        self.findDlg.replaceBtn.clicked.connect(self.replace)
        self.findDlg.replaceFindBtn.clicked.connect(self.replaceFind)
        self.findDlg.replaceAllBtn.clicked.connect(self.replaceAll)
        self.findDlg.replaceAllOpenBtn.clicked.connect(self.replaceAllInOpenFiles)

        # Make sure the dialog updates if the edit mode of the current tab changes.
        self.findDlg.updateForEditMode(self.currTab.inEditMode)
        self.editModeChanged.connect(self.findDlg.updateForEditMode)

        # Open dialog.
        self.findDlg.show()

    @Slot()
    def find2(self, startPos=3, loop=True, findText=None, tab=None):
        """
        Find functionality for find/replace dialog.

        :Parameters:
            startPos : `int`
                Position from which the search should begin.
                0=Start of document
                1=End of document
                2=Start of selection
                3=End of selection (default)
            loop : `bool`
                True lets us loop through the beginning or end of a document
                if the phrase was not found from the current position.
                False limits that behavior so that we don't endlessly loop.
            findText : `str`
                Text to find.
            tab : `BrowserTab` | None
                Tab. Defaults to current tab if None.
        """
        tab = tab or self.currTab

        # Set options.
        searchFlags = self.findDlg.searchFlags()
        if self.findDlg.searchBackwardsCheck.isChecked() and startPos == 3:
            startPos = 2

        currTextWidget = tab.getCurrentTextWidget()

        # Set where to start searching from.
        if startPos == 0:
            currPos = 0
        elif startPos == 1:
            # Moving our current cursor doesn't work, so create a temporary one to find the end of the document.
            tmpCursor = QtGui.QTextCursor(currTextWidget.document())
            tmpCursor.movePosition(QtGui.QTextCursor.End)
            currPos = tmpCursor.position()
            del tmpCursor
        elif startPos == 2:
            currPos = currTextWidget.textCursor().selectionStart()
        else:  # startPos == 3
            currPos = currTextWidget.textCursor().selectionEnd()

        # Find text.
        if findText is None:
            findText = self.getFindText()
        cursor = currTextWidget.document().find(findText, currPos, searchFlags)

        if cursor.hasSelection():
            # Found phrase. Set cursor and formatting.
            currTextWidget.setTextCursor(cursor)
            self.findDlg.statusBar.clearMessage()
            self.findDlg.setStyleSheet("QLineEdit#findLineEdit{background:none}")
            return True
        elif loop:
            # loop = False because we don't want to create an infinite recursive search.
            startPos = 1 if (searchFlags & QtGui.QTextDocument.FindBackward) else 0
            return self.find2(startPos=startPos, loop=False, tab=tab)
        else:
            self.findDlg.statusBar.showMessage("Phrase not found")
            self.findDlg.setStyleSheet("QLineEdit#findLineEdit{background:salmon}")
            return False

    @Slot()
    def replace(self, findText=None, replaceText=None, tab=None):
        """ Replace next hit for the search text.

        :Parameters:
            findText : `str` | None
                Text to find.
                Defaults to getting text from Find/Replace dialog.
            replaceText : `str` | None
                Text to replace it with.
                Defaults to getting text from Find/Replace dialog.
            tab : `BrowserTab` | None
                Tab to replace text in. Defaults to current tab if None.
        """
        tab = tab or self.currTab

        if findText is None:
            findText = self.getFindText()
        if replaceText is None:
            replaceText = self.getReplaceText()

        # If we already have a selection.
        cursor = tab.textEditor.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == findText:
            tab.textEditor.insertPlainText(replaceText)
            self.findDlg.statusBar.showMessage("1 occurrence replaced.")
        # If we don't have a selection, try to get a new one.
        elif self.find2(findText, tab=tab):
            self.replace(findText, replaceText, tab=tab)

    @Slot()
    def replaceFind(self):
        """ Replace next hit for the search text, then find the next after that.
        """
        self.replace()
        self.find2()

    @Slot()
    def replaceAll(self, findText=None, replaceText=None, tab=None, report=True):
        """ Replace all occurrences of the search text.

        :Parameters:
            findText : `str` | None
                Text to find. If None, get the value from the Find/Replace dialog.
            replaceText : `str` | None
                Text to replace. If None, get the value from the Find/Replace dialog.
            tab : `TabWidget` | None
                Tab to replace text in. Defaults to current tab.
            report : `bool`
                If True, report replace statistics; otherwise, just return the number of replacements.
        :Returns:
            Number of replacements
        :Rtype:
            `int`
        """
        count = 0
        with self.overrideCursor():
            findText = findText if findText is not None else self.getFindText()
            replaceText = replaceText if replaceText is not None else self.getReplaceText()
            tab = tab or self.currTab
            # Make sure we don't use the FindBackward flag. While direction doesn't really matter since all occurrences
            # are getting replaced, it doesn't work with this simplified, fast logic.
            flags = self.findDlg.searchFlags() & ~QtGui.QTextDocument.FindBackward
            editor = tab.getCurrentTextWidget()
            editor.textCursor().beginEditBlock()
            doc = editor.document()
            cursor = QtGui.QTextCursor(doc)
            while True:
                cursor = doc.find(findText, cursor, flags)
                if cursor.isNull():
                    break
                cursor.insertText(replaceText)
                count += 1
            editor.textCursor().endEditBlock()

        if report:
            if count > 0:
                self.findDlg.setStyleSheet("QLineEdit#findLineEdit{background:none}")
                self.findDlg.statusBar.showMessage("{} occurrence{} replaced.".format(count, '' if count == 1 else 's'))
            else:
                self.findDlg.statusBar.showMessage("Phrase not found. 0 occurrences replaced.")
        return count

    @Slot()
    def replaceAllInOpenFiles(self):
        """ Iterate through all the writable tabs, finding and replacing the search text.
        """
        count = files = 0

        with self.overrideCursor():
            findText = self.getFindText()
            replaceText = self.getReplaceText()
            for tab in self.tabIterator():
                status = tab.getFileStatus()
                if not status.writable:
                    continue
                if not tab.inEditMode:
                    self.toggleEdit(tab=tab)
                thisCount = self.replaceAll(findText, replaceText, tab, report=False)
                if thisCount:
                    files += 1
                    count += thisCount

        if count > 0:
            self.findDlg.setStyleSheet("QLineEdit#findLineEdit{background:none}")
            self.findDlg.statusBar.showMessage("{} occurrence{} replaced in {} file{}.".format(
                count, '' if count == 1 else 's', files, '' if files == 1 else 's'))
        else:
            self.findDlg.statusBar.showMessage("Phrase not found. 0 occurrences replaced.")

    def findAndReplace(self, findText, replaceText, tab, startPos=0):
        """ Replace a single occurrence of a phrase.

        :Parameters:
            findText : `str`
                Text to find
            replaceText : `str`
                Text to replace with
            startPos : `int`
                Position from which the search should begin.
                0=Start of document (default)
                1=End of document
                2=Start of selection
                3=End of selection

        :Returns:
            Whether or not a match was found.

        :Rtype:
            `bool`
        """
        # Find one occurrence...
        if self.find2(startPos=startPos, loop=False, findText=findText, tab=tab):
            # ...and replace it.
            cursor = tab.textEditor.textCursor()
            if cursor.hasSelection() and cursor.selectedText() == findText:
                tab.textEditor.insertPlainText(replaceText)
            return True
        return False

    def getFindText(self):
        """ Get the text to find.

        :Returns:
            The search text from the Find/Replace dialog.
        :Rtype:
            `str`
        """
        return self.findDlg.findLineEdit.text()

    def getReplaceText(self):
        """ Get the text to replace the search text with.

        :Returns:
            The replace text from the Find/Replace dialog.
        :Rtype:
            `str`
        """
        return self.findDlg.replaceLineEdit.text()

    @Slot()
    def goToLineNumberDlg(self):
        """
        Get a line number from the user and scroll to it.
        """
        textWidget = self.currTab.getCurrentTextWidget()
        currLine = textWidget.textCursor().blockNumber() + 1
        maxLine = textWidget.document().blockCount()
        # Get line number. Current = current line, min = 1, max = number of lines.
        line = QtWidgets.QInputDialog.getInt(self, "Go To Line Number", "Line number:", currLine, 1, maxLine)
        if line[1]:
            self.currTab.goToLineNumber(line[0])

    def goToLineNumber(self, line=1):
        """ Go to the given line number

        :Parameters:
            line : `int`
                Line number to scroll to. Defaults to 1 (top of document).
        """
        warnings.warn(
            "goToLineNumber has been deprecated. Call this same method on the BrowserTab object itself.",
            DeprecationWarning
        )
        self.currTab.goToLineNumber(line)

    def tabIterator(self):
        """ Iterator through the tab widgets. """
        for i in range(self.tabWidget.count()):
            yield self.tabWidget.widget(i)

    @Slot()
    def editPreferences(self):
        """ Open Preferences dialog """
        dlg = PreferencesDialog(self)
        # Open dialog.
        if dlg.exec_() == dlg.Accepted:
            # Users currently have to refresh to see these changes.
            self.preferences['parseLinks'] = dlg.getPrefParseLinks()
            self.preferences['syntaxHighlighting'] = dlg.getPrefSyntaxHighlighting()
            self.preferences['teletype'] = dlg.getPrefTeletypeConversion()
            self.preferences['theme'] = dlg.getPrefTheme()

            # These changes do not require the user to refresh any tabs to see the change.
            self.preferences['newTab'] = dlg.getPrefNewTab()
            self.preferences['lineNumbers'] = dlg.getPrefLineNumbers()
            self.preferences['showAllMessages'] = dlg.getPrefShowAllMessages()
            self.preferences['showHiddenFiles'] = dlg.getPrefShowHiddenFiles()
            self.preferences['autoCompleteAddressBar'] = dlg.getPrefAutoCompleteAddressBar()
            self.preferences['textEditor'] = dlg.getPrefTextEditor()
            self.preferences['diffTool'] = dlg.getPrefDiffTool()
            self.preferences['font'] = dlg.getPrefFont()
            self.preferences['useSpaces'] = dlg.getPrefUseSpaces()
            self.preferences['tabSpaces'] = dlg.getPrefTabSpaces()
            self.preferences['lineLimit'] = dlg.getPrefLineLimit()
            self.preferences['autoIndent'] = dlg.getPrefAutoIndent()

            # Update font and line number visibility in all tabs.
            self.tabWidget.setFont(self.preferences['font'])
            self.includeWidget.showAll(self.preferences['showHiddenFiles'])

            for w in self.tabIterator():
                w.textBrowser.setFont(self.preferences['font'])
                w.textBrowser.zoomIn(self.preferences['fontSizeAdjust'])
                w.textBrowser.lineNumbers.setVisible(self.preferences['lineNumbers'])
                w.textEditor.setFont(self.preferences['font'])
                w.textEditor.zoomIn(self.preferences['fontSizeAdjust'])
                w.textEditor.lineNumbers.setVisible(self.preferences['lineNumbers'])
                w.setIndentSettings(self.preferences['useSpaces'], self.preferences['tabSpaces'],
                                    self.preferences['autoIndent'])

            programs = dlg.getPrefPrograms()
            if programs != self.programs:
                self.programs = programs
                # Update regex used for searching links.
                self.compileLinkRegEx.emit()
                # Update highlighter.
                for h in self.masterHighlighters.values():
                    h.setLinkPattern(self.programs)

            for h in self.masterHighlighters.values():
                h.setSyntaxHighlighting(self.preferences['syntaxHighlighting'])

            # Enable/Disable completer on address bar.
            if self.preferences['autoCompleteAddressBar']:
                self.addressBar.setCompleter(self.addressBar.customCompleter)
            else:
                self.addressBar.setCompleter(QtWidgets.QCompleter())

            # Save the preferences to disk.
            self.writeSettings()

    def updatePreference(self, key, value):
        """ Update a user preference, setting the preferences dict and updating the config file.

        :Parameters:
            key : `str`
                Preference key
            value
                Serializable preference value
        """
        self.preferences[key] = value
        self.config.setValue(key, value)

    @Slot(bool)
    def updatePreference_findMatchCase(self, checked):
        """ Stores a bool representation of checkbox's state.

        :Parameters:
            checked : `bool`
                State of checkbox.
        """
        self.updatePreference('findMatchCase', checked)
        self.findRehighlightAll()

    @Slot(str)
    def validateFindBar(self, text):
        """ Update widgets on the Find bar as the search text changes.

        :Parameters:
            text : `str`
                Current text in the find bar.
        """
        if text:
            self.buttonFindPrev.setEnabled(True)
            self.buttonFindNext.setEnabled(True)
            self.actionFindPrev.setEnabled(True)
            self.actionFindNext.setEnabled(True)
            self.buttonHighlightAll.setEnabled(True)
            self.find(startPos=2)  # Find as user types.
        else:
            self.buttonFindPrev.setEnabled(False)
            self.buttonFindNext.setEnabled(False)
            self.actionFindPrev.setEnabled(False)
            self.actionFindNext.setEnabled(False)
            self.buttonHighlightAll.setEnabled(False)
            if self.buttonHighlightAll.isChecked():
                self.findHighlightAll()
            self.findBar.setStyleSheet("QLineEdit{{background:{}}}".format("inherit" if self.isDarkTheme() else "none"))
            self.labelFindPixmap.setVisible(False)
            self.labelFindStatus.setVisible(False)

    ###
    # View Menu Methods
    ###

    @Slot(bool)
    def toggleInclude(self, checked):
        """ Show/Hide the side file browser.

        :Parameters:
            checked : `bool`
                State of checked menu.
        """
        self.updatePreference('includeVisible', checked)
        self.mainWidget.setSizes([1 if checked else 0, 1500])

    @Slot(int, int)
    def setIncludePanelActionState(self, pos=0, index=0):
        """ Set the check state of the include panel action.
        If it is visible, the action will be checked.

        :Parameters:
            pos : `int`
                Position from left edge of widget. For catching signal only.
            index : `int`
                Splitter handle index. For catching signal only.
        """
        self.actionIncludePanel.setChecked(self.mainWidget.sizes()[0] != 0)

    @Slot()
    def duplicateTab(self):
        """ Duplicate the tab that was right-clicked.
        This doesn't duplicate edit state or any history at the moment.
        """
        origIndex = self.tabWidget.tabBar.tabAt(self.contextMenuPos)
        url = self.tabWidget.widget(origIndex).getCurrentUrl()

        # Create a new tab and select it, positioning it immediately after the original tab.
        self.newTab()
        fromIndex = self.tabWidget.currentIndex()
        toIndex = origIndex + 1
        if fromIndex != toIndex:
            self.tabWidget.moveTab(fromIndex, toIndex)

        # Open the same document as the original tab.
        if not url.isEmpty():
            # TODO: Should we copy some of the data instead of reloading from disk?
            self.setSource(url)

    @Slot()
    def refreshSelectedTab(self):
        """ Refresh the tab that was right-clicked.
        """
        selectedIndex = self.tabWidget.tabBar.tabAt(self.contextMenuPos)
        selectedTab = self.tabWidget.widget(selectedIndex)
        self.refreshTab(tab=selectedTab)

    @Slot()
    @Slot(bool)
    def refreshTab(self, checked=False, tab=None):
        """ Reload the file for a tab.

        :Parameters:
            checked : `bool`
                For signal only
            tab : `BrowserTab` | None
                Tab to refresh. Defaults to current tab if None.
        :Returns:
            If the tab was reloaded successfully.
        :Rtype:
            `bool`
        """
        # Only refresh the tab if the refresh action is enabled, since the F5 shortcut is never disabled,
        # and methods sometimes call this directly even though we do not want to refresh.
        if self.actionRefresh.isEnabled():
            tab = tab or self.currTab
            status = self.setSource(tab.getCurrentUrl(), isNewFile=False,
                                    hScrollPos=tab.getCurrentTextWidget().horizontalScrollBar().value(),
                                    vScrollPos=tab.getCurrentTextWidget().verticalScrollBar().value(),
                                    tab=tab)
            return status
        return False

    @Slot()
    def increaseFontSize(self):
        """ Increase font size in the text browser and editor.
        """
        self.updatePreference('fontSizeAdjust', self.preferences['fontSizeAdjust'] + 1)
        for w in self.tabIterator():
            w.textBrowser.zoomIn()
            w.textEditor.zoomIn()

    @Slot()
    def decreaseFontSize(self):
        """ Decrease font size in the text browser and editor.
        """
        # Don't allow zooming to zero or lower. While the widgets already block this safely, we don't want our font
        # size adjustment to get larger even when the document font size isn't getting smaller than 1.
        size = self.currTab.getCurrentTextWidget().document().defaultFont().pointSize()
        if size + self.preferences['fontSizeAdjust'] <= 1:
            return
        self.updatePreference('fontSizeAdjust', self.preferences['fontSizeAdjust'] - 1)
        for w in self.tabIterator():
            w.textBrowser.zoomOut()
            w.textEditor.zoomOut()

    @Slot()
    def defaultFontSize(self):
        """ Reset the text browser and editor to the default font size.
        """
        for w in self.tabIterator():
            w.textBrowser.zoomIn(-self.preferences['fontSizeAdjust'])
            w.textEditor.zoomIn(-self.preferences['fontSizeAdjust'])
        self.updatePreference('fontSizeAdjust', 0)

    @Slot(bool)
    def toggleFullScreen(self, *args):
        """ Toggle between full screen mode
        """
        self.setWindowState(self.windowState() ^ QtCore.Qt.WindowFullScreen)

    ###
    # History Menu Methods
    ###

    @Slot()
    def browserBack(self):
        """ Go back one step in history for the current tab.
        """
        # Check if there are any changes to be saved before we modify the history.
        if not self.dirtySave():
            return
        self.currTab.goBack()

    @Slot()
    def browserForward(self):
        """ Go forward one step in history for the current tab.
        """
        # Check if there are any changes to be saved before we modify the history.
        if not self.dirtySave():
            return
        self.currTab.goForward()

    @Slot(QtWidgets.QWidget)
    def restoreTab(self, tab):
        """ Restore a previously closed tab.

        :Parameters:
            tab : `QtWidgets.QWidget`
                Tab widget
        """
        # Find out if current tab is blank.
        index = -1
        if self.currTab.isNewTab:
            index = self.tabWidget.currentIndex()

        if index != -1:
            logger.debug("Restoring tab at index %d", index)
            # If we had a blank tab to start with, swap it with the new tab.
            # Be sure to add the new tab before removing the old tab so we always have at least one tab.
            self.tabWidget.setCurrentIndex(self.tabWidget.insertTab(index, tab, tab.action.icon(),
                                                                    QtCore.QFileInfo(tab.getCurrentPath()).fileName()))
            self.tabWidget.removeTab(index + 1)
            actions = self.menuTabList.actions()
            oldAction = actions[index]
            self.menuTabList.insertAction(oldAction, tab.action)
            self.menuTabList.removeAction(oldAction)
        else:
            # Add the new tab to the end of the list.
            logger.debug("Restoring tab at end")
            self.tabWidget.setCurrentIndex(self.tabWidget.addTab(tab, tab.action.icon(),
                                                                 QtCore.QFileInfo(tab.getCurrentPath()).fileName()))
            self.menuTabList.addAction(tab.action)

        # Remove the restored tab from the recently closed tabs menu.
        self.menuRecentlyClosedTabs.removeAction(tab.action)

        # Re-activate the restored tab.
        tab.isActive = True

        # Disable menu if there are no more recent tabs.
        if not self.menuRecentlyClosedTabs.actions():
            self.menuRecentlyClosedTabs.setEnabled(False)

        # Update settings in the recently re-opened tab that may have changed.
        if self.preferences['font'] != self.app.DEFAULTS['font']:
            tab.textBrowser.setFont(self.preferences['font'])
            tab.textEditor.setFont(self.preferences['font'])
        tab.textBrowser.lineNumbers.setVisible(self.preferences['lineNumbers'])
        tab.textEditor.lineNumbers.setVisible(self.preferences['lineNumbers'])

        # TODO: If this file doesn't exist or has changed on disk, reload it or warn the user?

    ###
    # Commands Menu Methods
    ###

    @Slot()
    def diffFile(self):
        """ Compare current version of file in app to current version on disk.
        Allows you to make comparisons using a temporary file, without saving your changes.
        """
        path = self.currTab.getCurrentPath()
        if self.currTab.parser.binary:
            path = self.getCachePath(path, self.currTab.parser)

        fd, tmpPath = utils.mkstemp(suffix=QtCore.QFileInfo(path).fileName(), dir=self.app.tmpDir)
        with os.fdopen(fd, 'w') as f:
            f.write(self.currTab.textEditor.toPlainText())
        self.launchPathCommand(self.preferences['diffTool'], [QtCore.QDir.toNativeSeparators(path), tmpPath])

    @staticmethod
    def getPermissionString(path):
        """ Get permissions string for a file's mode.
        Qt.py compatibility fix since QFileInfo.permissions isn't in PySide2.

        :Parameters:
            path : `str`
                File path
        :Returns:
            String corresponding to read (r), write (w), and execute (x) permissions for file.
        """
        mode = os.stat(path)[stat.ST_MODE]
        perms = "-"
        for who in "USR", "GRP", "OTH":
            for what in "R", "W", "X":
                if mode & getattr(stat, "S_I" + what + who):
                    perms += what.lower()
                else:
                    perms += "-"
        return perms

    @Slot()
    def fileInfo(self):
        """ Display information about the current file.
        """
        # Get file information.
        path = self.currTab.getCurrentPath()
        info = QtCore.QFileInfo(path)
        if not info.exists():
            self.showWarningMessage("Selected file does not exist.")
            return
        size = info.size()
        owner = info.owner()
        modified = info.lastModified().toString()
        permissions = self.getPermissionString(path)

        # Create dialog to display info.
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowIcon(self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogInfoView))
        dlg.setWindowTitle("File Information")
        layout = QtWidgets.QGridLayout(dlg)
        labelName = QtWidgets.QLabel("<b>{}</b>".format(info.fileName()))
        labelName.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(labelName, 0, 0, 1, 0)
        labelPath1 = QtWidgets.QLabel("Full path:")
        labelPath2 = QtWidgets.QLabel(QtCore.QDir.toNativeSeparators(path))
        labelSize1 = QtWidgets.QLabel("Size:")
        labelSize2 = QtWidgets.QLabel(utils.humanReadableSize(size))
        labelPermissions1 = QtWidgets.QLabel("Permissions:")
        labelPermissions2 = QtWidgets.QLabel(permissions)
        labelOwner1 = QtWidgets.QLabel("Owner:")
        labelOwner2 = QtWidgets.QLabel(owner)
        labelModified1 = QtWidgets.QLabel("Modified:")
        labelModified2 = QtWidgets.QLabel(modified)
        # Set text interaction.
        labelName.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        labelPath2.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        labelSize2.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        labelPermissions2.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        labelOwner2.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        labelModified2.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        # Add to layout.
        layout.addWidget(labelPath1, 1, 0)
        layout.addWidget(labelPath2, 1, 1)
        layout.addWidget(labelSize1, 2, 0)
        layout.addWidget(labelSize2, 2, 1)
        layout.addWidget(labelPermissions1, 3, 0)
        layout.addWidget(labelPermissions2, 3, 1)
        layout.addWidget(labelOwner1, 4, 0)
        layout.addWidget(labelOwner2, 4, 1)
        layout.addWidget(labelModified1, 5, 0)
        layout.addWidget(labelModified2, 5, 1)
        btnBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        layout.addWidget(btnBox, 6, 0, 1, 0)
        btnBox.accepted.connect(dlg.accept)
        dlg.exec_()

    def getCommentStrings(self):
        """ Get the language-specific string(s) for a comment.

        :Returns:
            Tuple of start `str` and end `str` defining a comment.
        :Rtype:
            `tuple`
        """
        path = self.currTab.getCurrentPath()
        if path:
            ext = QtCore.QFileInfo(path).suffix()
            if ext in self.masterHighlighters:
                extHighlighter = self.masterHighlighters[ext]
                if extHighlighter.comment:
                    return extHighlighter.comment, ""
                elif extHighlighter.multilineComment:
                    return extHighlighter.multilineComment
        # Default to generic USD and Python comments.
        return "#", ""

    @Slot()
    def commentTextRequest(self):
        """ Slot called by the Comment action. """
        self.currTab.getCurrentTextWidget().commentOutText(*self.getCommentStrings())

    @Slot()
    def uncommentTextRequest(self):
        """ Slot called by the Uncomment action. """
        self.currTab.getCurrentTextWidget().uncommentText(*self.getCommentStrings())

    @Slot()
    def indentText(self):
        """ Indent selected lines by one tab stop.
        """
        self.currTab.getCurrentTextWidget().indentText()

    @Slot()
    def unindentText(self):
        """ Un-indent selected lines by one tab stop.
        """
        self.currTab.getCurrentTextWidget().unindentText()

    @Slot()
    def launchTextEditor(self):
        """ Launch the current file in a separate text editing application.
        """
        self.launchPathCommand(self.preferences['textEditor'],
                               QtCore.QDir.toNativeSeparators(self.currTab.getCurrentPath()))

    @Slot()
    def launchUsdView(self):
        """ Launch the current file in usdview.
        """
        self.launchPathCommand(self.app.DEFAULTS['usdview'],
                               QtCore.QDir.toNativeSeparators(self.currTab.getCurrentPath()))

    @Slot(bool)
    def launchProgramOfChoice(self, checked=False, path=None):
        """ Open a file with a program given by the user.

        :Parameters:
            checked : `bool`
                For signal only
            path : `str`
                File to open. If None, use currently open file.
        """
        if path is None:
            path = QtCore.QDir.toNativeSeparators(self.currTab.getCurrentPath())

        # Get program of choice from user.
        prog, ok = QtWidgets.QInputDialog.getText(
            self, "Open with...",
            "Please enter the program you would like to open this file with.\n\nYou may include command line options "
            "as well, and the file path will be appended to the end of the command.\n\nUse {} if the path needs to go "
            "in a specific place within the command.\n\nExample:\n    usdview --unloaded\n    ls {} -l\n",
            QtWidgets.QLineEdit.Normal, self.preferences['lastOpenWithStr'])
        # Return if cancel was pressed or nothing entered.
        if not ok or not prog:
            return

        # Store command for future convenience.
        self.updatePreference('lastOpenWithStr', prog)

        # Launch program.
        self.launchPathCommand(prog, path)

    ###
    # Help Menu Methods
    ###

    @Slot(bool)
    def showAboutDialog(self, *args):
        """ Display a modal dialog box that shows the "about" information for the application.
        """
        from .version import __version__
        captionText = "About {}".format(self.app.appDisplayName)
        aboutText = ("<b>App Name:</b> {0} {1}<br/>"
                     "<b>App Path:</b> {2}<br/>"
                     "<b>Documentation:</b> <a href={3}>{3}</a>".format(
                         self.app.appName, __version__, self.app.appPath, self.app.appURL))
        QtWidgets.QMessageBox.about(self, captionText, aboutText)

    @Slot(bool)
    def showAboutQtDialog(self, *args):
        """ Show Qt about dialog.
        """
        QtWidgets.QMessageBox.aboutQt(self, self.app.appDisplayName)

    @Slot(bool)
    def desktopOpenUrl(self, checked=False, url=None):
        """ Open a URL in a web browser.
        This method doesn't do anything if the URL evaluates to False.

        :Parameters:
            checked : `bool`
                For signal only
            url : `str`
                A URL to open.  If one is not provided, it defaults to
                self.appURL.
        """
        url = url or self.app.appURL
        if url:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))

    ###
    # Extra Keyboard Shortcuts
    ###

    @Slot()
    def onBackspace(self):
        """ Handle the Backspace key for back browser navigation.
        """
        # Need this test since the Backspace keyboard shortcut is always linked to this method.
        if self.currTab.isBackwardAvailable() and not self.currTab.inEditMode:
            self.browserBack()

    ###
    # Miscellaneous Methods
    ###

    def currentlyOpenFiles(self):
        """ Get the currently open files from all tabs.

        :Returns:
            `str` file paths for each open tab
        :Rtype:
            `list`
        """
        return [x.getCurrentPath() for x in self.tabIterator()]

    @Slot(QtCore.QUrl)
    def hoverUrl(self, link):
        """ Slot called when the mouse hovers over a URL.
        """
        path = link.toLocalFile()
        if utils.queryItemBoolValue(link, "binary"):
            self.statusbar.showMessage("{} (binary)".format(path))
        else:
            self.statusbar.showMessage(path)

    @Slot(str)
    def onFileChange(self, path):
        """ Track files that have been modified on disk.

        :Parameters:
            path : `str`
                Modified file path
        """
        logger.debug("onFileChange: %s", path)

        # Check if the file has ACTUALLY changed.
        # We're getting a LOT of false positives with QFileSystemWatcher.
        # Allow changes within the last minute (60,000 milliseconds) (threshold chosen arbitrarily).
        if (QtCore.QFile.exists(path) and
                QtCore.QFileInfo(path).lastModified() < QtCore.QDateTime.currentDateTime().addMSecs(-60000)):
            logger.debug("Ignoring file change since modified time is more than 1 minute ago.")

            # Remove and re-add it so we get notifications again.
            self.fileSystemWatcher.removePath(path)
            self.fileSystemWatcher.addPath(path)
            return

        if path == self.currTab.getCurrentPath():
            # If this is the current tab, pop up a dialog prompting the user if they want to reload.
            self.promptOnFileChange(path)
        else:
            # Otherwise, store this in a list of modified paths. When we switch tabs,
            # if it's a tab whose file has changed, prompt the user to reload the file.
            self.fileSystemModified.add(path)

    def promptOnFileChange(self, path):
        """ Prompt if the file should be reloaded when it has changed on the file system.

        :Parameters:
            path : `str`
                Modified file path
        :Returns:
            True if the user reloaded the file; otherwise, False
        :Rtype:
            `bool`
        """
        # Stop watching this file.
        # If the user reloads, we will start watching the file again.
        if path in self.fileSystemModified:
            self.fileSystemModified.remove(path)
        self.fileSystemWatcher.removePath(path)

        if QtCore.QFile.exists(path):
            result = QtWidgets.QMessageBox.question(
                self, "File Modified Externally",
                "{} has been modified on disk. Would you like to reload it?".format(path),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
            if result == QtWidgets.QMessageBox.Yes:
                return self.refreshTab()
            # TODO: If choosing not to reload, should we warn the user again if saving this file later?
            return False
        else:
            result = QtWidgets.QMessageBox.question(
                self, "File Not Found",
                "{} no longer exists. Another process may have moved or deleted it.".format(path),
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel, QtWidgets.QMessageBox.Save)
            if result == QtWidgets.QMessageBox.Save:
                return self.saveTab()
            # If not saving, switch to Edit mode so you can save.
            # Make sure the tab appears as dirty so the user is prompted on exit to do so if they still haven't up to
            # that point.
            if not self.currTab.inEditMode:
                self.toggleEdit(tab=self.currTab)
            self.currTab.setDirty()
            return False

    def setOverrideCursor(self, cursor=QtCore.Qt.WaitCursor):
        """ Set the override cursor if it is not already set.

        :Parameters:
            cursor
                Qt cursor
        """
        if not QtWidgets.QApplication.overrideCursor():
            QtWidgets.QApplication.setOverrideCursor(cursor)

    def restoreOverrideCursor(self):
        """ If an override cursor is currently set, restore the previous cursor.
        """
        if QtWidgets.QApplication.overrideCursor():
            QtWidgets.QApplication.restoreOverrideCursor()

    @contextmanager
    def overrideCursor(self, cursor=QtCore.Qt.WaitCursor):
        """ For use with the "with" keyword, so the override cursor is always
        restored via a try/finally block, even if the commands in-between fail.

        Example:
            with overrideCursor():
                # do something that may raise an error
        """
        self.setOverrideCursor(cursor)
        try:
            yield
        finally:
            self.restoreOverrideCursor()

    def getCachePath(self, fileStr, fileParser):
        """ Cache a converted binary file so we can use it again later without reconversion if it's still newer.

        :Parameters:
            fileStr : `str`
                Binary file path
            fileParser : `AbstractExtParser`
                File parser
        :Returns:
            Cache file path
        :Rtype:
            `str`
        """
        if (fileStr in self.app.fileCache and
                QtCore.QFileInfo(self.app.fileCache[fileStr]).lastModified() > QtCore.QFileInfo(fileStr).lastModified()):
            path = self.app.fileCache[fileStr]
            logger.debug("Reusing cached file %s for binary file %s", path, fileStr)
        else:
            logger.debug("Converting binary file to ASCII representation...")
            self.app.fileCache[fileStr] = path = fileParser.generateTempFile(fileStr, self.app.tmpDir)
        return path

    def readBinaryFile(self, fileStr, fileParser):
        """ Read in a binary file, converting to a temp ASCII file.

        Used by file parsers.

        :Parameters:
            fileStr : `str`
                Binary file path
            fileParser : `AbstractExtParser`
                File parser
        :Returns:
            ASCII file text
        :Rtype:
            `str`
        """
        with open(self.getCachePath(fileStr, fileParser)) as f:
            return f.readlines()

    @Slot(QtCore.QUrl)
    def setSource(self, link, isNewFile=True, newTab=False, hScrollPos=0, vScrollPos=0, tab=None, focus=True):
        """ Create a new tab or update the current one.
        Process a file to add links.
        Send the formatted text to the appropriate tab.

        :Parameters:
            link : `QtCore.QUrl`
                File to open.
                If link contains a fragment (e.g. #text), no new file will be loaded. The current file (if any) will
                remain and the portion after the # will be treated as a query string. Useful for jumping to line
                numbers without reloading the current file.
            isNewFile : `bool`
                Optional bool for if this is a new file or an item from history.
            newTab : `bool`
                Optional bool to open in a new tab no matter what.
            hScrollPos : `int`
                Horizontal scroll bar position.
            vScrollPos : `int`
                Vertical scroll bar position.
            tab : `BrowserTab` | None
                Existing tab to load in. Defaults to current tab. Ignored if newTab=True.
            focus : `bool`
                If True, change focus to this tab. Currently only applies when creating new tabs.
        :Returns:
            True if the file was loaded successfully (or was dirty but the user cancelled the save prompt).
        :Rtype:
            `bool`
        """
        # If we're staying in the current tab, check if the tab is dirty before doing anything.
        # Perform save operations if necessary.
        if not newTab and not self.dirtySave(tab=tab):
            return True

        # Handle self-referential links, where we just want to do something to the current file based on input query
        # parameters instead of reloading the file. QFileInfo gets confused by fragments, so process this first.
        if link.hasFragment():
            print("has fragment")
            queryLink = utils.urlFragmentToQuery(link)

            if newTab:
                return self.setSource(queryLink, isNewFile, newTab, hScrollPos, vScrollPos, tab, focus)

            if queryLink.hasQuery():
                # Scroll to line number.
                line = utils.queryItemValue(queryLink, "line")
                if line is not None:
                    tab = tab or self.currTab
                    tab.goToLineNumber(line)
                    # TODO: It would be nice to store the "clicked" position in history, so going back would take us to
                    # the object we just clicked (as opposed to where we first loaded the file from).
            return self.setSourceFinish(tab=tab)

        # HACK to interpret a fragment URL where the # was encoded (Qt5) or not recognized as a fragment (Qt4).
        # This happens when using Qt's "Copy Link Location" context menu action with a fragment-based URL and pasting
        # it in the address bar.
        fullUrlStr = link.toString()
        if "%23?" in fullUrlStr:  # Qt5
            logger.debug("Converting link with encoded '#' and query string: %s", fullUrlStr)
            link = utils.strToUrl(fullUrlStr.replace("%23?", "?", 1))
            return self.setSource(link, isNewFile, newTab, hScrollPos, vScrollPos, tab, focus)
        elif (Qt.IsPyQt4 or Qt.IsPySide) and "#?" in fullUrlStr:
            logger.debug("Converting link with '#?': %s", fullUrlStr)
            link = utils.strToUrl(fullUrlStr.replace("#?", "?", 1))
            return self.setSource(link, isNewFile, newTab, hScrollPos, vScrollPos, tab, focus)

        # TODO: When given a relative path here, this expands based on the directory the tool was launched from.
        # Should this instead be relative based on the currently active tab's directory?
        localFile = link.toLocalFile()
        fileInfo = QtCore.QFileInfo(localFile)
        absFilePath = fileInfo.absoluteFilePath()
        if not absFilePath:
            logger.warning("Unable to determine file path from %s", link)
            return self.setSourceFinish(tab=tab)

        nativeAbsPath = QtCore.QDir.toNativeSeparators(absFilePath)
        fileExists = True  # Assume the file exists for now.
        logger.debug("Setting source to %s (local file path: %s) %s %s", fullUrlStr, localFile, nativeAbsPath, link)

        self.setOverrideCursor()
        try:
            # If the filename contains an asterisk, make sure there is at least one valid file.
            multFiles = None
            if '*' in nativeAbsPath or "<UDIM>" in nativeAbsPath:
                multFiles = glob(nativeAbsPath.replace("<UDIM>", "[1-9][0-9][0-9][0-9]"))
                if not multFiles:
                    return self.setSourceFinish(False, "The file(s) could not be found:\n{}".format(nativeAbsPath),
                                                tab=tab)

                # If we're opening any files, avoid also opening directories that a glob might have picked up.
                isFile = {x: QtCore.QFileInfo(x).isFile() for x in multFiles}
                if any(isFile.values()):
                    multFiles = [x for x in multFiles if isFile[x]]
                else:
                    # We only found one or more directories via glob, no files. Set multFiles to a single directory,
                    # which will have the effect of opening the file browser dialog to that directory. We don't want
                    # this to open multiple times for each found directory.
                    multFiles = [multFiles[0]]
            # These next tests would normally fail out if the path had a wildcard.
            else:
                if fileInfo.isDir():
                    logger.debug("Set source to directory. Opening file dialog to %s", nativeAbsPath)
                    status = self.setSourceFinish(tab=tab)
                    # Instead of failing with a message that you can't open a directory, open the "Open File" dialog to
                    # this directory instead.
                    self.lastOpenFileDir = absFilePath
                    self.openFileDialog(tab=tab)
                    return status
                if not fileInfo.exists():
                    logger.debug("The file could not be found: %s", nativeAbsPath)
                    fileExists = False
                elif not fileInfo.isReadable():
                    return self.setSourceFinish(False, "The file could not be read:\n{}".format(nativeAbsPath), tab=tab)

            # Get extension (minus beginning .) to determine which program to
            # launch, or if the textBrowser should try to display the file.
            ext = fileInfo.suffix()
            if ext in self.programs and self.programs[ext]:
                if multFiles is not None:
                    # Assumes program takes a space-separated list of files.
                    self.launchPathCommand(self.programs[ext], multFiles)
                else:
                    self.launchPathCommand(self.programs[ext], nativeAbsPath)
                return self.setSourceFinish(tab=tab)

            if multFiles is not None:
                self.setSources(multFiles, tab=tab, focus=focus)
                return self.setSourceFinish(tab=tab)

            # Open this in a new tab or not?
            tab = tab or self.currTab
            if (newTab or (isNewFile and self.preferences['newTab'])) and not tab.isNewTab:
                tab = self.newTab(focus=focus)
            else:
                # Remove the tab's previous path from the file system watcher.
                # Be careful not to remove the path if any other tabs have the same file open.
                path = self.currTab.getCurrentPath()
                if path and self.currentlyOpenFiles().count(path) <= 1:
                    self.fileSystemWatcher.removePath(path)

                # Set to none until we know what we're reading in.
                tab.fileFormat = FILE_FORMAT_NONE

            # Set path in tab's title and address bar.
            fileName = fileInfo.fileName()
            idx = self.tabWidget.indexOf(tab)
            self.tabWidget.setTabText(idx, fileName)
            self.tabWidget.setTabIcon(idx, QtGui.QIcon())
            self.tabWidget.setTabToolTip(idx, "{} - {}".format(fileName, nativeAbsPath))

            # Take care of various history menus.
            self.updateRecentMenus(link, fullUrlStr)

            if fileExists:
                # TODO: If files can load in parallel, this single progress bar would need to change.
                self.loadingProgressBar.setValue(0)
                self.loadingProgressBar.setVisible(True)
                self.loadingProgressLabel.setVisible(True)

                try:
                    if self.validateFileSize(fileInfo):
                        self.updateTabParser(tab, fileInfo, link)
                        parser = tab.parser
                        if ext in USD_ZIP_EXTS:
                            layer = utils.queryItemValue(link, "layer")
                            dest = parser.read(absFilePath, layer, self.app.fileCache, self.app.tmpDir)
                            self.restoreOverrideCursor()
                            self.loadingProgressBar.setVisible(False)
                            self.loadingProgressLabel.setVisible(False)
                            return self.setSource(utils.strToUrl(dest), tab=tab, focus=focus)

                        # Stop Loading Tab stops the expensive parsing of the file
                        # for links, checking if the links actually exist, etc.
                        # Setting it to this bypasses link parsing if the tab is in edit mode.
                        parser.stop(tab.inEditMode or not self.preferences['parseLinks'])
                        self.actionStop.setEnabled(True)

                        parser.parse(nativeAbsPath, fileInfo, link)
                        tab.fileFormat = parser.fileFormat
                        self.tabWidget.setTabIcon(idx, parser.icon)
                        self.setHighlighter(ext, tab=tab)
                        logger.debug("Setting HTML")
                        tab.textBrowser.setHtml(parser.html)
                        logger.debug("Setting plain text")
                        tab.textEditor.setPlainText("".join(parser.text))
                        truncated = parser.truncated
                        warning = parser.warning
                        parser.cleanup()
                    else:
                        self.loadingProgressBar.setVisible(False)
                        self.loadingProgressLabel.setVisible(False)
                        return self.setSourceFinish(False, tab=tab)
                except Exception:
                    self.loadingProgressBar.setVisible(False)
                    self.loadingProgressLabel.setVisible(False)
                    return self.setSourceFinish(False, "The file could not be read: {}".format(nativeAbsPath),
                                                traceback.format_exc(), tab=tab)

                self.loadingProgressLabel.setText("Highlighting text")
                self.labelFindPixmap.setVisible(False)
                self.labelFindStatus.setVisible(False)
                self.findRehighlightAll()
            else:
                # Load an empty tab pointing to the nonexistent file.
                self.setHighlighter(ext, tab=tab)
                tab.textBrowser.setHtml("")
                tab.textEditor.setPlainText("")
                truncated = False
                warning = None

            logger.debug("Updating history")
            tab.isNewTab = False
            if isNewFile:
                tab.updateHistory(link, truncated=truncated)
            tab.updateFileStatus(truncated=truncated)
            if fileExists:
                logger.debug("Setting scroll position")
                # Set focus and scroll to given position.
                # For some reason this never seems to work the first time.
                tab.getCurrentTextWidget().setFocus()
                tab.getCurrentTextWidget().horizontalScrollBar().setValue(hScrollPos)
                tab.getCurrentTextWidget().verticalScrollBar().setValue(vScrollPos)

                # Scroll to line number.
                if link.hasQuery():
                    line = utils.queryItemValue(link, "line")
                    if line is not None:
                        tab.goToLineNumber(line)

                if absFilePath not in self.fileSystemWatcher.files():
                    self.fileSystemWatcher.addPath(absFilePath)

                # Since we dirty the tab anytime the text is changed, undirty it, as we just loaded this file.
                tab.setDirty(False)

                self.loadingProgressBar.setVisible(False)
                self.loadingProgressLabel.setVisible(False)
            else:
                if not tab.inEditMode:
                    self.toggleEdit(tab=tab)
                tab.setDirty(True)

            logger.debug("Cleanup")
            self.statusbar.showMessage("Done", 2000)
        except Exception:
            return self.setSourceFinish(False, "An error occurred while reading the file: {}".format(nativeAbsPath),
                                        traceback.format_exc(), tab=tab)
        else:
            return self.setSourceFinish(warning=warning, tab=tab)

    def setSourceFinish(self, success=True, warning=None, details=None, tab=None):
        """ Finish updating UI after loading a new source.

        :Parameters:
            success : `bool`
                If the file was loaded successfully or not
            warning : `str` | None
                Optional warning message
            details : `str` | None
                Optional details for the warning message
            tab : `BrowserTab | None
                Tab that finished. Defaults to current tab.
        :Returns:
            Success
        :Rtype:
            `bool`
        """
        # Clear link since we don't want any previous links to carry over.
        if tab is None or tab == self.currTab:
            self.linkHighlighted = QtCore.QUrl("")
            self.actionStop.setEnabled(False)
            self.updateButtons()
        self.restoreOverrideCursor()
        if warning:
            self.showWarningMessage(warning, details)
        return success

    def setSources(self, files, tab=None, focus=True):
        """ Open multiple files in new tabs.

        :Parameters:
            files : `list`
                List of string-based paths to open
            tab : `BrowserTab` | None
                Tab this may be opening from. Useful for path expansion.
            focus : `bool`
                Change focus to the new tabs as they are created.
        """
        tab = tab or self.currTab
        prevPath = tab.getCurrentPath()
        for path in files:
            self.setSource(utils.expandUrl(path, prevPath), newTab=True, tab=tab, focus=focus)

    @Slot(int)
    def setLoadingProgress(self, value):
        """ Called by parser to update loading progress bar's value.

        :Parameters:
            value : `int`
                Line number being parsed
        """
        self.loadingProgressBar.setValue(value)
        QtWidgets.QApplication.processEvents()

    def validateFileSize(self, info):
        """ If a file's size is above a certain threshold, confirm the user still wants to open the file.

        :Parameters:
            info : `QtCore.QFileInfo`
                File info object
        :Returns:
            If we should open the file or not
        :Rtype:
            `bool`
        """
        size = info.size()
        if size >= 104857600:  # 100 MB
            self.restoreOverrideCursor()
            try:
                dlg = QtWidgets.QMessageBox.question(
                    self, "Large File",
                    "This file is {} and may be slow to load. Are you sure you want to continue?\n\n{}".format(
                        utils.humanReadableSize(size), info.absoluteFilePath()),
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                return dlg == QtWidgets.QMessageBox.Yes
            finally:
                self.setOverrideCursor()
        return True

    def addItemToMenu(self, url, menu, slot, maxLen=None, start=0, end=None):
        """ Add a URL to a history menu.

        :Parameters:
            url : `QtCore.QUrl`
                The full URL to add to a history menu.
            menu : `QtWidgets.QMenu`
                Menu to add history item to.
            slot
                Method to connect action to
            maxLen : `int`
                Optional maximum number of history items in the menu.
            start : `int`
                Optional number of actions at the start of the menu to ignore.
            end : `int` | None
                Optional number of actions at the end of the menu to ignore.
        """
        # Get the current actions.
        actions = menu.actions()
        numAllActions = len(actions)

        if end is not None:
            end = -end
            numActions = numAllActions - start + end
        else:
            numActions = numAllActions - start

        # Validate the start, end, and maxLen numbers.
        if start < 0 or maxLen <= 0 or numActions < 0:
            logger.error("Invalid start/end values provided for inserting action in menu.\n"
                         "start: %d, end: %d, menu length: %d", start, end, numAllActions)
        elif numActions == 0:
            # There are not any actions yet, so just add or insert it.
            action = RecentFile(url, menu, slot)
            if start != 0 and numAllActions > start:
                menu.insertAction(actions[start], action)
            else:
                menu.addAction(action)
        else:
            alreadyInMenu = False
            for action in actions[start:end]:
                if url == action.url:
                    alreadyInMenu = True
                    # Move to the top if there is more than one action and it isn't already at the top.
                    if numActions > 1 and action != actions[start]:
                        menu.removeAction(action)
                        menu.insertAction(actions[start], action)
                    break
            if not alreadyInMenu:
                action = RecentFile(url, menu, slot)
                menu.insertAction(actions[start], action)
                if maxLen is not None and numActions == maxLen:
                    menu.removeAction(actions[start + maxLen - 1])

    @Slot()
    @Slot(bool)
    def goPressed(self, *args):
        """ Handle loading the current path in the address bar.
        """
        # Check if text has changed.
        url = utils.expandUrl(self.addressBar.text().strip())
        if url != self.currTab.getCurrentUrl():
            self.setSource(url)
        else:
            self.refreshTab()

    @Slot(QtWidgets.QWidget)
    def changeTab(self, tab):
        """ Set the current tab to the calling tab.

        :Parameters:
            tab : `QtWidgets.QWidget`
                Tab widget
        """
        self.tabWidget.setCurrentWidget(tab)

    @Slot(int)
    def currentTabChanged(self, idx):
        """ Slot called when the current tab has changed.

        :Parameters:
            idx : `int`
                Index of the newly selected tab
        """
        prevMode = self.currTab.inEditMode
        self._prevParser = self.currTab.parser
        self.currTab = self.tabWidget.widget(idx)
        if prevMode != self.currTab.inEditMode:
            self.editModeChanged.emit(self.currTab.inEditMode)

        self.setNavigationMenus()
        self.updateButtons()

        if not self.quitting:
            # Prompt if this file was modified on disk since the last time we viewed it.
            path = self.currTab.getCurrentPath()
            if path in self.fileSystemModified:
                if self.promptOnFileChange(path):
                    return

            # Highlighting can be very slow on bigger files. Don't worry about
            # updating it if we're closing tabs while quitting the app.
            self.findRehighlightAll()

    def setNavigationMenus(self):
        """ Set the navigation buttons to use the current tab's history menus.
        """
        self.navToolbar.widgetForAction(self.actionBack).setMenu(self.currTab.backMenu)
        self.navToolbar.widgetForAction(self.actionForward).setMenu(self.currTab.forwardMenu)

    def isDarkTheme(self):
        """ Check if any dark theme is active based on launch preference and the background lightness.

        :Returns:
            True if launched with the dark theme preference or the lightness factor of the window background is less
            than 0.5. The 0.5 threshold to determine if it's dark is completely arbitrary.
        :Rtype:
            `bool`
        """
        return self._darkTheme or self.palette().window().color().lightnessF() < 0.5

    def updateButtons(self):
        """ Update button states, text fields, and other GUI elements.
        """
        # Hide the file:// from the URL in the address bar.
        url = self.currTab.getCurrentUrl()
        path = url.toLocalFile()
        urlStr = url.toString()
        if url.hasQuery():
            urlStr, query = urlStr.split("?", 1)
        else:
            query = None
        path = QtCore.QDir.toNativeSeparators(path)
        if query:
            path += "?" + query
        self.addressBar.setText(path)

        self.breadcrumb.setText(self.currTab.breadcrumb)
        self.updateEditButtons()
        self.updateParserPlugins()

        title = self.app.appDisplayName
        if self.currTab.isNewTab:
            self.actionBack.setEnabled(False)
            self.actionForward.setEnabled(False)
            self.actionRefresh.setEnabled(False)
            self.actionFileInfo.setEnabled(False)
            self.actionTextEditor.setEnabled(False)
            self.actionOpenWith.setEnabled(False)
        else:
            title += " - " + self.tabWidget.tabText(self.tabWidget.currentIndex())
            self.actionBack.setEnabled(self.currTab.isBackwardAvailable())
            self.actionForward.setEnabled(self.currTab.isForwardAvailable())
            enable = bool(path)
            self.actionRefresh.setEnabled(enable)
            self.actionFileInfo.setEnabled(enable)
            self.actionTextEditor.setEnabled(enable)
            self.actionOpenWith.setEnabled(enable)
        self.setWindowTitle(title)

        status = self.currTab.getFileStatus()
        self.fileStatusButton.setText(status.text)
        self.fileStatusButton.setIcon(status.icon)
        self.actionEdit.setEnabled(status.writable)

        # Emit a signal that buttons are updating due to a file change.
        # Useful for plug-ins that may need to update their actions' enabled state.
        self.updatingButtons.emit()

    def updateParserPlugins(self):
        """ Update parser-specific UI actions when the file parser has changed
        due to the display of a different file type.
        """
        if self.currTab.parser != self._prevParser:
            # Clear old actions up to the last separator.
            for action in reversed(self.menuCommands.actions()):
                if action.isSeparator():
                    break
                self.menuCommands.removeAction(action)
            if self.currTab.parser is not None:
                for args in self.currTab.parser.plugins:
                    self.menuCommands.addAction(*args)

    def updateEditButtons(self):
        """ Toggle edit action and button text.
        """
        if self.currTab.inEditMode:
            self.actionEdit.setVisible(False)
            self.actionBrowse.setVisible(True)
            self.actionSave.setEnabled(True)
            self.actionPaste.setEnabled(self.currTab.textEditor.canPaste())
            self.actionUndo.setEnabled(self.currTab.textEditor.document().isUndoAvailable())
            self.actionRedo.setEnabled(self.currTab.textEditor.document().isRedoAvailable())
            self.actionFind.setText("&Find/Replace...")
            self.actionFind.setIcon(utils.icon("edit-find-replace"))
            self.actionCommentOut.setEnabled(True)
            self.actionUncomment.setEnabled(True)
            self.actionIndent.setEnabled(True)
            self.actionUnindent.setEnabled(True)
        else:
            self.actionEdit.setVisible(True)
            self.actionBrowse.setVisible(False)
            self.actionSave.setEnabled(False)
            self.actionUndo.setEnabled(False)
            self.actionRedo.setEnabled(False)
            self.actionCut.setEnabled(False)
            self.actionPaste.setEnabled(False)
            self.actionFind.setText("&Find...")
            self.actionFind.setIcon(utils.icon("edit-find"))
            self.actionCommentOut.setEnabled(False)
            self.actionUncomment.setEnabled(False)
            self.actionIndent.setEnabled(False)
            self.actionUnindent.setEnabled(False)

    @Slot(str)
    def validateAddressBar(self, address):
        """ Validate the text in the address bar.
        Currently, this just ensures the address is not an empty string.

        :Parameters:
            address : `str`
                Current text in the address bar.
        """
        self.buttonGo.setEnabled(bool(address.strip()))

    def launchPathCommand(self, command, path, **kwargs):
        """ Launch a command with a file path either being appended to the end
        or substituting curly brackets if present.

        Any additional keyword arguments are passed to the Popen object.

        Example:
            launchPathCommand("rez-env usd_view -c 'usdview {}'", "scene.usd")
            runs: rez-env usd_view -c 'usdview scene.usd'

            launchPathCommand("nedit", "scene.usd") runs: nedit scene.usd

            launchPathCommand("ls", ["foo", "bar"]) runs: ls foo bar

        :Parameters:
            command : `str` | [`str`]
                Command to run. If the path to open with the command cannot
                simply be appended with a space at the end of the command, use
                {} like standard python string formatting to denote where the
                path should go.
            path : `str` | [`str`]
                File path `str`, space-separated list of files paths as a
                single `str`, or `list` of `str` file paths
        :Returns:
            Returns process ID, or None if the subprocess fails
        :Rtype:
            `subprocess.Popen` | None
        """
        if not isinstance(command, list):
            if '{}' in command:
                try:
                    quote = shlex.quote  # Python 3.3+ (shlex is already imported)
                except AttributeError:
                    from pipes import quote  # Deprecated since python 2.7
                if isinstance(path, list):
                    path = subprocess.list2cmdline(quote(x) for x in path)
                try:
                    command = command.format(quote(path))
                except IndexError as e:
                    self.showCriticalMessage("Invalid command: {}. If using curly brackets, please ensure there is only "
                                            "one set.".format(e), details="Command: {}\nPath: {}".format(command, path))
                    return
                if not kwargs.get("shell"):
                    command = shlex.split(command)
            else:
                command = shlex.split(command)
                if isinstance(path, list):
                    command += path
                else:
                    command.append(path)
        else:
            if isinstance(path, list):
                command += path
            elif '{}' in command:
                while '{}' in command:
                    command[command.index('{}')] = path
            else:
                command.append(path)
        return self.launchProcess(command, **kwargs)

    def launchProcess(self, args, **kwargs):
        """ Launch a subprocess. Any additional keyword arguments are passed to the Popen object.

        :Parameters:
            args : `list` | `str`
                A sequence of program arguments with the program as the first arg.
        :Returns:
            Returns process ID, or None if the subprocess fails
        :Rtype:
            `subprocess.Popen` | None
        """
        with self.overrideCursor():
            try:
                if kwargs.get("shell"):
                    # With shell=True, convert args to a string to call Popen with.
                    # Properly quote any args as necessary before using this.
                    logger.debug("Running Popen with shell=True")
                    if isinstance(args, list):
                        args = subprocess.list2cmdline(args)
                    logger.info(args)
                else:
                    # Leave args as a list for Popen, but still log the string command.
                    logger.info(subprocess.list2cmdline(args))
                return subprocess.Popen(args, **kwargs)
            except Exception:
                self.restoreOverrideCursor()
                cmd = args[0] if isinstance(args, list) else args.split()[0]
                self.showCriticalMessage("Operation failed. {} may not be installed.".format(cmd),
                                         traceback.format_exc())

    @Slot(bool)
    def viewSource(self, checked=False):
        """ For debugging, view the source HTML of the text browser widget.

        :Parameters:
            checked : `bool`
                Just for signal
        """
        html = self.currTab.textBrowser.toHtml()
        tab = self.newTab()
        tab.textBrowser.setPlainText(html)

    def showCriticalMessage(self, message, details=None, title=None):
        """ Show an error message with optional details text (useful for tracebacks).

        :Parameters:
            message : `str`
                Main message
            details : `str` | None
                Optional details
            title : `str`
                Dialog title (defaults to app name)
        :Returns:
            Selected StandardButton value
        :Rtype:
            `int`
        """
        return self.showWarningMessage(message, details, title, QtWidgets.QMessageBox.Critical)

    def showSuccessMessage(self, msg, title=None):
        """ Display a generic message if the user's preferences are not set to only show warnings/errors.

        :Parameters:
            msg : `str`
                Message to display.
            title : `str` | None
                Optional title.
        """
        if self.preferences['showAllMessages']:
            QtWidgets.QMessageBox(QtWidgets.QMessageBox.NoIcon, title or self.windowTitle(), msg,
                                  QtWidgets.QMessageBox.Ok, self).exec_()

    def showWarningMessage(self, message, details=None, title=None, icon=QtWidgets.QMessageBox.Warning):
        """ Show a warning message with optional details text (useful for tracebacks).

        :Parameters:
            message : `str`
                Main message
            details : `str` | None
                Optional details
            title : `str`
                Dialog title (defaults to app name)
            icon : `int`
                QMessageBox.Icon
        :Returns:
            Selected StandardButton value
        :Rtype:
            `int`
        """
        title = title or self.app.appDisplayName
        if details:
            msgBox = QtWidgets.QMessageBox(icon, title, message, QtWidgets.QMessageBox.Ok, self)
            msgBox.setDefaultButton(QtWidgets.QMessageBox.Ok)
            msgBox.setEscapeButton(QtWidgets.QMessageBox.Ok)
            msgBox.setDetailedText(details)
            return msgBox.exec_()
        return QtWidgets.QMessageBox.warning(self, title, message)

    @Slot(QtWidgets.QWidget, str, str, bool)
    def _changeTabName(self, tab, text, toolTip, dirty):
        """ Change the displayed name of a tab.

        Called via signal from a tab when the tab's dirty state changes.

        :Parameters:
            text : `str`
                Name to display
            toolTip : `str`
                Tab tool tip
            dirty : `bool`
                Dirty state of tab
        """
        idx = self.tabWidget.indexOf(tab)
        if idx == -1:
            logger.debug("Tab not found for %s", text)
            return
        self.tabWidget.setTabText(idx, text)
        self.tabWidget.setTabToolTip(idx, toolTip)
        if tab == self.currTab:
            self.setWindowTitle("{} - {}".format(self.app.appDisplayName, text))
            self.actionDiffFile.setEnabled(dirty)

    def dirtySave(self, tab=None):
        """ Present a save dialog for dirty tabs to know if they're safe to close/reload or not.

        :Parameters:
            tab : `BrowserTab` | None
                Tab to save. Defaults to current tab.
        :Returns:
            False if Cancel selected.
            True if Discard selected.
            True if Save selected (and actually saving).
        :Rtype:
            `bool`
        """
        tab = tab or self.currTab
        if tab.isDirty():
            doc = tab.textEditor.document()
            if (not doc.isUndoAvailable() and not doc.isRedoAvailable()
                    and not QtCore.QFile.exists(tab.getCurrentPath())):
                # We navigated to a non-existent file and haven't actually edited it yet, but other code set it to
                # dirty so it's easier to save as the new file. Don't prompt to close in this case.
                # TODO: Is there a better way to track this?
                return True
            dlg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "Save File", "The document has been modified.",
                                        QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard |
                                        QtWidgets.QMessageBox.Cancel, self)
            dlg.setDefaultButton(QtWidgets.QMessageBox.Save)
            dlg.setInformativeText("Do you want to save your changes?")
            btn = dlg.exec_()
            if btn == QtWidgets.QMessageBox.Cancel:
                return False
            elif btn == QtWidgets.QMessageBox.Save:
                return self.saveTab(tab=tab)
            else:  # Discard
                tab.setDirty(False)
        return True

    @Slot(QtCore.QUrl)
    def onOpenOldUrl(self, url):
        """ Open a path from history in the current tab.

        :Parameters:
            url : `QtCore.QUrl`
                URL to open
        """
        self.setSource(url, isNewFile=False)

    @Slot(str)
    def onOpen(self, path):
        """ Open the path in a new tab.

        :Parameters:
            path : `str`
                File to open
        """
        self.setSource(utils.strToUrl(path), newTab=True)

    @Slot()
    def onOpenLinkNewWindow(self):
        """ Open the currently highlighted link in a new window.
        """
        url = utils.urlFragmentToQuery(self.linkHighlighted)
        window = self.newWindow()
        window.setSource(url)

    @Slot()
    def onOpenLinkNewTab(self):
        """ Open the currently highlighted link in a new tab.
        """
        self.setSource(self.linkHighlighted, newTab=True)

    @Slot()
    def onOpenLinkWith(self):
        """ Show the "Open With..." dialog for the currently highlighted link.
        """
        self.launchProgramOfChoice(path=QtCore.QDir.toNativeSeparators(self.linkHighlighted.toLocalFile()))

    @Slot(str)
    def onBreadcrumbActivated(self, path):
        """ Slot called when a breadcrumb link (history for the current tab) is selected.

        :Parameters:
            path : `str`
                Breadcrumb path
        """
        # Check if there are any changes to be saved before we modify the history.
        if not self.dirtySave():
            return
        self.currTab.gotoBreadcrumb(utils.strToUrl(path))

    @Slot(str)
    def onBreadcrumbHovered(self, path):
        """ Slot called when the mouse is hovering over a breadcrumb link.
        """
        self.statusbar.showMessage(path, 2000)

    def updateRecentMenus(self, link, fullUrlStr):
        """ Update the history and recently open files menus.

        :Parameters:
            link : `QtCore.QUrl`
                URL to file
            fullUrlStr : `str`
                URL string representation
        """
        self.addItemToMenu(link, self.menuHistory, slot=self.setSource, maxLen=25, start=3, end=2)
        self.addItemToMenu(link, self.menuOpenRecent, slot=self.openRecent, maxLen=RECENT_FILES)
        self.menuOpenRecent.setEnabled(True)
        self.addRecentFileToSettings(fullUrlStr)


class AddressBar(QtWidgets.QLineEdit):
    """
    Custom QLineEdit class to enable drag/drop.
    """
    goPressed = Signal()
    openFile = Signal(str)

    def __init__(self, parent):
        """ Create the address bar.
        :Parameters:
            parent : `UsdMngrWindow`
                Main window
        """
        super(AddressBar, self).__init__(parent)
        self.setAcceptDrops(True)

        # Auto-completion for address bar.
        # Relative paths based on current directory in Include Panel.
        self.customCompleter = AddressBarCompleter(parent.includeWidget.fileModel, self)
        if parent.preferences['autoCompleteAddressBar']:
            self.setCompleter(self.customCompleter)
        self.returnPressed.connect(self.addressBarActivated)

    @Slot()
    def addressBarActivated(self):
        """ Trigger loading of the current path in the address bar.
        """
        t = self.text()
        if t:
            # Emit the signal to try opening the entered file path.
            self.goPressed.emit()

    def dragEnterEvent(self, event):
        """ Allow drag events of a file path to the address bar.
        """
        if event.mimeData().hasUrls() or event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """ Allow drop events of a file path to the address bar.
        """
        if event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toString()
        else:
            # Create a model to decode the data and get an item back out.
            model = QtGui.QStandardItemModel()
            model.dropMimeData(event.mimeData(), QtCore.Qt.CopyAction, 0, 0, QtCore.QModelIndex())
            path = model.item(0, 2).text()
        self.setText(path)
        self.openFile.emit(path)


class AddressBarCompleter(QtWidgets.QCompleter):
    """Custom completer for AddressBar.
    """


class RecentFile(QtWidgets.QAction):
    """ Action representing an individual file in the Recent Files or history menus.
    """
    openUrl = Signal(QtCore.QUrl)

    def __init__(self, url, parent=None, slot=None):
        """ Create the action.

        :Parameters:
            url : `QtCore.QUrl`
                URL to open.
            parent : `QtWidgets.QMenu`
                Menu to add action to.
            slot
                Method to connect openFile signal to
        """
        super(RecentFile, self).__init__(parent)
        self.url = url
        localFile = url.toLocalFile()
        # Don't show any query strings or SDF_FORMAT_ARGS in the menu.
        displayName = localFile.split(":SDF_FORMAT_ARGS:", 1)[0]
        # Escape any ampersands so that we don't get underlines for Alt+<key> shortcuts.
        displayName = QtCore.QFileInfo(displayName).fileName().replace("&", "&&")
        self.setText(displayName)
        self.setStatusTip(localFile)
        self.triggered.connect(self.onClick)
        if slot is not None:
            self.openUrl.connect(slot)

    @Slot(bool)
    def onClick(self, *args):
        """ Signal to open the selected file in the current tab.
        """
        self.openUrl.emit(self.url)


class TabBar(QtWidgets.QTabBar):
    """
    Customized QTabBar to enable re-ordering of tabs.
    """
    tabMoveRequested = Signal(int, int)
    crossWindowTabMoveRequested = Signal(int, int, int, int)

    def __init__(self, parent=None):
        """ Create and initialize the tab bar.

        :Parameters:
            parent : `TabWidget`
                Main container of the tab bar and individual tabs
        """
        super(TabBar, self).__init__(parent)
        self.setAcceptDrops(True)
        self.dragStartPos = QtCore.QPoint()

    def mousePressEvent(self, e):
        """ Mouse press event

        :Parameters:
            e : `QtGui.QMouseEvent`
                Mouse press event
        """
        if e.button() & QtCore.Qt.LeftButton:
            self.dragStartPos = e.pos()
        QtWidgets.QTabBar.mousePressEvent(self, e)

    def mouseMoveEvent(self, e):
        """ Mouse move event

        :Parameters:
            e : `QtGui.QMouseEvent`
                Mouse move event
        """
        if not e.buttons() & QtCore.Qt.LeftButton:
            return
        drag = QtGui.QDrag(self)
        drag.setPixmap(self.style().standardIcon(QtWidgets.QStyle.SP_ArrowUp).pixmap(12, 12))
        mimeData = QtCore.QMimeData()
        mimeData.setData("action", "moveTab")
        # Set the source window index so we know which window the drag/drop came from.
        mimeData.setData("window", str(self.currentWindowIndex()))
        drag.setMimeData(mimeData)
        drag.exec_()

    def dragEnterEvent(self, e):
        """ Drag enter event

        :Parameters:
            e : `QtGui.QDragEnterEvent`
                Drag event
        """
        mime = e.mimeData()
        formats = mime.formats()
        if "action" in formats and "window" in formats and mime.data("action") == "moveTab":
            e.acceptProposedAction()

    def currentWindowIndex(self):
        """ Get the index of the current active window.

        :Returns:
            Index of the current active window
        :Rtype:
            `int`
        """
        window = self.window()
        return window.app._windows.index(window)

    def dropEvent(self, e):
        """ Drop event, used to move tabs.

        :Parameters:
            e : `QtGui.QDropEvent`
                Drop event
        """
        mime = e.mimeData()
        fromWindowIndex, ok = mime.data("window").toInt()
        if not ok:
            logger.error("Failed to get int window index from TabBar drop event")
            e.ignore()
            return
        fromWindow = self.window().app._windows[fromWindowIndex]
        fromTabBar = fromWindow.tabWidget.tabBar
        fromTabIndex = fromTabBar.tabAt(fromTabBar.dragStartPos)
        toTabIndex = self.tabAt(e.pos())
        toWindowIndex = self.currentWindowIndex()

        # Sanity check.
        assert fromTabIndex >= 0 and toTabIndex >= 0 and fromWindowIndex >= 0 and toWindowIndex >= 0

        if fromWindowIndex == toWindowIndex:
            if fromTabIndex != toTabIndex:
                # Moving a tab within the same window.
                self.tabMoveRequested.emit(fromTabIndex, toTabIndex)
        else:
            # Moving a tab across windows.
            self.crossWindowTabMoveRequested.emit(fromTabIndex, toTabIndex, fromWindowIndex, toWindowIndex)
        e.acceptProposedAction()


class TabWidget(QtWidgets.QTabWidget):
    """
    Customized QTabWidget to enable re-ordering of tabs with a custom QTabBar.
    """
    def __init__(self, parent=None):
        """ Create and initialize the tab widget.

        :Parameters:
            parent : `UsdMngrWindow`
                Main window
        """
        super(TabWidget, self).__init__(parent)
        self.tabBar = TabBar(self)
        self.tabBar.tabMoveRequested.connect(self.moveTab)
        self.setTabBar(self.tabBar)

    @Slot(int, int)
    def moveTab(self, fromIndex, toIndex):
        """ Drag and drop tabs within the same window.

        :Parameters:
            fromIndex : `int`
                Original tab position
            toIndex : `int`
                New tab position
        """
        widget = self.widget(fromIndex)
        text = self.tabText(fromIndex)
        icon = self.tabIcon(fromIndex)
        self.removeTab(fromIndex)
        self.insertTab(toIndex, widget, icon, text)
        self.setCurrentIndex(toIndex)

    def setTabIcon(self, index, icon):
        """ Override the default method to set the same icon on our custom action that focuses on or re-opens the
        widget at the given index.

        :Parameters:
            index : `int`
                Index of widget
            icon : `QtGui.QIcon`
                Icon
        """
        super(TabWidget, self).setTabIcon(index, icon)
        self.widget(index).action.setIcon(icon)


class TextBrowser(QtWidgets.QTextBrowser):
    """
    Customized QTextBrowser to override mouse events and add line numbers.
    """
    def __init__(self, parent=None):
        """ Create and initialize the text browser.

        :Parameters:
            parent : `BrowserTab`
                Browser tab containing this text browser widget
        """
        super(TextBrowser, self).__init__(parent)
        self.lineNumbers = LineNumbers(self)
        self._mouseStartPos = QtCore.QPoint(0, 0)

    def resizeEvent(self, event):
        """ Ensure line numbers resize properly when this resizes.

        :Parameters:
            event : `QtGui.QResizeEvent`
                Resize event
        """
        super(TextBrowser, self).resizeEvent(event)
        self.lineNumbers.onEditorResize()

    def copySelectionToClipboard(self):
        """ Store current selection to the middle mouse selection.

        Doing this on selectionChanged signal instead of mouseReleaseEvent causes the following to be output in Qt5:
        "QXcbClipboard: SelectionRequest too old"

        For some reason, this isn't needed for QTextEdit but is for QTextBrowser?
        """
        cursor = self.textCursor()
        if cursor.hasSelection():
            clipboard = QtWidgets.QApplication.clipboard()
            if clipboard.supportsSelection():
                selection = cursor.selectedText().replace(u'\u2029', '\n')
                clipboard.setText(selection, clipboard.Selection)

    def mousePressEvent(self, event):
        """ Store the starting mouse position so that on mouse release we can determine if it was an intentional mouse
        move to highlight text or a click that may have drifted a pixel or two.

        :Parameters:
            event : `QtGui.QMouseEvent`
                Mouse press event
        """
        super(TextBrowser, self).mousePressEvent(event)
        if event.button() == QtCore.Qt.LeftButton:
            self._mouseStartPos = event.pos()

    def mouseReleaseEvent(self, event):
        """ Add support for middle mouse button clicking of links.

        :Parameters:
            event : `QtGui.QMouseEvent`
                Mouse release event
        """
        link = self.anchorAt(event.pos())
        if link:
            url = QtCore.QUrl(link)
            modifiers = event.modifiers()
            if event.button() == QtCore.Qt.LeftButton:
                # Only open the link if the user hasn't changed the selection of text while clicking.
                # Allow moving an arbitrary leeway of 3 pixels during the click.
                if (event.pos() - self._mouseStartPos).manhattanLength() <= 3:
                    if modifiers == QtCore.Qt.NoModifier:
                        self.window().setSource(url)
                    elif modifiers == QtCore.Qt.ControlModifier:
                        self.window().setSource(url, newTab=True, focus=False)
                    elif modifiers == QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier:
                        self.window().setSource(url, newTab=True, focus=True)
                    elif modifiers == QtCore.Qt.ShiftModifier:
                        window = self.window().newWindow()
                        window.setSource(url)
                    return
            elif event.button() & QtCore.Qt.MidButton:
                # Don't focus on new tab unless Shift is used.
                self.window().setSource(url, newTab=True, focus=modifiers & QtCore.Qt.ShiftModifier)
                return
        self.copySelectionToClipboard()


class TextEdit(QtWidgets.QPlainTextEdit):
    """
    Customized text edit widget to allow entering spaces with the Tab key.
    """
    def __init__(self, parent=None, tabSpaces=4, useSpaces=True, autoIndent=True):
        """ Create and initialize the tab.

        :Parameters:
            parent : `BrowserTab`
                Browser tab containing this text edit widget
            tabSpaces : `int`
                Number of spaces to use instead of a tab character, if useSpaces is True.
            useSpaces : `bool`
                If True, use the number of tab spaces instead of a tab character;
                otherwise, just use a tab character
        """
        super(TextEdit, self).__init__(parent)
        self.tabSpaces = tabSpaces
        self.useSpaces = useSpaces
        self.autoIndent = autoIndent

        self.lineNumbers = PlainTextLineNumbers(self)

    def resizeEvent(self, event):
        """ Ensure line numbers resize properly when this resizes.

        :Parameters:
            event : `QtGui.QResizeEvent`
                Resize event
        """
        super(TextEdit, self).resizeEvent(event)
        self.lineNumbers.onEditorResize()

    def keyPressEvent(self, e):
        """ Override the Tab key to insert spaces instead and the Return key to match indentation

        :Parameters:
            e : `QtGui.QKeyEvent`
                Key press event
        """
        if e.key() == QtCore.Qt.Key_Tab:
            if e.modifiers() == QtCore.Qt.NoModifier:
                if self.textCursor().hasSelection():
                    self.indentText()
                    return
                elif self.useSpaces:
                    # Insert the spaces equivalent of a tab character.
                    # Otherwise, QTextEdit/QPlainTextEdit already handle inserting the tab character.
                    self.insertPlainText(" " * self.tabSpaces)
                    return
        elif e.key() == QtCore.Qt.Key_Backtab and e.modifiers() == QtCore.Qt.ShiftModifier:
            self.unindentText()
            return
        elif e.key() == QtCore.Qt.Key_Return and self.autoIndent:
            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.insertText("\n")
            # Copy indent by moving up a line and to the next word
            cursor.movePosition(cursor.Up)
            cursor.movePosition(cursor.NextWord, cursor.KeepAnchor)
            indent = cursor.selectedText()
            # Don't insert indents that aren't only tabs and/or spaces
            if QtCore.QRegExp("[\t ]*").exactMatch(indent):
                cursor.movePosition(cursor.Down)
                cursor.insertText(indent)
            cursor.endEditBlock()
            return

        super(TextEdit, self).keyPressEvent(e)

    def commentOutText(self, commentStart="#", commentEnd=""):
        """ Comment out selected lines.

        TODO: For languages that use a different syntax for multi-line comments,
        use that when multiple lines are selected?

        :Parameters:
            commentStart : `str`
                String used for commenting out lines.
            commentEnd : `str`
                If the comment can be applied to multiple lines,
                this is the string marking the end of the comment.
        """
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        commentLen = len(commentStart)
        cursor.setPosition(start)
        cursor.movePosition(cursor.StartOfBlock)
        cursor.beginEditBlock()

        if not commentEnd:
            # Modify all blocks between selectionStart and selectionEnd
            while cursor.position() <= end and not cursor.atEnd():
                cursor.insertText(commentStart)
                # For every character we insert, increment the end position.
                end += commentLen
                prevBlock = cursor.blockNumber()
                cursor.movePosition(cursor.NextBlock)

                # I think I have a bug in my code if I have to do this.
                if prevBlock == cursor.blockNumber():
                    break
        else:
            # Only modify the beginning and end lines since this can
            # be a multiple-line comment.
            cursor.insertText(commentStart)
            cursor.setPosition(end)
            cursor.movePosition(cursor.EndOfBlock)
            cursor.insertText(commentEnd)
        cursor.endEditBlock()

    def uncommentText(self, commentStart="#", commentEnd=""):
        """ Uncomment selected lines.

        :Parameters:
            commentStart : `str`
                String used for commenting out lines.
            commentEnd : `str`
                If the comment can be applied to multiple lines,
                this is the string marking the end of the comment.
        """
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        commentLen = len(commentStart)
        cursor.setPosition(start)
        cursor.movePosition(cursor.StartOfBlock)
        cursor.beginEditBlock()
        if not commentEnd:
            # Modify all blocks between selectionStart and selectionEnd
            while cursor.position() <= end and not cursor.atEnd():
                block = cursor.block()
                # Select the number of characters used in the comment string.
                for _ in range(len(commentStart)):
                    cursor.movePosition(cursor.NextCharacter, cursor.KeepAnchor)
                # If the selection is all on the same line and matches the comment string, remove it.
                if block.contains(cursor.selectionEnd()) and cursor.selectedText() == commentStart:
                    cursor.deleteChar()
                    end -= commentLen
                prevBlock = cursor.blockNumber()
                cursor.movePosition(cursor.NextBlock)
                if prevBlock == cursor.blockNumber():
                    break
        else:
            # Remove the beginning comment string.
            # Do we only want to do this if there's also an end comment string in the selection?
            # We probably also want to remove the comments if there is any whitespace before or after it.
            # This logic may not be completely right when some comment symbols are already in the selection.
            block = cursor.block()
            # Select the number of characters used in the comment string.
            for _ in range(len(commentStart)):
                cursor.movePosition(cursor.NextCharacter, cursor.KeepAnchor)
            # If the selection is all on the same line and matches the comment string, remove it.
            if block.contains(cursor.selectionEnd()) and cursor.selectedText() == commentStart:
                cursor.deleteChar()
            # Remove the end comment string.
            cursor.setPosition(end - len(commentStart))
            block = cursor.block()
            cursor.movePosition(cursor.EndOfBlock)
            for _ in range(len(commentEnd)):
                cursor.movePosition(cursor.PreviousCharacter, cursor.KeepAnchor)
            if block.contains(cursor.selectionStart()) and cursor.selectedText() == commentEnd:
                cursor.deleteChar()
        cursor.endEditBlock()

    def indentText(self):
        """ Indent selected lines by one tab stop.
        """
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(cursor.StartOfBlock)
        cursor.beginEditBlock()
        # Modify all blocks between selectionStart and selectionEnd
        while cursor.position() < end and not cursor.atEnd():
            if self.useSpaces:
                if self.tabSpaces:
                    cursor.insertText(" " * self.tabSpaces)
                    # Increment end by the number of characters we inserted.
                    end += self.tabSpaces
            else:
                cursor.insertText("\t")
                end += 1
            prevBlock = cursor.blockNumber()
            cursor.movePosition(cursor.NextBlock)
            if prevBlock == cursor.blockNumber():
                break
        cursor.endEditBlock()

    def unindentText(self):
        """ Un-indent selected lines by one tab stop.
        """
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(cursor.StartOfBlock)
        cursor.beginEditBlock()
        # Modify all blocks between selectionStart and selectionEnd
        while cursor.position() < end and not cursor.atEnd():
            currBlock = cursor.blockNumber()

            for _ in range(self.tabSpaces):
                cursor.movePosition(cursor.NextCharacter, cursor.KeepAnchor)
                if cursor.selectedText() == " ":
                    cursor.deleteChar()
                    end -= 1
                elif cursor.selectedText() == "\t":
                    cursor.deleteChar()
                    end -= 1
                    # If we hit a tab character, that's the end of this tab stop.
                    break
                else:
                    break

            # If we're still in the same block, go to the next block.
            if currBlock == cursor.blockNumber():
                cursor.movePosition(cursor.NextBlock)
                if currBlock == cursor.blockNumber():
                    # We didn't get a new block, so we're at the end.
                    break
            else:
                # We already moved to the next block.
                cursor.movePosition(cursor.StartOfLine, cursor.MoveAnchor)
        cursor.endEditBlock()

    def zoomIn(self, adjust=1):
        """ Legacy Qt 4 support.

        :Parameters:
            adjust : `int`
                Font point size adjustment
        """
        try:
            super(TextEdit, self).zoomIn(adjust)
        except AttributeError:
            # Qt4 support.
            font = self.document().defaultFont()
            size = font.pointSize() + adjust
            if size > 0:
                font.setPointSize(size)
            self.document().setDefaultFont(font)

    def zoomOut(self, adjust=1):
        """ Legacy Qt 4 support.

        :Parameters:
            adjust : `int`
                Font point size adjustment
        """
        try:
            super(TextEdit, self).zoomOut(adjust)
        except AttributeError:
            # Qt4 support.
            font = self.document().defaultFont()
            size = font.pointSize() - adjust
            if size > 0:
                font.setPointSize(size)
            self.document().setDefaultFont(font)


class BrowserTab(QtWidgets.QWidget):
    """
    A QWidget that contains custom objects for each tab in the browser.
    This primarily consists of a text browser and text editor.
    """
    changeTab = Signal(QtWidgets.QWidget)
    restoreTab = Signal(QtWidgets.QWidget)
    openFile = Signal(str)
    openOldUrl = Signal(QtCore.QUrl)
    tabNameChanged = Signal(QtWidgets.QWidget, str, str, bool)

    def __init__(self, parent=None):
        """ Create and initialize the tab.

        :Parameters:
            parent : `TabWidget`
                Tab widget containing this widget
        """
        super(BrowserTab, self).__init__(parent)

        if self.window().isDarkTheme():
            color = QtGui.QColor(35, 35, 35).name()
        else:
            color = self.style().standardPalette().base().color().darker(105).name()
        self.setStyleSheet("QTextBrowser{{background-color:{}}}".format(color))
        self.inEditMode = False
        self.isActive = True  # Track if this tab is open or has been closed.
        self.isNewTab = True  # Track if this tab has been used for any files yet.
        self.setAcceptDrops(True)
        self.breadcrumb = ""
        self.history = []  # List of FileStatus objects
        self.historyIndex = -1  # First file opened will be 0.
        self.fileFormat = FILE_FORMAT_NONE  # Used to differentiate between things like usda and usdc.
        self.highlighter = None  # Syntax highlighter
        self.parser = None  # File parser for the currently active file type, used to add extra Commands menu actions.
        font = parent.font()
        prefs = parent.window().preferences

        # Text browser.
        self.textBrowser = TextBrowser(self)
        self.textBrowser.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.textBrowser.setFont(font)
        # Don't let the browser handle links, since we have our own, special handling.
        # TODO: Should we do a file:// URL handler instead?
        self.textBrowser.setOpenLinks(False)
        self.textBrowser.setVisible(not self.inEditMode)

        # Text editor.
        self.textEditor = TextEdit(self)
        self.textEditor.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.textEditor.setFont(font)
        self.textEditor.setLineWrapMode(self.textEditor.NoWrap)
        self.textEditor.setVisible(self.inEditMode)
        self.setIndentSettings(prefs['useSpaces'], prefs['tabSpaces'], prefs['autoIndent'])
        self.textEditor.document().modificationChanged.connect(self.setDirty)

        self.textBrowser.lineNumbers.setVisible(prefs['lineNumbers'])
        self.textEditor.lineNumbers.setVisible(prefs['lineNumbers'])

        # Menu item to be used in dropdown list of currently open tabs.
        self.action = QtWidgets.QAction("(Untitled)", None)
        self.action.triggered.connect(self.onActionTriggered)

        # Add widget to layout and layout to tab
        self.browserLayout = QtWidgets.QHBoxLayout()
        self.browserLayout.setContentsMargins(0, 2, 0, 0)
        self.browserLayout.addWidget(self.textBrowser)
        self.browserLayout.addWidget(self.textEditor)
        self.setLayout(self.browserLayout)

        # Menus for history navigation.
        self.backMenu = QtWidgets.QMenu(self)
        self.forwardMenu = QtWidgets.QMenu(self)

    def addHistoryAction(self, menu, index=0):
        """ Create a menu action for the current path.

        :Parameters:
            menu : `QtWidgets.QMenu`
                Menu to add action to
            index : `int`
                Index to insert action at.
                Defaults to the start of the menu if the index isn't given or is invalid.
        """
        item = self.history[self.historyIndex]
        action = RecentFile(item.url, menu, self.onHistoryActionTriggered)
        action.historyIndex = self.historyIndex

        try:
            before = menu.actions()[index]
        except IndexError:
            before = None
        menu.insertAction(before, action)

    def dragEnterEvent(self, event):
        """ Accept drag enter events from the custom file browser.
        """
        if event.mimeData().hasUrls() or event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """ If we receive a drop event with a file path, open the file in a new tab.
        """
        if event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toString()
        else:
            # Create a model to decode the data and get an item back out.
            model = QtGui.QStandardItemModel()
            model.dropMimeData(event.mimeData(), QtCore.Qt.CopyAction, 0, 0, QtCore.QModelIndex())
            path = model.item(0, 2).text()
        self.openFile.emit(path)

    def findUrl(self, url):
        """ Find the index of the given path in the tab's history.

        This returns the first occurrence if it is in the history more than once.

        :Parameters:
            url : `QtCore.QUrl`
                URL to search for in history.
        :Returns:
            Index of the given path in the history, or 0 if not found.
        :Rtype:
            `int`
        """
        for i in range(self.historyIndex + 1):
            if self.history[i].url == url:
                return i
        return 0

    def getCurrentPath(self):
        """ Get the absolute path of the current file.

        :Returns:
            Absolute path to current file
            Ex: /studio/filename.usd
        :Rtype:
            `str`
        """
        return self.getFileStatus().path

    def getCurrentUrl(self):
        """ Get the absolute path to the current file with any query strings appended.

        :Returns:
            Absolute path to current file plus any query strings.
            Ex: file:///studio/filename.usd?line=14
        :Rtype:
            `QtCore.QUrl`
        """
        return self.getFileStatus().url

    def getCurrentTextWidget(self):
        """ Get the current text widget (browser or editor).

        :Returns:
            The current text widget, based on edit mode
        :Rtype:
            `TextBrowser` | `TextEdit`
        """
        return self.textEditor if self.inEditMode else self.textBrowser

    def getFileStatus(self):
        """ Get the current file's status.

        :Returns:
            The current file's cached status
        :Rtype:
            `FileStatus`
        """
        if self.historyIndex >= 0:
            # I haven't been able to reproduce this, but it failed once before.
            # Try to get some more logging to debug the problem.
            assert self.historyIndex < len(self.history), (
                "Error: history index = {} but history length is {}. History: {}".format(self.historyIndex,
                                                                                         len(self.history),
                                                                                         self.history))
            return self.history[self.historyIndex]
        return FileStatus()

    def goBack(self):
        """ Go back in history one item.
        """
        # Insert the current path as the first item on the Forward menu.
        self.addHistoryAction(self.forwardMenu)

        # Remove the first item from the Back menu.
        if not self.backMenu.isEmpty():
            action = self.backMenu.actions()[0]
            self.backMenu.removeAction(action)

        self.historyIndex -= 1
        self.updateBreadcrumb()
        self.openOldUrl.emit(self.getCurrentUrl())

    def goForward(self):
        """ Go forward in history one item.
        """
        # Insert the current path as the first item on the Back menu.
        self.addHistoryAction(self.backMenu)

        # Remove the first item from the Forward menu.
        if not self.forwardMenu.isEmpty():
            action = self.forwardMenu.actions()[0]
            self.forwardMenu.removeAction(action)

        self.historyIndex += 1
        self.updateBreadcrumb()
        self.openOldUrl.emit(self.getCurrentUrl())

    def gotoBreadcrumb(self, url, index=None):
        """ Go to the historical index of the given URL.

        This does not handle updating the displayed document.

        :Parameters:
            url : `QtCore.QUrl`
                Breadcrumb URL
            index : `int` | None
                History index of the item to go to
        """
        # Insert the current URL as the first item on the Forward menu.
        self.addHistoryAction(self.forwardMenu)

        # Rebuild the history navigation menus.
        newIndex = index if index is not None else self.findUrl(url)
        self.backMenu.clear()
        self.forwardMenu.clear()
        for i in range(len(self.history[:newIndex])):
            self.historyIndex = i
            self.addHistoryAction(self.backMenu)
        for i in range(len(self.history[newIndex+1:])):
            self.historyIndex = i + newIndex + 1
            self.addHistoryAction(self.forwardMenu, i)

        self.historyIndex = newIndex
        self.updateBreadcrumb()
        self.openOldUrl.emit(self.getCurrentUrl())

    def goToLineNumber(self, line=1):
        """ Go to the given line number

        :Parameters:
            line : `int`
                Line number to scroll to. Defaults to 1 (top of document).
        """
        try:
            line = int(line)
        except ValueError:
            logger.warning("Invalid line number: %s", line)
            return

        textWidget = self.getCurrentTextWidget()
        block = textWidget.document().findBlockByNumber(line - 1)
        cursor = textWidget.textCursor()
        cursor.setPosition(block.position())
        # Highlight entire line.
        pos = block.position() + block.length() - 1
        if pos != -1:
            cursor.setPosition(pos, QtGui.QTextCursor.KeepAnchor)
            textWidget.setTextCursor(cursor)
            textWidget.ensureCursorVisible()

    def isBackwardAvailable(self):
        """ Check if you can go back in history.

        :Returns:
            If the backward action for history is available.
        :Rtype:
            `bool`
        """
        return self.historyIndex > 0

    def isDirty(self):
        """ Check if the current file has been modified in app.

        :Returns:
            If the current text editor document has been modified
        :Rtype:
            `bool`
        """
        if self.inEditMode:
            return self.textEditor.document().isModified()
        return False

    def isForwardAvailable(self):
        """ Check if you can go forward in history.

        :Returns:
            If the forward action for history is available.
        :Rtype:
            `bool`
        """
        return self.historyIndex < (len(self.history) - 1)

    @Slot(bool)
    def onActionTriggered(self, *args):
        """ Slot called when an action for the tab is activated
        (i.e. a tab from the Recently Closed Tabs menu).
        """
        if self.isActive:
            self.changeTab.emit(self)
        else:
            self.restoreTab.emit(self)

    @Slot(QtCore.QUrl)
    def onHistoryActionTriggered(self, url):
        """ Go to the URL when a `RecentItem` action is clicked.

        :Parameters:
            url : `QtCore.QUrl`
                URL
        """
        self.gotoBreadcrumb(url, self.sender().historyIndex)
        self.openOldUrl.emit(url)

    @Slot(bool)
    def setDirty(self, dirty=True):
        """ Set the dirty state.

        :Parameters:
            dirty : `bool`
                If this tab is dirty.
        """
        self.isNewTab = False
        self.textEditor.document().setModified(dirty)
        path = self.getCurrentPath()
        if not path:
            fileName = "(Untitled)"
            tipSuffix = ""
        else:
            fileName = QtCore.QFileInfo(path).fileName()
            tipSuffix = " - {}".format(path)
            if self.parser.binary:
                tipSuffix += " (binary)"
            elif self.fileFormat == FILE_FORMAT_USDZ:
                tipSuffix += " (zip)"
        text = "*{}*".format(fileName) if dirty else fileName
        self.tabNameChanged.emit(self, text, text + tipSuffix, dirty)

    def setIndentSettings(self, useSpaces=True, tabSpaces=4, autoIndent=True):
        """ Set various indent settings, such as spaces for tabs and auto indentation

        :Parameters:
            useSpaces : `bool`
                Use spaces instead of a tab character
            spaces : `int`
                Tab size in spaces
            autoIndent: `bool`
                Automatically copy indentation from above line with return
        """
        font = self.parent().font()
        width = tabSpaces * QtGui.QFontMetricsF(font).averageCharWidth()
        self.textBrowser.setTabStopWidth(width)
        self.textEditor.setTabStopWidth(width)
        self.textEditor.tabSpaces = tabSpaces
        self.textEditor.useSpaces = useSpaces
        self.textEditor.autoIndent = autoIndent

    def updateHistory(self, url, update=False, truncated=False):
        """ Add a newly created file to the tab's history, cutting off any forward history.

        :Parameters:
            url : `QtCore.QUrl`
                Link for file to add to history list.
            update : `bool`
                Update the path's file status cache.
            truncated : `bool`
                If the file was truncated on read, and therefore should never be edited.
        """
        # Add the previous item to the Back menu.
        # The current item actually isn't displayed in either menu.
        if self.history:
            self.addHistoryAction(self.backMenu)
        self.forwardMenu.clear()

        self.historyIndex += 1
        self.history = self.history[:self.historyIndex]
        self.history.append(FileStatus(url, update=update, truncated=truncated))
        self.updateBreadcrumb()

    def updateBreadcrumb(self):
        """ Update the breadcrumb of file browsing paths and the action for the
        currently open file, which lets us restore the tab after it is closed.
        """
        # Limit the length of the breadcrumb trail.
        # This is pretty much an arbitrary number.
        maxLen = 120

        # Always display the current file in the breadcrumb.
        fullUrlStr = self.getCurrentUrl().toString()
        path = QtCore.QFileInfo(self.getCurrentPath()).fileName()
        crumbLen = len(path)

        # Update action.
        self.action.setText(path)
        self.action.setToolTip(fullUrlStr)

        # Update breadcrumb
        self.breadcrumb = '<a href="{}">{}</a>'.format(fullUrlStr, path)

        # If there are more files, add them, space permitting.
        for i in range(self.historyIndex):
            crumbLen += len(path) + 3  # +3 for the space between crumbs.
            if crumbLen < maxLen:
                # Get the file one back in the history.
                historyItem = self.history[self.historyIndex - (i+1)]
                self.breadcrumb = '<a href="{}">{}</a> &gt; {}'.format(
                    historyItem.url.toString(),
                    historyItem.fileInfo.fileName(),
                    self.breadcrumb)
            else:
                self.breadcrumb = "&hellip; &gt; {}".format(self.breadcrumb)
                break

    def updateFileStatus(self, truncated=False):
        """ Check the status of a file.

        :Parameters:
            truncated : `bool`
                If the file was truncated on read, and therefore should never be edited.
        """
        try:
            self.history[self.historyIndex].updateFileStatus(truncated=truncated)
        except Exception:
            window = self.window()
            window.restoreOverrideCursor()
            window.showCriticalMessage("An error occurred while querying the file status.", traceback.format_exc())


class App(QtCore.QObject):
    """
    Application class that initializes the main Qt window as defined in a ui
    template file.
    """
    # Boolean indicating whether the event loop has already been started.
    _eventLoopStarted = False

    # The QApplication object.
    app = None

    # The QSettings configuration for this application.
    config = None

    # Temporary directory for operations like converting crate to ASCII.
    tmpDir = None

    # Mapping of converted file paths to avoid reconversion if the cached file is still newer.
    fileCache = {}

    # The widget class to build the application's main window.
    uiSource = UsdMngrWindow

    # List of all open windows.
    _windows = []

    appDisplayName = "USD Manager"

    def __init__(self):
        super(App, self).__init__()

        self.appPath = os.path.abspath(sys.argv[0])
        self.appName = os.path.basename(self.appPath)
        self.opts = {
            'dir': os.getcwd(),
        }

    def run(self):
        """ Launch the application.
        """
        parser = argparse.ArgumentParser(prog=os.path.basename(self.appPath), description='File Browser/Text Editor '
                                         'for quick navigation and\nediting among text-based files that reference '
                                         'other files.\n\n')
        parser.add_argument('fileName', nargs='*', help='The file(s) to view.')

        group = parser.add_mutually_exclusive_group()
        group.add_argument("-theme", choices=["light", "dark"],
                           help="Override the user theme preference. Use the Preferences dialog to save this setting)")
        parser.add_argument("-info", action="store_true", help="Log info messages")
        parser.add_argument("-debug", action="store_true", help="Log debugging messages")
        results = parser.parse_args()
        self.opts['info'] = results.info
        self.opts['debug'] = results.debug
        self.opts['theme'] = results.theme

        # Initialize the application and settings.
        self._set_log_level()
        logger.debug("Qt version: %s %s", Qt.__binding__, Qt.__binding_version__)
        # Avoid the following with PySide2: "Qt WebEngine seems to be initialized from a plugin. Please set
        # Qt::AA_ShareOpenGLContexts using QCoreApplication::setAttribute before constructing QGuiApplication."
        if Qt.IsPySide2:
            QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
        self.app = QtWidgets.QApplication(sys.argv)
        self.app.setApplicationName(self.appName)
        self.app.setWindowIcon(QtGui.QIcon(":images/images/logo.png"))
        if Qt.IsPySide2 or Qt.IsPyQt5:
            self.app.setApplicationDisplayName(self.appDisplayName)
        self.app.setOrganizationName("USD")
        self.app.lastWindowClosed.connect(self.onExit)

        # User settings.
        self.config = Settings()

        # App settings.
        appConfigPath = resource_filename(__name__, "config.json")
        try:
            logger.info("Loading app config from %s", appConfigPath)
            with open(appConfigPath) as f:
                appConfig = json.load(f)
        except Exception:
            logger.exception("Failed to load app config from %s", appConfigPath)
            appConfig = {}

        # Find the default icons if this was pip installed with the defaults.
        searchPaths = appConfig.get("themeSearchPaths", [])
        try:
            import crystal_small
        except ImportError:
            logger.debug("Unable to import crystal_small. If icons are missing, check your config and installation.")
        else:
            searchPaths.append(crystal_small.PATH)

        # Define app defaults that we use when the user preference doesn't exist and when resetting preferences in the
        # Preferences dialog.
        self.DEFAULTS = {
            'autoCompleteAddressBar': True,
            'autoIndent': True,
            'defaultPrograms': appConfig.get("defaultPrograms", {}),
            'diffTool': appConfig.get("diffTool", "FC" if os.name == "nt" else "xdiff"),
            'findMatchCase': False,
            'fontSizeAdjust': 0,
            'iconThemes': appConfig.get("iconThemes", {}),
            'includeVisible': True,
            'lastOpenWithStr': "",
            'lineLimit': LINE_LIMIT,
            'lineNumbers': True,
            'newTab': False,
            'parseLinks': True,
            'showAllMessages': True,
            'showHiddenFiles': False,
            'syntaxHighlighting': True,
            'tabSpaces': 4,
            'teletype': True,
            'textEditor': os.getenv("EDITOR", appConfig.get("textEditor", "idle" if os.name == "nt" else "nedit")),
            'theme': None,
            'themeSearchPaths': searchPaths,
            'usdview': appConfig.get("usdview", "usdview"),
            'useSpaces': True,
        }
        
        # Set up icon defaults before loading any windows.
        if self.DEFAULTS['themeSearchPaths']:
            # Ensure themeSearchPaths trumps anything in the default search paths.
            searchPaths = self.DEFAULTS['themeSearchPaths'] + [x for x in QtGui.QIcon.themeSearchPaths()
                                                               if x not in self.DEFAULTS['themeSearchPaths']]
            logger.debug("Theme search paths: %s", searchPaths)
            QtGui.QIcon.setThemeSearchPaths(searchPaths)
        
        # Set the preferred theme name for some non-standard icons.
        for theme in ("light", "dark"):
            if theme not in self.DEFAULTS['iconThemes']:
                self.DEFAULTS['iconThemes'][theme] = appConfig.get("iconTheme", "crystal_project")
        QtGui.QIcon.setThemeName(self.DEFAULTS['iconThemes'][results.theme or "light"])
        utils.ICON_ALIASES.update(appConfig.get("iconAliases", {}))

        # Documentation URL.
        self.appURL = appConfig.get("appURL", "https://github.com/dreamworksanimation/usdmanager")

        # Create a main window.
        window = self.newWindow()

        # Create a temp directory for cache-like files before opening any files.
        self.tmpDir = tempfile.mkdtemp(prefix=self.appName)
        logger.debug("Temp directory: %s", self.tmpDir)

        # Open any files passed in by the user.
        if results.fileName:
            window.setSources(results.fileName)

        # Start the application loop.
        self.mainLoop()

    def _set_log_level(self):
        """ Set the logging level.

        Call this after each component in the case of misbehaving libraries.
        """
        if self.opts['info']:
            logger.setLevel(logging.INFO)
        if self.opts['debug']:
            logger.setLevel(logging.DEBUG)

    def cleanup(self):
        """ Clean up the temp dir.
        """
        if self.tmpDir is not None:
            logger.debug("Removing temp dir: %s", self.tmpDir)
            shutil.rmtree(self.tmpDir, ignore_errors=True)
            self.tmpDir = None

    def createWindowFrame(self):
        """ Create a a new widget based on self.uiSource.

        :Returns:
            A dynamically-created widget object.
        :Rtype:
            CustomWidget
        """
        attribs = {'config' : self.config,
                   'app' : self,
                   'name' : self.uiSource.__name__}
        widgetClass = type("CustomWidget", (self.uiSource, ), attribs)
        return widgetClass()

    def newWindow(self):
        """ Create a new main window.

        :Returns:
            New main window widget
        :Rtype:
            `QtWidgets.QWidget`
        """
        window = self.createWindowFrame()
        self._windows.append(window)
        window.show()
        return window

    def mainLoop(self):
        """ Start the application loop.
        """
        if not App._eventLoopStarted:
            App._eventLoopStarted = True

            # Let the python interpreter continue running every 500 ms so we can cleanly kill the app on a
            # KeyboardInterrupt.
            timer = QtCore.QTimer()
            timer.start(500)
            timer.timeout.connect(lambda: None)

            self.app.exec_()

    @Slot()
    def onExit(self):
        """ Callback when the application is exiting.
        """
        App._eventLoopStarted = False
        self.cleanup()
        logging.shutdown()


class Settings(QtCore.QSettings):
    """ Add a method to get `bool` values from settings, since bool is stored as the `str` "true" or "false."
    """
    def value(self, key, default=None):
        """ PySide2 bug fix of default value of 0 not getting used and None getting returned.

        :Parameters:
            key : `str`
                Key
            default
                Default value, if stored value is None.
        """
        val = super(Settings, self).value(key, default)
        return default if val is None else val

    def boolValue(self, key, default=False):
        """ Boolean values are saved to settings as the string "true" or "false," except on a Mac, where the .plist
        file saves them as actual booleans. Convert a setting back to a bool, since we don't have QVariant objects in
        Qt.py.

        :Parameters:
            key : `str`
                Settings key
            default : `bool`
                Default value if key is undefined
        :Returns:
            True of the value is "true"; otherwise False.
            False if the value is undefined.
        :Rtype:
            `bool`
        """
        val = self.value(key)
        if type(val) is bool:
            return val
        return bool(default) if val is None else val == "true"


def run():
    """ Main entry point to start the application.
    """
    app = App()

    def interrupt(*args):
        """ Cleanly exit the application if a KeyboardInterrupt is detected.
        """
        logger.info("KeyboardInterrupt")
        app.onExit()
        QtWidgets.QApplication.quit()
        sys.exit(0)

    # Allow Ctrl+C to kill the GUI, but first clean up any temp files we left lying around.
    try:
        signal.signal(signal.SIGINT, interrupt)
    except ValueError as e:
        logger.warning("You may not be able to kill this app via Ctrl-C: %s", e)

    app.run()


if __name__ == '__main__':
    run()
