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

        - LineNumbers
        - TextBrowser
        - TextEdit

"""
from __future__ import absolute_import, division, print_function

import argparse
import cgi
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
from collections import defaultdict
from contextlib import contextmanager
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
    LINE_CHAR_LIMIT, LINE_LIMIT, CHAR_LIMIT, FILE_FILTER, FILE_FORMAT_NONE, FILE_FORMAT_USD, FILE_FORMAT_USDA,
    FILE_FORMAT_USDC, FILE_FORMAT_USDZ, HTML_BODY, RECENT_FILES, RECENT_TABS, TTY2HTML, USD_EXTS)
from .file_dialog import FileDialog
from .file_status import FileStatus
from .find_dialog import FindDialog
from .linenumbers import LineNumbers
from .include_panel import IncludePanel
from .plugins import images_rc as plugins_rc
from .plugins import Plugin
from .preferences_dialog import PreferencesDialog


# Set up logging.
logger = logging.getLogger(__name__)
logging.basicConfig()


# Allow Ctrl+C to kill the GUI.
try:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
except ValueError as e:
    logger.warning("You may not be able to kill this app via Ctrl-C: {}".format(e))


# Qt.py compatibility: HACK for missing QUrl.path in PySide2 build.
if Qt.IsPySide2 and not hasattr(QtCore.QUrl, "path"):
    def qUrlPath(self):
        return self.toString(QtCore.QUrl.PrettyDecoded | QtCore.QUrl.RemoveQuery)
    
    QtCore.QUrl.path = qUrlPath


class PathCacheDict(defaultdict):
    """ Cache if file paths referenced more than once in a file exist, so we
    don't check on disk over and over. """
    def __missing__(self, key):
        self[key] = os.path.exists(key)
        return self[key]


class UsdMngrWindow(QtWidgets.QMainWindow):
    """
    File Browser/Text Editor for quick navigation and editing among text-based files that reference other files.
    Normal links are colored blue (USD Crate files are a different shade of blue). The linked file exists.
    Links to multiple files are colored yellow. Files may or may not exist.
    Links that cannot be resolved or confirmed as valid files are colored red.
    
    Ideas (in no particular order):

    - Better usdz support (https://graphics.pixar.com/usd/docs/Usdz-File-Format-Specification.html)

      - Support nested references on read
      - Ability to write and repackage as usdz

    - Add a preference for which files to enable teletype for
      (currently hard-coded to .log and .txt files).
    - Plug-ins based on active file type
      (ABC-specific commands, USD commands, etc.)
    - Link matching RegEx based on active file type instead of all using the
      same rules. Different extensions to search for based on file type, too.
    - Cache converted crate files or previously read in files?
    - Add customized print options like name of file and date headers, similar
      to printing a web page.
    - Move setSource link parsing to a thread?
    - From Pixar: There's one feature in a tool our sim dept wrote that might
      be useful to incorporate into your browser, which can help immensely
      for big files, and it's to basically allow filtering of what gets
      displayed for the usd file's contents. Not just like pattern matching
      so only certain prims/properties get shown (though that is also useful),
      but things like "don't show timeSamples" or "only show first and last
      values for each array with an ellipsis in the middle".
    - Dark theme syntax highlighting could use work. The bare minimum to get
      this working was done.
    - Going from Edit mode back to Browse mode shouldn't reload the document
      if the file on disk hasn't changed. Not sure why this is slower than
      just loading the browse tab in the first place...
    - More detailed history that persists between sessions.
    - Cross-platform testing:

      - Windows mostly untested.
      - Mac could use more testing and work with icons and theme.

    - Remember scroll position per file so going back in history jumps you to
      approximately where you were before.

    Known issues:

        - AddressBar file completer has problems occasionally.
        - Figure out why network printers aren't showing up. Linux or DWA
          issue? macOS and Windows are fine.
        - When reading in a USDZ file, the progress bar gets stuck.
        - Qt.py problems:

          - PyQt5

            - Non-critical messages

              - QStandardPaths: XDG_RUNTIME_DIR not set, defaulting to
                '/tmp/runtime-mdsandell'
              - QXcbConnection: XCB error: 3 (BadWindow), sequence: 878,
                resource id: 26166399, major code: 40 (TranslateCoords),
                minor code: 0

          - PySide2

            - Preferences dialog doesn't center on main window, can't load
              via loadUiType

        - Syntax highlighting for USD and Python incorrectly thinks # is a
          comment even if the # is in a quoted string.

    """
    
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
        
        # Set default programs to a dictionary of extension: program pairs,
        # where the extension is launched with the given program. This is
        # useful for adding custom programs to view things like .exr images or
        # .abc models. A blank string is opened by this app, not launched
        # externally. The user's preferred programs are stored in
        # self.programs.
        self.defaultPrograms = {x: "" for x in USD_EXTS}
        self.defaultPrograms.update(self.app.appConfig.get("defaultPrograms", {}))
        self.programs = self.defaultPrograms
        self.masterHighlighters = {}
        
        self.contextMenuPos = None
        self.overrideCursorSet = False
        self.findDlg = None
        self.lastOpenFileDir = ""
        self.linkHighlighted = QtCore.QUrl("")
        self.quitting = False
        self.stopLoadingTab = False
        # TODO: Will we ever need to support transform timeSamples that use parentheses instead of square brackets?
        self.usdArrayRegEx = re.compile(
            "((?:\s*(?:\w+\s+)?\w+\[\]\s+[\w:]+\s*=|\s*\d+:)\s*\[)" # Array attribute definition and equal sign, or a frame number and colon, plus the opening bracket.
            "\s*(.*)\s*" # Everything inside the square brackets.
            "(\].*)$" # Closing bracket to the end of the line.
        )
        
        self.setupUi()
        self.connectSignals()
        
        # Find and initialize plugins.
        self.plugins = []
        for module in utils.findModules("plugins"):
            for name, cls in inspect.getmembers(module, lambda x: inspect.isclass(x) and issubclass(x, Plugin)):
                try:
                    plugin = cls(self)
                except Exception as e:
                    logger.error("Failed to initialize {}: {}".format(name, e))
                else:
                    self.plugins.append(plugin)
    
    def setupUi(self):
        """ Create and lay out the widgets defined in the ui file,
        then add additional modifications to the UI.
        """
        self.baseInstance = utils.loadUiWidget('main_window.ui', self)
        
        # Set usdview stylesheet.
        if self.app.opts['dark']:
            stylesheet = resource_filename(__name__, "usdviewstyle.qss")
            with open(stylesheet) as f:
                # Qt style sheet accepts only forward slashes as path separators.
                sheetString = f.read().replace('RESOURCE_DIR', os.path.dirname(stylesheet).replace("\\", "/"))
            self.setStyleSheet(sheetString)
            
            # Change some more stuff that the stylesheet doesn't catch.
            p = QtWidgets.QApplication.palette()
            p.setColor(p.Link, QtGui.QColor(0, 205, 250))
            QtWidgets.QApplication.setPalette(p)
            
            # Redefine some colors for the dark theme.
            global HTML_BODY
            HTML_BODY = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" "http://www.w3.org/TR/REC-html40/strict.dtd">
<html><head><style type="text/css">
a.mayNotExist {{color:#CC6}}
a.binary {{color:#69F}}
span.badLink {{color:#F33}}
</style></head><body style="white-space:pre">{}</body></html>"""
            
            highlighter.DARK_THEME = True
        
        # You now have access to the widgets defined in the ui file.
        self.defaultDocFont = QtGui.QFont()
        self.defaultDocFont.setStyleHint(QtGui.QFont.Courier)
        self.defaultDocFont.setFamily("Monospace")
        self.defaultDocFont.setPointSize(9)
        self.defaultDocFont.setBold(False)
        self.defaultDocFont.setItalic(False)
        
        self.readSettings()
        self.compileLinkRegEx()
        
        searchPaths = QtGui.QIcon.themeSearchPaths()
        extraSearchPaths = [x for x in self.app.appConfig.get("themeSearchPaths", []) if x not in searchPaths]
        if extraSearchPaths:
            searchPaths = extraSearchPaths + searchPaths
            QtGui.QIcon.setThemeSearchPaths(searchPaths)
        
        # Set the preferred theme name for some non-standard icons.
        QtGui.QIcon.setThemeName(self.app.appConfig.get("iconTheme", "crystal_project"))
        
        # Try to adhere to the freedesktop icon standards (https://standards.freedesktop.org/icon-naming-spec/icon-naming-spec-latest.html).
        # Some icons are preferred from the crystal_project set, which sadly follows different naming standards.
        # While we can define theme icons in the .ui file, it doesn't give us the fallback option.
        # Additionally, it doesn't work in Qt 4.8.6 but does work in Qt 5.10.0.
        # If you don't have the proper icons installed, the actions simply won't have an icon. It's non-critical.
        ft = QtGui.QIcon.fromTheme
        self.menuOpenRecent.setIcon(ft("document-open-recent"))
        self.actionPrintPreview.setIcon(ft("document-print-preview"))
        self.menuRecentlyClosedTabs.setIcon(ft("document-open-recent"))
        self.actionEdit.setIcon(ft("accessories-text-editor"))
        self.actionIndent.setIcon(ft("format-indent-more"))
        self.actionUnindent.setIcon(ft("format-indent-less"))
        self.exitAction.setIcon(ft("application-exit"))
        self.documentationAction.setIcon(ft("help-browser"))
        self.aboutAction.setIcon(ft("help-about"))
        self.buttonCloseFind.setIcon(ft("window-close"))  # TODO: Need mac icon
        
        # Try for standard name, then fall back to crystal_project name.
        self.actionBrowse.setIcon(ft("applications-internet", ft("Globe")))
        self.actionFileInfo.setIcon(ft("dialog-information", ft("info")))
        self.actionPreferences.setIcon(ft("preferences-system", ft("configure")))
        self.actionZoomIn.setIcon(ft("zoom-in", ft("viewmag+")))
        self.actionZoomOut.setIcon(ft("zoom-out", ft("viewmag-")))
        self.actionNormalSize.setIcon(ft("zoom-original", ft("viewmag1")))
        textEdit = ft("accessories-text-editor", ft("edit"))
        self.actionEdit.setIcon(textEdit)
        self.actionTextEditor.setIcon(textEdit)
        self.buttonGo.setIcon(ft("media-playback-start", ft("1rightarrow")))
        self.actionFullScreen.setIcon(ft("view-fullscreen", ft("window_fullscreen")))
        self.browserReloadIcon = ft("view-refresh", ft("reload"))
        self.actionRefresh.setIcon(self.browserReloadIcon)
        self.browserStopIcon = ft("process-stop", ft("stop"))
        self.actionStop.setIcon(self.browserStopIcon)
        
        # Try for crystal_project name, then fall back to standard name.
        self.actionFind.setIcon(ft("find", ft("edit-find")))
        self.actionOpen.setIcon(ft("fileopen", ft("document-open")))
        self.buttonFindPrev.setIcon(ft("previous", ft("go-previous")))
        self.buttonFindNext.setIcon(ft("next", ft("go-next")))
        self.actionNewWindow.setIcon(ft("new_window", ft("window-new")))
        self.actionOpenWith.setIcon(ft("terminal", ft("utilities-terminal")))
        self.actionPrint.setIcon(ft("printer", ft("document-print")))
        self.actionUndo.setIcon(ft("undo", ft("edit-undo")))
        self.actionRedo.setIcon(ft("redo", ft("edit-redo")))
        self.actionCut.setIcon(ft("editcut", ft("edit-cut")))
        self.actionCopy.setIcon(ft("editcopy", ft("edit-copy")))
        self.actionPaste.setIcon(ft("editpaste", ft("edit-paste")))
        self.actionSelectAll.setIcon(ft("ark_selectall", ft("edit-select-all")))
        self.actionSave.setIcon(ft("filesave", ft("document-save")))
        self.actionSaveAs.setIcon(ft("filesaveas", ft("document-save-as")))
        self.actionBack.setIcon(ft("back", ft("go-previous")))
        self.actionForward.setIcon(ft("forward", ft("go-next")))
        self.actionGoToLineNumber.setIcon(ft("goto", ft("go-jump")))
        newTab = ft("tab_new", ft("tab-new"))
        self.actionNewTab.setIcon(newTab)
        self.buttonNewTab.setIcon(newTab)
        removeTab = ft("tab_remove", ft("window-close"))
        self.actionCloseTab.setIcon(removeTab)
        self.buttonClose.setIcon(removeTab)
        
        # These icons have non-standard names and may only be available in crystal_project icons or a similar set.
        self.binaryIcon = ft("binary")
        self.zipIcon = ft("zip")
        self.actionCommentOut.setIcon(ft("comment"))
        self.actionUncomment.setIcon(ft("removecomment"))
        self.buttonHighlightAll.setIcon(ft("highlight"))
        
        self.aboutQtAction.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_TitleBarMenuButton))
        
        self.actionBrowse.setVisible(False)
        self.actionSelectAll.setEnabled(True)
        self.findWidget.setVisible(False)
        self.labelFindStatus.setVisible(False)
        
        # Some of our objects still need to be modified.
        # Remove them from the layout so everything can be added and placed properly.
        self.verticalLayout.removeWidget(self.buttonGo)
        self.verticalLayout.removeWidget(self.findWidget)
        
        self.includeWidget = IncludePanel(path=self.app.opts['dir'], filter=FILE_FILTER, selectedFilter=FILE_FILTER[FILE_FORMAT_NONE], parent=self)
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
        self.fileStatusButton.setIconSize(QtCore.QSize(16,16))
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
            "QPushButton:hover{border:1px solid #8f8f91; border-radius:3px; background-color:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f6f7fa, stop:1 #dadbde);}"\
            "QPushButton:pressed{background-color:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #dadbde, stop:1 #f6f7fa);}")
        self.tabWidget.setCornerWidget(self.buttonNewTab, QtCore.Qt.TopLeftCorner)
        self.tabWidget.setCornerWidget(self.tabTopRightWidget, QtCore.Qt.TopRightCorner)
        self.tabLayout = QtWidgets.QHBoxLayout(self.tabWidget)
        self.tabLayout.setContentsMargins(0,0,0,0)
        self.tabLayout.setSpacing(5)
        
        # Edit
        self.editWidget = QtWidgets.QWidget(self)
        self.editLayout = QtWidgets.QVBoxLayout(self.editWidget)
        self.editLayout.setContentsMargins(0,0,0,0)
        self.editLayout.addWidget(self.tabWidget)
        self.editLayout.addWidget(self.findWidget)
        
        # Main
        self.verticalLayout.removeWidget(self.mainWidget)
        self.mainWidget = QtWidgets.QSplitter(self)
        self.mainWidget.setContentsMargins(0,0,0,0)
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
        self.actionDuplicateTab = QtWidgets.QAction(ft("tab_duplicate"), "&Duplicate", self)
        self.actionViewSource = QtWidgets.QAction(ft("html"), "View Page So&urce", self)
        
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
        
        # Add one of our special tabs.
        self.newTab()
        self.currTab = self.tabWidget.currentWidget()
        
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
        if (Qt.IsPySide2 or Qt.IsPyQt5) and QtCore.QSysInfo.productType() in ["osx", "macos"]:
            self.buttonTabList.setIcon(ft("1downarrow1"))
            
            # OSX likes to add its own Enter/Exit Full Screen item, not recognizing we already have one.
            self.actionFullScreen.setEnabled(False)
            self.menuView.removeAction(self.actionFullScreen)
    
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
    
    def setHighlighter(self, ext=None):
        """ Set the current tab's highlighter based on the current file extension.
        
        :Parameters:
            ext : `str` | None
                File extension (language) to highlight.
        """
        if ext not in self.masterHighlighters:
            logger.debug("Using default highlighter")
            ext = None
        master = self.masterHighlighters[ext]
        if type(self.currTab.highlighter.master) is not master:
            logger.debug("Setting highlighter to {}".format(ext))
            self.currTab.highlighter.deleteLater()
            self.currTab.highlighter = highlighter.Highlighter(self.currTab.getCurrentTextWidget().document(), master)
    
    def compileLinkRegEx(self):
        """ Compile regular expression to find links based on the acceptable extensions stored in self.programs.
        
        NOTE: If this RegEx is changed, the syntax highlighting rule needs to be as well.
        
        TODO: Support different search rules for different file extensions. Since we use the RegEx match groups in
              setSource, each file type might be responsible for building its own HTML representation at that point.
        """
        exts = self.programs.keys()
        self.re_usd = utils.usdRegEx(exts)
    
    @Slot(QtCore.QPoint)
    def customTextBrowserContextMenu(self, pos):
        """ Slot for the right-click context menu when in Browse mode.
        
        :Parameters:
            pos : `QtCore.QPoint`
                Position of the right-click
        """
        menu = self.currTab.textBrowser.createStandardContextMenu()
        actions = menu.actions()
        # Right now, you may see the open in new tab action even if you aren't
        # hovering over a link. Ideally, because of imperfection with the hovering
        # signal, we would check if the cursor is hovering over a link here.
        if self.linkHighlighted.toString():
            menu.insertAction(actions[0], self.actionOpenLinkNewWindow)
            menu.insertAction(actions[0], self.actionOpenLinkNewTab)
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
                if utils.isUsdFile(path):
                    menu.addAction(self.actionUsdView)
                menu.addAction(self.actionTextEditor)
                menu.addAction(self.actionOpenWith)
                menu.addSeparator()
                menu.addAction(self.actionFileInfo)
                menu.addAction(self.actionViewSource)
        actions[0].setIcon(self.actionCopy.icon())
        actions[3].setIcon(self.actionSelectAll.icon())
        menu.exec_(self.currTab.textBrowser.mapToGlobal(pos))
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
        actions[6].setIcon(QtGui.QIcon.fromTheme("edit-delete"))
        actions[8].setIcon(self.actionSelectAll.icon())
        path = self.currTab.getCurrentPath()
        if path:
            menu.addSeparator()
            if utils.isUsdFile(path):
                menu.addAction(self.actionUsdView)
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
    
    def readSettings(self):
        """ Read in user config settings.
        """
        logger.debug("Reading user settings from {}".format(self.config.fileName()))
        # Get basic preferences.
        # TODO: Read some of these from the same places as the preferences dialog so we don't have to maintain defaults in 2 places.
        self.preferences = {
            'parseLinks': self.config.boolValue("parseLinks", True),
            'newTab': self.config.boolValue("newTab", False),
            'syntaxHighlighting': self.config.boolValue("syntaxHighlighting", True),
            'teletype': self.config.boolValue("teletype", True),
            'lineNumbers': self.config.boolValue("lineNumbers", True),
            'showAllMessages': self.config.boolValue("showAllMessages", True),
            'showHiddenFiles': self.config.boolValue("showHiddenFiles", False),
            'font': self.config.value("font", self.defaultDocFont),
            'fontSizeAdjust': int(self.config.value("fontSizeAdjust", 0)),
            'findMatchCase': self.config.boolValue("findMatchCase", self.checkBoxMatchCase.isChecked()),
            'includeVisible': self.config.boolValue("includeVisible", self.actionIncludePanel.isChecked()),
            'lastOpenWithStr': self.config.value("lastOpenWithStr", ""),
            'textEditor': self.config.value("textEditor", os.getenv("EDITOR", self.app.appConfig.get("textEditor", "nedit"))),
            'diffTool': self.config.value("diffTool", self.app.appConfig.get("diffTool", "xdiff")),
            'autoCompleteAddressBar': self.config.boolValue("autoCompleteAddressBar", True),
            'useSpaces': self.config.boolValue("useSpaces", True),
            'tabSpaces': int(self.config.value("tabSpaces", 4))
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
                    logger.debug("Restoring program for file type {}".format(key))
                    self.programs[key] = self.defaultPrograms[key]
        
        # Set toolbar visibility and positioning.
        standardVis = self.config.boolValue("standardToolbarVisible", True)
        self.editToolbar.setVisible(standardVis)
        self.editToolbar.toggleViewAction().setChecked(standardVis)
        
        # Nav toolbar.
        navVis = self.config.boolValue("navToolbarVisible", True)
        self.navToolbar.setVisible(navVis)
        
        # Get recent files list.
        size = min(self.config.beginReadArray("recentFiles"), RECENT_FILES)
        for i in range(size):
            self.config.setArrayIndex(i)
            path = self.config.value("path")
            if path:
                action = RecentFile(path, self.menuOpenRecent)
                action.openFile.connect(self.setSource)
                self.menuOpenRecent.addAction(action)
        self.config.endArray()
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
        """ Write out user config settings.
        """
        logger.debug("Writing user settings to {}".format(self.config.fileName()))
        self.config.setValue("parseLinks", self.preferences['parseLinks'])
        self.config.setValue("newTab", self.preferences['newTab'])
        self.config.setValue("syntaxHighlighting", self.preferences['syntaxHighlighting'])
        self.config.setValue("teletype", self.preferences['teletype'])
        self.config.setValue("lineNumbers", self.preferences['lineNumbers'])
        self.config.setValue("showAllMessages", self.preferences['showAllMessages'])
        self.config.setValue("showHiddenFiles", self.preferences['showHiddenFiles'])
        self.config.setValue("font", self.preferences['font'])
        self.config.setValue("fontSizeAdjust", self.preferences['fontSizeAdjust'])
        self.config.setValue("findMatchCase", self.preferences['findMatchCase'])
        self.config.setValue("includeVisible", self.preferences['includeVisible'])
        self.config.setValue("lastOpenWithStr", self.preferences['lastOpenWithStr'])
        self.config.setValue("textEditor", self.preferences['textEditor'])
        self.config.setValue("diffTool", self.preferences['diffTool'])
        self.config.setValue("autoCompleteAddressBar", self.preferences['autoCompleteAddressBar'])
        self.config.setValue("useSpaces", self.preferences['useSpaces'])
        self.config.setValue("tabSpaces", self.preferences['tabSpaces'])
        
        # Write self.programs to settings object
        exts = self.programs.keys()
        progs = self.programs.values()
        self.config.beginWriteArray("programs")
        for i in range(len(progs)):
            self.config.setArrayIndex(i)
            self.config.setValue("extension", exts[i])
            self.config.setValue("program", progs[i])
        self.config.endArray()
        
        # Toolbars.
        self.config.setValue("standardToolbarVisible", self.editToolbar.isVisible())
        self.config.setValue("navToolbarVisible", self.navToolbar.isVisible())
        
        self.config.beginWriteArray("recentFiles")
        actions = self.menuOpenRecent.actions()
        for i in range(len(actions)):
            self.config.setArrayIndex(i)
            self.config.setValue("path", actions[i].path)
        self.config.endArray()
        
        # Windows.
        self.config.setValue("geometry", self.saveGeometry())
        self.config.setValue("windowState", self.saveState())
    
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
        self.actionStop.triggered.connect(self.stopTab)
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
        self.actionUsdView.triggered.connect(self.launchUsdView)
        self.actionTextEditor.triggered.connect(self.launchTextEditor)
        self.actionOpenWith.triggered.connect(self.launchProgramOfChoice)
        self.actionOpenLinkWith.triggered.connect(self.onOpenLinkWith)
        # Help Menu
        self.aboutAction.triggered.connect(self.showAboutDialog)
        self.aboutQtAction.triggered.connect(self.showAboutQtDialog)
        self.documentationAction.triggered.connect(self.openUrl)
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
        # Find
        self.buttonCloseFind.clicked.connect(self.toggleFindClose)
        self.findBar.textEdited.connect(self.validateFindBar)
        self.findBar.returnPressed.connect(self.find)
        self.buttonFindPrev.clicked.connect(self.findPrev)
        self.buttonFindNext.clicked.connect(self.find)
        self.buttonHighlightAll.clicked.connect(self.findHighlightAll)
        self.checkBoxMatchCase.stateChanged[int].connect(self.updatePreference_findMatchCase)
    
    def closeEvent(self, event):
        """ Override the default closeEvent called on exit.
        """
        # Check if we want to save any dirty tabs.
        self.quitting = True
        for i in range(self.tabWidget.count()):
            self.tabWidget.setCurrentIndex(0)
            if not self.closeTab():
                # Don't quit.
                event.ignore()
                self.quitting = False
                self.findHighlightAll()
                return
        # Ok to quit.
        self.writeSettings()
        event.accept()
    
    """
    File Menu Methods
    """
    
    @Slot()
    def newWindow(self):
        """ Create a new window.
        
        :Returns:
            New main window widget
        :Rtype:
            `QtGui.QWidget`
        """
        return self.app.newWindow()
    
    @Slot(bool)
    def newTab(self, *args):
        """ Create a new tab.
        """
        newTab = BrowserTab(self.tabWidget)
        newTab.highlighter = highlighter.Highlighter(newTab.getCurrentTextWidget().document(), self.masterHighlighters[None])
        newTab.textBrowser.zoomIn(self.preferences['fontSizeAdjust'])
        newTab.textEditor.zoomIn(self.preferences['fontSizeAdjust'])
        self.tabWidget.setCurrentIndex(self.tabWidget.addTab(newTab, "(Untitled)"))
        self.addressBar.setFocus()
        
        # Add to menu of tabs.
        self.menuTabList.addAction(newTab.action)
        self.connectTabSignals(newTab)
    
    def connectTabSignals(self, tab):
        """ Connect signals for a new tab.
        
        :Parameters:
            tab : `TabWidget`
                Tab widget
        """
        # Keep in sync with signals in disconnectTabSignals.
        tab.openFile.connect(self.onOpen)
        tab.changeTab.connect(self.changeTab)
        tab.restoreTab.connect(self.restoreTab)
        tab.textBrowser.anchorClicked.connect(self.setSource)
        tab.textBrowser.highlighted[QtCore.QUrl].connect(self.hoverUrl)
        tab.textBrowser.customContextMenuRequested.connect(self.customTextBrowserContextMenu)
        tab.textEditor.customContextMenuRequested.connect(self.customTextEditorContextMenu)
        tab.textBrowser.copyAvailable.connect(self.actionCopy.setEnabled)
        tab.textEditor.document().modificationChanged.connect(self.setDirtyTab)
        tab.textEditor.undoAvailable.connect(self.actionUndo.setEnabled)
        tab.textEditor.redoAvailable.connect(self.actionRedo.setEnabled)
        tab.textEditor.copyAvailable.connect(self.actionCopy.setEnabled)
        tab.textEditor.copyAvailable.connect(self.actionCut.setEnabled)
    
    def disconnectTabSignals(self, tab):
        """ Disconnect signals for a tab.
        
        :Parameters:
            tab : `TabWidget`
                Tab widget
        """
        # Keep in sync with signals in connectTabSignals.
        tab.openFile.disconnect(self.onOpen)
        tab.changeTab.disconnect(self.changeTab)
        tab.restoreTab.disconnect(self.restoreTab)
        tab.textBrowser.anchorClicked.disconnect(self.setSource)
        tab.textBrowser.highlighted[QtCore.QUrl].disconnect(self.hoverUrl)
        tab.textBrowser.customContextMenuRequested.disconnect(self.customTextBrowserContextMenu)
        tab.textEditor.customContextMenuRequested.disconnect(self.customTextEditorContextMenu)
        tab.textBrowser.copyAvailable.disconnect(self.actionCopy.setEnabled)
        tab.textEditor.document().modificationChanged.disconnect(self.setDirtyTab)
        tab.textEditor.undoAvailable.disconnect(self.actionUndo.setEnabled)
        tab.textEditor.redoAvailable.disconnect(self.actionRedo.setEnabled)
        tab.textEditor.copyAvailable.disconnect(self.actionCopy.setEnabled)
        tab.textEditor.copyAvailable.disconnect(self.actionCut.setEnabled)
    
    def openFileDialog(self, path=None):
        """ Show the Open File dialog and open any selected files.
        
        :Parameters:
            path : `str` | None
                File path to pre-select on open
        """
        startFilter = FILE_FILTER[self.currTab.fileFormat]
        fd = FileDialog(self, "Open File(s)", self.lastOpenFileDir, FILE_FILTER, startFilter, self.preferences['showHiddenFiles'])
        fd.setFileMode(fd.ExistingFiles)
        if path:
            fd.selectFile(path)
        if fd.exec_() == fd.Accepted:
            paths = fd.selectedFiles()
            if paths:
                self.lastOpenFileDir = QtCore.QFileInfo(paths[0]).absoluteDir().path()
                self.setSources(paths)
    
    @Slot()
    def openFileDialogToCurrentPath(self):
        """ Show the Open File dialog and open any selected files,
        pre-selecting the current file (if any).
        """
        self.openFileDialog(self.currTab.getCurrentPath())
    
    def saveFile(self, filePath, fileFormat=FILE_FORMAT_NONE, _checkUsd=True):
        """ Save the current file as the given filePath.
        
        :Parameters:
            filePath : `str`
                Path to save file as.
            fileFormat : `int`
                File format when saving as a generic extension
            _checkUsd : `bool`
                Check if this needs to be written as a binary USD file instead of a text file
        :Returns:
            If saved or not.
        :Rtype:
            `bool`
        """
        logger.debug("Checking file status")
        path = QtCore.QFile(filePath)
        if path.exists() and not QtCore.QFileInfo(path).isWritable():
            self.showCriticalMessage("The file is not writable.\n{}".format(filePath), title="Save File")
            return False
        logger.debug("Writing file")
        self.setOverrideCursor()
        
        # If the file is originally a usd crate file or the user is saving it with the .usdc extension, or the user is
        # saving it with .usd but fileFormat is set to usdc, save to a temp file then usdcat back to a binary file.
        crate = False
        _, ext = os.path.splitext(filePath)
        if _checkUsd:
            if ext == ".usdc":
                crate = True
            elif ext == ".usd" and (fileFormat == FILE_FORMAT_USDC or (fileFormat == FILE_FORMAT_NONE and self.currTab.fileFormat == FILE_FORMAT_USDC)):
                crate = True
        if crate:
            fd, tmpPath = tempfile.mkstemp(suffix=".usd", dir=self.app.tmpDir)
            os.close(fd)
            status = False
            if self.saveFile(tmpPath, fileFormat, False):
                try:
                    logger.debug("Converting back to USD crate file")
                    utils.usdcat(tmpPath, filePath, format="usdc")
                except Exception:
                    logger.debug("Save failed on USD crate conversion")
                    self.restoreOverrideCursor()
                    self.showCriticalMessage("The file could not be saved due to a usdcat error!", traceback.format_exc(), "Save File")
                else:
                    status = True
                    self.currTab.fileFormat = FILE_FORMAT_USDC
                    self.restoreOverrideCursor()
            else:
                self.restoreOverrideCursor()
            os.remove(tmpPath)
            return status
        elif fileFormat == FILE_FORMAT_USDZ:
            # TODO: usdz support
            self.restoreOverrideCursor()
            self.showCriticalMessage("Writing usdz files is not yet supported!", title="Save File")
            return False
        elif path.open(QtCore.QIODevice.WriteOnly | QtCore.QIODevice.Text):
            try:
                # Which method is better?
                path.write(str(self.currTab.textEditor.toPlainText()))
                #out = QtCore.QTextStream(path)
                #out << self.currTab.textEditor.toPlainText()
            except Exception:
                self.restoreOverrideCursor()
                self.showCriticalMessage("The file could not be saved!", traceback.format_exc(), "Save File")
                return False
            else:
                if ext in [".usd", ".usda"]:
                    self.currTab.fileFormat = FILE_FORMAT_USDA
                else:
                    self.currTab.fileFormat = FILE_FORMAT_NONE
                self.restoreOverrideCursor()
            finally:
                path.close()
            self.setDirtyTab(False)
            return True
        else:
            self.restoreOverrideCursor()
            self.showCriticalMessage("The file could not be opened for saving!", title="Save File")
            return False
    
    def getSaveAsPath(self, path=None):
        """ Get a path from the user to save an arbitrary file as.
        
        :Parameters:
            path : `str` | None
                Path to use for selecting default file extension filter.
        :Returns:
            Tuple of the absolute path user wants to save file as (or None if no file was selected or an error occurred)
            and the file format if explicitly set for USD files (e.g. usda)
        :Rtype:
            (`str`|None, `int`)
        """
        fileFormat = FILE_FORMAT_NONE
        if path:
            startFilter = FILE_FILTER[FILE_FORMAT_USD if utils.isUsdFile(path) else FILE_FORMAT_NONE]
        else:
            path = self.currTab.getCurrentPath()
            startFilter = FILE_FILTER[self.currTab.fileFormat]
        
        dlg = FileDialog(self, "Save File As", path or self.lastOpenFileDir, FILE_FILTER, startFilter, self.preferences['showHiddenFiles'])
        dlg.setAcceptMode(dlg.AcceptSave)
        dlg.setFileMode(dlg.AnyFile)
        if dlg.exec_() != dlg.Accepted:
            return None, fileFormat
        
        filePaths = dlg.selectedFiles()
        if not filePaths or not filePaths[0]:
            return None, fileFormat
        
        filePath = filePaths[0]
        selectedFilter = dlg.selectedNameFilter()
        
        # TODO: Is there a more generic way to enforce this?
        modifiedExt = False
        validExts = [x.lstrip("*") for x in selectedFilter.rsplit("(", 1)[1].rsplit(")", 1)[0].split()]
        _, ext = os.path.splitext(filePath)
        if selectedFilter == FILE_FILTER[FILE_FORMAT_USD]:
            if ext not in validExts:
                self.showCriticalMessage("Please enter a valid extension for a usd file")
                return self.getSaveAsPath(filePath)
            if ext == ".usda":
                fileFormat = FILE_FORMAT_USDA
            elif ext == ".usdc":
                fileFormat = FILE_FORMAT_USDC
            elif ext == ".usdz":
                fileFormat = FILE_FORMAT_USDZ
        elif selectedFilter == FILE_FILTER[FILE_FORMAT_USDA]:
            fileFormat = FILE_FORMAT_USDA
            if ext not in validExts:
                self.showCriticalMessage("Please enter a valid extension for a usda file")
                return self.getSaveAsPath(filePath)
        elif selectedFilter == FILE_FILTER[FILE_FORMAT_USDC]:
            fileFormat = FILE_FORMAT_USDC
            if ext not in validExts:
                self.showCriticalMessage("Please enter a valid extension for a usdc file")
                return self.getSaveAsPath(filePath)
        elif selectedFilter == FILE_FILTER[FILE_FORMAT_USDZ]:
            fileFormat = FILE_FORMAT_USDZ
            if ext not in validExts:
                # Sanity check in case we ever allow more extensions.
                if len(validExts) == 1:
                    # Just add the .usdz extension since it can't be anything else.
                    filePath += ".usdz"
                    modifiedExt = True
                else:
                    self.showCriticalMessage("Please enter a valid extension for a usdz file")
                    return self.getSaveAsPath(filePath)
        
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
                return self.getSaveAsPath(path)
        
        # Now we have a valid path to save as.
        return filePath, fileFormat
    
    @Slot()
    def saveFileAs(self):
        """ Save the current file with a new filename.
        
        :Returns:
            If saved or not.
        :Rtype:
            `bool`
        """
        filePath, fileFormat = self.getSaveAsPath()
        if filePath is not None:
            # Save file and apply new name where needed.
            if self.saveFile(filePath, fileFormat):
                idx = self.tabWidget.currentIndex()
                fileInfo = QtCore.QFileInfo(filePath)
                fileName = fileInfo.fileName()
                ext = fileInfo.suffix()
                self.tabWidget.setTabText(idx, fileName)
                if self.currTab.fileFormat == FILE_FORMAT_USDC:
                    self.tabWidget.setTabIcon(idx, self.binaryIcon)
                    self.tabWidget.setTabToolTip(idx, "{} - {} (binary)".format(fileName, filePath))
                elif self.currTab.fileFormat == FILE_FORMAT_USDZ:
                    self.tabWidget.setTabIcon(idx, self.zipIcon)
                    self.tabWidget.setTabToolTip(idx, "{} - {} (zip)".format(fileName, filePath))
                else:
                    self.tabWidget.setTabIcon(idx, QtGui.QIcon())
                    self.tabWidget.setTabToolTip(idx, "{} - {}".format(fileName, filePath))
                self.currTab.updateHistory(QtCore.QUrl(filePath))
                self.currTab.updateFileStatus()
                self.setHighlighter(ext)
                self.updateButtons()
                return True
        return False
    
    @Slot()
    def saveLinkAs(self):
        """ The user right-clicked a link and wants to save it as a new file.
        Get a new file path with the Save As dialog and copy the original file to the new file,
        opening the new file in a new tab.
        """
        path = self.linkHighlighted.toString(QtCore.QUrl.RemoveQuery)
        if "*" in path or "<UDIM>" in path:
            self.showWarningMessage("Link could not be resolved as it may point to multiple files.")
            return
        
        qFile = QtCore.QFile(path)
        if qFile.exists():
            saveAsPath, fileFormat = self.getSaveAsPath(path)
            if saveAsPath is not None:
                try:
                    if fileFormat == self.currTab.fileFormat:
                        qFile.copy(saveAsPath)
                        self.setSource(QtCore.QUrl(saveAsPath), newTab=True)
                    else:
                        # Open the link first so it's easier to use the saveFile functionality to handle format conversion.
                        self.setSource(self.linkHighlighted, newTab=True)
                        self.saveFile(saveAsPath, fileFormat)
                        self.setSource(QtCore.QUrl(saveAsPath))
                except Exception:
                    self.showCriticalMessage("Unable to save {} as {}.".format(path, saveAsPath), traceback.format_exc(), "Save Link As")
        else:
            self.showWarningMessage("Selected file does not exist.")
    
    @Slot()
    def saveTab(self):
        """ If the file already has a name, save it;
        otherwise, get a filename and save it.
        
        :Returns:
            If saved or not.
        :Rtype:
            `bool`
        """
        filePath = self.currTab.getCurrentPath()
        if filePath:
            return self.saveFile(filePath)
        else:
            return self.saveFileAs()
    
    @Slot(bool)
    def printDialog(self, checked=False):
        """ Open a print dialog.
        
        :Parameters:
            checked : `bool`
                For signal only
        """
        if QtPrintSupport is None:
            self.showWarningMessage("Printing is not supported on your system, as Qt.QtPrintSupport could not be imported.")
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
            self.showWarningMessage("Printing is not supported on your system, as Qt.QtPrintSupport could not be imported.")
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
                Try to close this specific tab instead of where the context
                menu originated.
        :Returns:
            If the tab was closed or not.
            If the tab needed to be saved, for example, and the user cancelled,
            this returns False.
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
                self.tabWidget.setCurrentWidget(prevTab)
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
        logger.debug("moveTabAcrossWindows {} {} {} {}".format(fromIndex, toIndex, fromWindow, toWindow))
        
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
        dstWindow.setHighlighter(ext)
    
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
    
    """
    Edit Menu Methods
    """
    
    @Slot()
    def toggleEdit(self):
        """ Switch between Browse mode and Edit mode.
        
        :Returns:
            True if we switched modes; otherwise, False.
            This only returns False if we were in Edit mode and the user cancelled due to unsaved changes.
        :Rtype:
            `bool`
        """
        # Don't change between browse and edit mode if dirty. Saves if needed.
        if not self.dirtySave():
            return False
        
        # Toggle edit mode
        self.currTab.inEditMode = not self.currTab.inEditMode
        if self.currTab.inEditMode:
            # Set editor's scroll position to browser's position.
            hScrollPos = self.currTab.textBrowser.horizontalScrollBar().value()
            vScrollPos = self.currTab.textBrowser.verticalScrollBar().value()
            self.currTab.textBrowser.setVisible(False)
            self.currTab.textEditor.setVisible(True)
            self.currTab.lineNumbers.setTextWidget(self.currTab.textEditor)
            self.currTab.textEditor.setFocus()
            self.currTab.textEditor.horizontalScrollBar().setValue(hScrollPos)
            self.currTab.textEditor.verticalScrollBar().setValue(vScrollPos)
        else:
            # Set browser's scroll position to editor's position.
            hScrollPos = self.currTab.textEditor.horizontalScrollBar().value()
            vScrollPos = self.currTab.textEditor.verticalScrollBar().value()
            self.refreshTab()
            self.currTab.textEditor.setVisible(False)
            self.currTab.textBrowser.setVisible(True)
            self.currTab.lineNumbers.setTextWidget(self.currTab.textBrowser)
            self.currTab.textBrowser.setFocus()
            self.currTab.textBrowser.horizontalScrollBar().setValue(hScrollPos)
            self.currTab.textBrowser.verticalScrollBar().setValue(vScrollPos)
        
        # Update highlighter.
        self.currTab.highlighter.setDocument(self.currTab.getCurrentTextWidget().document())
        
        self.updateEditButtons()
        self.editModeChanged.emit(self.currTab.inEditMode)
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
    
    @Slot()
    def toggleFindClose(self):
        """ Hide the Find bar.
        """
        self.findWidget.setVisible(False)
    
    @Slot()
    def find(self, flags=None, startPos=3, loop=True):
        """ Find next hit for the search text.
        
        :Parameters:
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
        else: # startPos == 3
            currPos = currTextWidget.textCursor().selectionEnd()
        
        # Find text.
        cursor = currTextWidget.document().find(self.findBar.text(), currPos, searchFlags)
        
        if cursor.hasSelection():
            # Found phrase. Set cursor and formatting.
            currTextWidget.setTextCursor(cursor)
            self.findBar.setStyleSheet("QLineEdit{{background:{}}}".format("inherit" if self.app.opts['dark'] else "none"))
            if loop:
                # Didn't just loop through the document, so hide any messages.
                self.labelFindPixmap.setVisible(False)
                self.labelFindStatus.setVisible(False)
        elif loop:
            self.labelFindPixmap.setPixmap(self.browserReloadIcon.pixmap(16,16))
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
            self.labelFindPixmap.setPixmap(self.browserStopIcon.pixmap(16,16))
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
    
    @Slot()
    def findHighlightAll(self):
        """ Highlight all hits for the search text.
        """
        phrase = self.findBar.text() if self.buttonHighlightAll.isChecked() else highlighter.DONT_MATCH_PHRASE
        if phrase != self.masterHighlighters[None].findPhrase:
            for lang, h in self.masterHighlighters.iteritems():
                h.setFindPhrase(phrase)
        if self.currTab.highlighter.dirty:
            with self.overrideCursor():
                self.currTab.highlighter.rehighlight()
    
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
    def find2(self, startPos=3, loop=True, findText=None):
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
        """
        # Set options.
        searchFlags = QtGui.QTextDocument.FindFlags()
        if self.findDlg.caseSensitiveCheck.isChecked():
            searchFlags |= QtGui.QTextDocument.FindCaseSensitively
        if self.findDlg.wholeWordsCheck.isChecked():
            searchFlags |= QtGui.QTextDocument.FindWholeWords
        if self.findDlg.searchBackwardsCheck.isChecked():
            searchFlags |= QtGui.QTextDocument.FindBackward
            if startPos == 3:
                startPos = 2
        
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
        else: # startPos == 3
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
            return self.find2(startPos=startPos, loop=False)
        else:
            self.findDlg.statusBar.showMessage("Phrase not found")
            self.findDlg.setStyleSheet("QLineEdit#findLineEdit{background:salmon}")
            return False
    
    @Slot()
    def replace(self, findText=None, replaceText=None):
        """ Replace next hit for the search text.
        """
        if findText is None:
            findText = self.getFindText()
        if replaceText is None:
            replaceText = self.getReplaceText()
        
        # If we already have a selection.
        cursor = self.currTab.textEditor.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == findText:
            self.currTab.textEditor.insertPlainText(replaceText)
            self.findDlg.statusBar.showMessage("1 occurrence replaced.")
        # If we don't have a selection, try to get a new one.
        elif self.find2(findText):
            self.replace(findText, replaceText)
    
    @Slot()
    def replaceFind(self):
        """ Replace next hit for the search text, then find the next after that.
        """
        self.replace()
        self.find2()
    
    @Slot()
    def replaceAll(self):
        """ Replace all occurrences of the search text.
        """
        count = 0
        
        with self.overrideCursor():
            findText = self.getFindText()
            replaceText = self.getReplaceText()
            found = self.findAndReplace(findText, replaceText)
            while found:
                count += 1
                found = self.findAndReplace(findText, replaceText, startPos=3)
        
        if count > 0:
            self.findDlg.setStyleSheet("QLineEdit#findLineEdit{background:none}")
            self.findDlg.statusBar.showMessage("{} occurrence{} replaced.".format(count, '' if count == 1 else 's'))
        else:
            self.findDlg.statusBar.showMessage("Phrase not found. 0 occurrences replaced.")
    
    @Slot()
    def replaceAllInOpenFiles(self):
        """ Iterate through all the writable tabs, finding and replacing the search text.
        """
        count = files = 0
        
        with self.overrideCursor():
            findText = self.getFindText()
            replaceText = self.getReplaceText()
            origTab = self.tabWidget.currentIndex()

            for i in range(self.tabWidget.count()):
                self.tabWidget.setCurrentIndex(i)
                status = self.currTab.getFileStatus()
                if not status.writable:
                    continue
                if not self.currTab.inEditMode:
                    self.toggleEdit()
                fileChanged = False
                found = self.findAndReplace(findText, replaceText)
                while found:
                    fileChanged = True
                    count += 1
                    found = self.findAndReplace(findText, replaceText, startPos=3)
                if fileChanged:
                    files += 1
            
            # End on the original tab.
            if self.tabWidget.currentIndex() != origTab:
                self.tabWidget.setCurrentIndex(origTab)
        
        if count > 0:
            self.findDlg.setStyleSheet("QLineEdit#findLineEdit{background:none}")
            self.findDlg.statusBar.showMessage("{} occurrence{} replaced in {} file{}.".format(
                count, '' if count == 1 else 's', files, '' if files == 1 else 's'))
        else:
            self.findDlg.statusBar.showMessage("Phrase not found. 0 occurrences replaced.")
    
    def findAndReplace(self, findText, replaceText, startPos=0):
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
        if self.find2(startPos=startPos, loop=False, findText=findText):
            # ...and replace it.
            cursor = self.currTab.textEditor.textCursor()
            if cursor.hasSelection() and cursor.selectedText() == findText:
                self.currTab.textEditor.insertPlainText(replaceText)
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
            self.goToLineNumber(line[0])
    
    def goToLineNumber(self, line=1):
        """ Go to the given line number
        
        :Parameters:
            line : `int`
                Line number to scroll to. Defaults to 1 (top of document).
        """
        textWidget = self.currTab.getCurrentTextWidget()
        block = textWidget.document().findBlockByNumber(line - 1)
        cursor = textWidget.textCursor()
        cursor.setPosition(block.position())
        # Highlight entire line.
        pos = block.position() + block.length() - 1
        if pos != -1:
            cursor.setPosition(pos, QtGui.QTextCursor.KeepAnchor)
            textWidget.setTextCursor(cursor)
            textWidget.ensureCursorVisible()
    
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
            # Save new preferences.
            self.preferences['parseLinks'] = dlg.getPrefParseLinks()
            self.preferences['newTab'] = dlg.getPrefNewTab()
            self.preferences['syntaxHighlighting'] = dlg.getPrefSyntaxHighlighting()
            self.preferences['teletype'] = dlg.getPrefTeletypeConversion()
            self.preferences['lineNumbers'] = dlg.getPrefLineNumbers()
            self.preferences['showAllMessages'] = dlg.getPrefShowAllMessages()
            self.preferences['showHiddenFiles'] = dlg.getPrefShowHiddenFiles()
            self.preferences['autoCompleteAddressBar'] = dlg.getPrefAutoCompleteAddressBar()
            self.preferences['textEditor'] = dlg.getPrefTextEditor()
            self.preferences['diffTool'] = dlg.getPrefDiffTool()
            self.preferences['font'] = dlg.getPrefFont()
            self.preferences['useSpaces'] = dlg.getPrefUseSpaces()
            self.preferences['tabSpaces'] = dlg.getPrefTabSpaces()
            
            # Update font and line number visibility in all tabs.
            self.tabWidget.setFont(self.preferences['font'])
            self.includeWidget.showAll(self.preferences['showHiddenFiles'])
            
            for w in self.tabIterator():
                w.textBrowser.setFont(self.preferences['font'])
                w.textBrowser.zoomIn(self.preferences['fontSizeAdjust'])
                w.textEditor.setFont(self.preferences['font'])
                w.textEditor.zoomIn(self.preferences['fontSizeAdjust'])
                w.lineNumbers.setVisible(self.preferences['lineNumbers'])
                w.setTabSpaces(self.preferences['useSpaces'], self.preferences['tabSpaces'])
            
            programs = dlg.getPrefPrograms()
            if programs != self.programs:
                self.programs = programs
                # Update regex used for searching links.
                self.compileLinkRegEx()
                # Update highlighter.
                for lang, h in self.masterHighlighters.iteritems():
                    h.setLinkPattern(self.programs)
            
            for lang, h in self.masterHighlighters.iteritems():
                h.setSyntaxHighlighting(self.preferences['syntaxHighlighting'])
            
            # Enable/Disable completer on address bar.
            if self.preferences['autoCompleteAddressBar']:
                self.addressBar.setCompleter(self.addressBar.customCompleter)
            else:
                self.addressBar.setCompleter(QtWidgets.QCompleter())
            
            if not self.currTab.isDirty():
                self.refreshTab()
            
            self.writeSettings()
    
    @Slot(int)
    def updatePreference_findMatchCase(self, checked):
        """ Stores a bool representation of checkbox's state.
        
        :Parameters:
            checked : `int`
                State of checkbox.
        """
        checked = checked & QtCore.Qt.Checked
        if checked != self.preferences['findMatchCase']:
            self.preferences['findMatchCase'] = checked
            for lang, h in self.masterHighlighters.iteritems():
                h.setFindCase(checked)
            with self.overrideCursor():
                self.currTab.highlighter.rehighlight()
    
    @Slot(str)
    def validateFindBar(self, text):
        """ Update widgets on the Find bar as the search text changes.
        
        :Parameters:
            text : `str`
                Current text in the find bar.
        """
        if text != "":
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
            self.findBar.setStyleSheet("QLineEdit{{background:{}}}".format("inherit" if self.app.opts['dark'] else "none"))
            self.labelFindPixmap.setVisible(False)
            self.labelFindStatus.setVisible(False)
    
    """
    View Menu Methods
    """
    
    @Slot(bool)
    def toggleInclude(self, checked):
        """ Show/Hide the side file browser.
        
        :Parameters:
            checked : `bool`
                State of checked menu.
        """
        self.preferences['includeVisible'] = checked
        # Set back to default size.
        if checked:
            self.mainWidget.setSizes([1, 1500])  # TODO: Not sure why this works or how it should really be done.
        # Collapse the splitter.
        else:
            self.mainWidget.setSizes([0, 1500])
    
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
        origPath = self.tabWidget.widget(origIndex).getCurrentUrl()
        
        # Create a new tab and select it, positioning it immediately after the original tab.
        self.newTab()
        fromIndex = self.tabWidget.currentIndex()
        toIndex = origIndex + 1
        if fromIndex != toIndex:
            self.tabWidget.moveTab(fromIndex, toIndex)
        
        # Open the same document as the original tab.
        if not origPath.isEmpty():
            self.setSource(origPath)
    
    @Slot()
    def refreshSelectedTab(self):
        """ Refresh the tab that was right-clicked.
        """
        currIndex = self.tabWidget.currentIndex()
        selectedIndex = self.tabWidget.tabBar.tabAt(self.contextMenuPos)
        selectedTab = self.tabWidget.widget(selectedIndex)
        self.tabWidget.setCurrentIndex(selectedIndex)
        self.setSource(selectedTab.getCurrentUrl(), isNewFile=False,
                       hScrollPos=selectedTab.getCurrentTextWidget().horizontalScrollBar().value(),
                       vScrollPos=selectedTab.getCurrentTextWidget().verticalScrollBar().value())
        self.tabWidget.setCurrentIndex(currIndex)
    
    @Slot()
    def refreshTab(self):
        """ Refresh the current tab.
        """
        # Only refresh the tab if the refresh action is enabled, since the F5 shortcut is never disabled,
        # and methods sometimes call this directly even though we do not want to refresh.
        if self.actionRefresh.isEnabled():
            self.setSource(self.currTab.getCurrentUrl(), isNewFile=False,
                           hScrollPos=self.currTab.getCurrentTextWidget().horizontalScrollBar().value(),
                           vScrollPos=self.currTab.getCurrentTextWidget().verticalScrollBar().value())
    
    @Slot()
    def stopTab(self):
        """ Stop loading the current tab.
        """
        self.stopLoadingTab = True
    
    @Slot()
    def increaseFontSize(self):
        """ Increase font size in the text browser and editor.
        """
        for w in self.tabIterator():
            w.textBrowser.zoomIn()
            w.textEditor.zoomIn()
        self.preferences['fontSizeAdjust'] += 1
    
    @Slot()
    def decreaseFontSize(self):
        """ Decrease font size in the text browser and editor.
        """
        for w in self.tabIterator():
            w.textBrowser.zoomOut()
            w.textEditor.zoomOut()
        self.preferences['fontSizeAdjust'] -= 1
    
    @Slot()
    def defaultFontSize(self):
        """ Reset the text browser and editor to the default font size.
        """
        for w in self.tabIterator():
            w.textBrowser.zoomIn(-self.preferences['fontSizeAdjust'])
            w.textEditor.zoomIn(-self.preferences['fontSizeAdjust'])
        self.preferences['fontSizeAdjust'] = 0
    
    @Slot(bool)
    def toggleFullScreen(self, *args):
        """ Toggle between full screen mode
        """
        self.setWindowState(self.windowState() ^ QtCore.Qt.WindowFullScreen)
    
    """
    History Menu Methods
    """
    
    @Slot()
    def browserBack(self):
        """ Go back one step in history for the current tab.
        """
        # Check if there are any changes to be saved before we modify the history.
        if not self.dirtySave():
            return
        self.currTab.historyIndex -= 1
        self.currTab.updateBreadcrumb()
        self.setSource(self.currTab.getCurrentUrl(), isNewFile=False)
    
    @Slot()
    def browserForward(self):
        """ Go forward one step in history for the current tab.
        """
        # Check if there are any changes to be saved before we modify the history.
        if not self.dirtySave():
            return
        self.currTab.historyIndex += 1
        self.currTab.updateBreadcrumb()
        self.setSource(self.currTab.getCurrentUrl(), isNewFile=False)
    
    @Slot(QtWidgets.QWidget)
    def restoreTab(self, tab):
        """ Restore a previously closed tab.
        
        :Parameters:
            tab : `QtWidgets.QWidget`
                Tab widget
        """
        # Find out if current tab is blank.
        index = None
        if self.currTab.isNewTab:
            index = self.tabWidget.currentIndex()
        
        self.tabWidget.setCurrentIndex(self.tabWidget.addTab(tab, QtCore.QFileInfo(tab.getCurrentPath()).fileName()))
        
        # If we had a blank tab to start with, remove it.
        if index is not None:
            self.tabWidget.removeTab(index)
            self.menuTabList.removeAction(self.menuTabList.actions()[index])
            
        # Remove from recently closed tabs menu.
        self.menuRecentlyClosedTabs.removeAction(tab.action)
        # Re-activate tab.
        self.currTab.isActive = True
        # Add to current tabs list.
        self.menuTabList.addAction(tab.action)
        
        # Disable menu if there are no more recent tabs.
        if not self.menuRecentlyClosedTabs.actions():
            self.menuRecentlyClosedTabs.setEnabled(False)
        
        # Update settings in the recently re-opened tab that may have changed.
        if self.preferences['font'] != self.defaultDocFont:
            tab.textBrowser.setFont(self.preferences['font'])
            tab.textEditor.setFont(self.preferences['font'])
        tab.lineNumbers.setVisible(self.preferences['lineNumbers'])
    
    """
    Commands Menu Methods
    """
    @Slot()
    def diffFile(self):
        """ Compare current version of file in app to current version on disk.
        Allows you to make comparisons using a temporary file, without saving your changes.
        """
        path = self.currTab.getCurrentPath()
        fd, tmpPath = tempfile.mkstemp(suffix=QtCore.QFileInfo(path).fileName(), dir=self.app.tmpDir)
        with os.fdopen(fd, 'w') as f:
            f.write(self.currTab.textEditor.toPlainText())
        args = shlex.split(self.preferences['diffTool']) + [path, tmpPath]
        self.launchProcess(args)
    
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
        size = info.size()
        owner = info.owner()
        modified = info.lastModified().toString()
        
        # Former PyQt4 way before moving to getPermissionString method.
        """
        perms = info.permissions()
        permissions = "-"
        permissions += "r" if perms & QtCore.QFile.ReadUser else "-"
        permissions += "w" if perms & QtCore.QFile.WriteUser else "-"
        permissions += "x" if perms & QtCore.QFile.ExeUser else "-"
        permissions += "r" if perms & QtCore.QFile.ReadGroup else "-"
        permissions += "w" if perms & QtCore.QFile.WriteGroup else "-"
        permissions += "x" if perms & QtCore.QFile.ExeGroup else "-"
        permissions += "r" if perms & QtCore.QFile.ReadOther else "-"
        permissions += "w" if perms & QtCore.QFile.WriteOther else "-"
        permissions += "x" if perms & QtCore.QFile.ExeOther else "-"
        """
        permissions = self.getPermissionString(path)
        
        # Create dialog to display info.
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowIcon(self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogInfoView))
        dlg.setWindowTitle("File Information")
        layout = QtWidgets.QGridLayout(dlg)
        labelName = QtWidgets.QLabel("<b>{}</b>".format(info.fileName()))
        labelName.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(labelName, 0, 0, 1, 0)
        labelPath1        = QtWidgets.QLabel("Full path:")
        labelPath2        = QtWidgets.QLabel(path)
        labelSize1        = QtWidgets.QLabel("Size:")
        labelSize2        = QtWidgets.QLabel(utils.humanReadableSize(size))
        labelPermissions1 = QtWidgets.QLabel("Permissions:")
        labelPermissions2 = QtWidgets.QLabel(permissions)
        labelOwner1       = QtWidgets.QLabel("Owner:")
        labelOwner2       = QtWidgets.QLabel(owner)
        labelModified1    = QtWidgets.QLabel("Modified:")
        labelModified2    = QtWidgets.QLabel(modified)
        # Set text interaction.
        labelName.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        labelPath2.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        labelSize2.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        labelPermissions2.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        labelOwner2.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        labelModified2.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        # Add to layout.
        layout.addWidget(labelPath1,        1, 0)
        layout.addWidget(labelPath2,        1, 1)
        layout.addWidget(labelSize1,        2, 0)
        layout.addWidget(labelSize2,        2, 1)
        layout.addWidget(labelPermissions1, 3, 0)
        layout.addWidget(labelPermissions2, 3, 1)
        layout.addWidget(labelOwner1,       4, 0)
        layout.addWidget(labelOwner2,       4, 1)
        layout.addWidget(labelModified1,    5, 0)
        layout.addWidget(labelModified2,    5, 1)
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
        path = self.currTab.getCurrentPath()
        args = shlex.split(self.preferences['textEditor']) + [path]
        self.launchProcess(args)
    
    @Slot()
    def launchUsdView(self):
        """ Launch the current file in usdview.
        """
        path = self.currTab.getCurrentPath()
        args = [self.app.appConfig.get("usdview", "usdview"), path]
        self.launchProcess(args)
    
    @Slot()
    def launchProgramOfChoice(self, path=None):
        """ Open a file with a program given by the user.
        
        :Parameters:
            path : `str`
                File to open. If None, use currently open file.
        """
        if path is None:
            path = self.currTab.getCurrentPath()
        
        # Get program of choice from user.
        prog, ok = QtWidgets.QInputDialog.getText(
                    self, "Open with...",
                    "Please enter the program you would like to open this file with.\n"
                    "You may include command line options as well, and the file path will be appended to the end of the command.\n\n"
                    "Example:\n    usdview --unloaded\n    rm\n",
                    QtWidgets.QLineEdit.Normal, self.preferences['lastOpenWithStr'])
        # Return if cancel was pressed or nothing entered.
        if not ok or not prog:
            return
        
        # Store command for future convenience.
        self.preferences['lastOpenWithStr'] = prog
        
        # Launch program.
        args = shlex.split(prog) + [path]
        self.launchProcess(args)
    
    """
    Help Menu Methods
    """
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
    def openUrl(self, checked=False, url=None):
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
    
    """
    Extra Keyboard Shortcuts
    """
    
    @Slot()
    def onBackspace(self):
        """ Handle the Backspace key for back browser navigation.
        """
        # Need this test since the Backspace keyboard shortcut is always linked to this method.
        if self.currTab.isBackwardAvailable() and not self.currTab.inEditMode:
            self.browserBack()
    
    """
    Miscellaneous Methods
    """
    @staticmethod
    def convertTeletype(t):
        """ Convert teletype codes to HTML styles.
        This method assumes you have already escaped any necessary HTML characters.
        
        :Parameters:
            t : `str`
                Original text
        :Returns:
            String with teletype codes converted to HTML styles.
        :Rtype:
            `str`
        """
        for (code, style) in TTY2HTML:
            t = t.replace(code, style)
        return "<span>{}</span>".format(t)
    
    @Slot(QtCore.QUrl)
    def hoverUrl(self, link):
        """ Slot called when the mouse hovers over a URL.
        """
        pathNoQuery = link.toString(QtCore.QUrl.RemoveQuery)
        if utils.queryItemBoolValue(link, "binary"):
            self.statusbar.showMessage("{} (binary)".format(pathNoQuery))
        else:
            self.statusbar.showMessage(pathNoQuery)
        self.linkHighlighted = link
    
    def setOverrideCursor(self, cursor=QtCore.Qt.WaitCursor):
        """ Set the override cursor if it is not already set.
        
        :Parameters:
            cursor
                Qt cursor
        """
        if not self.overrideCursorSet:
            self.overrideCursorSet = True
            QtWidgets.QApplication.setOverrideCursor(cursor)
    
    def restoreOverrideCursor(self):
        """ If an override cursor is currently set, restore the previous cursor.
        """
        if self.overrideCursorSet:
            self.overrideCursorSet = False
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
    
    def readUsdCrateFile(self, fileStr):
        """ Read in a USD crate file via usdcat converting a temp file to ASCII.
        
        :Parameters:
            fileStr : `str`
                USD file path
        :Returns:
            ASCII file text
        :Rtype:
            `bool`
        """
        logger.debug("Binary USD file detected. Converting to ASCII representation.")
        self.currTab.fileFormat = FILE_FORMAT_USDC
        self.tabWidget.setTabIcon(self.tabWidget.currentIndex(), self.binaryIcon)
        usdPath = utils.generateTemporaryUsdFile(fileStr, self.app.tmpDir)
        with open(usdPath) as f:
            fileText = f.readlines()
        os.remove(usdPath)
        return fileText
    
    '''
    def readUsdzFile(self, fileStr):
        """ Read in a USD zip (.usdz) file via usdzip, uncompressing to a temp directory.
        
        :Parameters:
            fileStr : `str`
                USD file path
        :Returns:
            ASCII file text
        :Rtype:
            `bool`
        """
        logger.debug("Uncompressing usdz file...")
        self.currTab.fileFormat = FILE_FORMAT_USDZ
        self.tabWidget.setTabIcon(self.tabWidget.currentIndex(), self.zipIcon)
        usdDir = utils.unzip(fileStr, self.app.tmpDir)
        return os.path.join(usdDir, os.path.basename(fileStr))
    '''
    
    @Slot(QtCore.QUrl)
    def setSource(self, link, isNewFile=True, newTab=False, hScrollPos=0, vScrollPos=0):
        """ Create a new tab or update the current one.
        Process a file to add links.
        Send the formatted text to the appropriate tab.
        
        :Parameters:
            link : `QtCore.QUrl`
                File to open.
            isNewFile : `bool`
                Optional bool for if this is a new file or an item from history.
            newTab : `bool`
                Optional bool to open in a new tab no matter what.
            hScrollPos : `int`
                Horizontal scroll bar position.
            vScrollPos : `int`
                Vertical scroll bar position.
        """
        # Check if the current tab is dirty before doing anything.
        # Perform save operations if necessary.
        if not self.dirtySave():
            return True
        
        # Re-cast the QUrl so any query strings are evaluated properly.
        link = QtCore.QUrl(link.toString())
        
        # TODO: When given a relative path here, this expands based on the directory the tool was launched from.
        # Should this instead be relative based on the currently active tab's directory?
        fileInfo = QtCore.QFileInfo(link.path())
        fileStr = fileInfo.absoluteFilePath()
        if not fileStr:
            self.closeTab()
            return self.setSourceFinish()
        
        # Set path to the fully expanded path.
        link.setPath(fileStr)
        fullUrlStr = link.toString()
        logger.debug("Setting source to {}".format(fullUrlStr))
        
        self.setOverrideCursor()
        try:
            # If the filename contains an asterisk, make sure there is at least one valid file.
            multFiles = None
            if '*' in fileStr or "<UDIM>" in fileStr:
                multFiles = glob(fileStr.replace("<UDIM>", "[1-9][0-9][0-9][0-9]"))
                if not multFiles:
                    return self.setSourceFinish(False, "The file(s) could not be found:\n{}".format(fileStr))
            # These next tests would normally fail out if the path had a wildcard.
            else:
                if not fileInfo.exists():
                    return self.setSourceFinish(False, "The file could not be found:\n{}".format(fileStr))
                if fileInfo.isDir():
                    logger.debug("Set source to directory. Opening file dialog to {}".format(fileStr))
                    status = self.setSourceFinish()
                    # Instead of failing with a message that you can't open a directory, open the "Open File" dialog to
                    # this directory instead.
                    self.lastOpenFileDir = fileStr
                    self.openFileDialog()
                    return status
                if not fileInfo.isReadable():
                    return self.setSourceFinish(False, "The file could not be read:\n{}".format(fileStr))
            
            # Get extension (minus beginning .) to determine which program to
            # launch, or if the textBrowser should try to display the file.
            ext = fileInfo.suffix()
            if ext in self.programs and self.programs[ext]:
                if multFiles is not None:
                    # Assumes program takes a space-separated list of files.
                    args = shlex.split(self.programs[ext]) + multFiles
                    self.launchProcess(args)
                else:
                    args = shlex.split(self.programs[ext]) + [fileStr]
                    self.launchProcess(args)
                return self.setSourceFinish()
            
            if multFiles is not None:
                self.setSources(multFiles)
                return self.setSourceFinish()
            
            # Open this in a new tab or not?
            if (newTab or (isNewFile and self.preferences['newTab'])) and not self.currTab.isNewTab:
                self.newTab()
            else:
                # Set to none until we know what we're reading in.
                self.currTab.fileFormat = FILE_FORMAT_NONE
            
            # Set path in tab's title and address bar.
            fileName = fileInfo.fileName()
            idx = self.tabWidget.currentIndex()
            self.tabWidget.setTabText(idx, fileName)
            self.tabWidget.setTabIcon(idx, QtGui.QIcon())
            self.tabWidget.setTabToolTip(idx, "{} - {}".format(fileName, fileStr))
            self.addressBar.setText(fullUrlStr)
            
            # Take care of various history menus.
            self.addItemToMenu(fullUrlStr, self.menuHistory, 25, 3, 2)
            self.addItemToMenu(fullUrlStr, self.menuOpenRecent, RECENT_FILES)
            
            # Stop Loading Tab stops the expensive parsing of the file
            # for links, checking if the links actually exist, etc.
            # Setting it to this bypasses link parsing if the tab is in edit mode.
            self.stopLoadingTab = self.currTab.inEditMode or not self.preferences['parseLinks']
            self.actionStop.setEnabled(True)
            
            # Progress bar.
            loadingProgressBar = QtWidgets.QProgressBar(self.statusbar)
            loadingProgressBar.setMaximumHeight(16)
            loadingProgressBar.setMaximumWidth(200)
            loadingProgressBar.setTextVisible(False)
            loadingProgressLabel = QtWidgets.QLabel("Reading file", self.statusbar)
            self.statusbar.addWidget(loadingProgressBar)
            self.statusbar.addWidget(loadingProgressLabel)
            
            # Read in the file.
            usd = False
            try:
                if self.validateFileSize(fileStr):
                    if utils.queryItemBoolValue(link, "binary") or ext == "usdc":
                        # Treat this file as a binary USD crate file. Don't bother
                        # checking the first line. If this is a valid ASCII USD
                        # file, not binary, and we hit this section accidentally,
                        # it will load slower but won't break anything.
                        usd = True
                        fileText = self.readUsdCrateFile(fileStr)
                    elif ext == "usd":
                        usd = True
                        with open(fileStr) as f:
                            # Read in the first line. If it's a binary USD file,
                            # convert it to a temp ASCII file for viewing/editing.
                            if f.readline().startswith("PXR-USDC"):
                                fileText = self.readUsdCrateFile(fileStr)
                            else:
                                self.currTab.fileFormat = FILE_FORMAT_USDA
                                # Read in the full file.
                                f.seek(0)
                                fileText = f.readlines()
                    elif ext == "usdz":
                        # TODO: Support nested usdz references.
                        usd = True
                        layer = utils.queryItemValue(link, "layer")
                        dest = utils.unzip(fileStr, layer, self.app.tmpDir)
                        self.restoreOverrideCursor()
                        return self.setSource(QtCore.QUrl(dest))
                    else:
                        if ext == "usda":
                            usd = True
                            self.currTab.fileFormat = FILE_FORMAT_USDA
                        with open(fileStr) as f:
                            fileText = f.readlines()
                else:
                    self.statusbar.removeWidget(loadingProgressBar)
                    self.statusbar.removeWidget(loadingProgressLabel)
                    return self.setSourceFinish(False)
            except Exception:
                self.statusbar.removeWidget(loadingProgressBar)
                self.statusbar.removeWidget(loadingProgressLabel)
                return self.setSourceFinish(False, "The file could not be read: {}".format(fileStr), traceback.format_exc())
            
            # Compile text into a single string formatted nicely for HTML.
            length = len(fileText)
            truncated = False
            
            # Optionally show a warning after the file is loaded.
            warning = None
            
            # Preserve any :SDF_FORMAT_ARGS: parameters from the current link.
            sdf_format_args = utils.sdfQuery(link)
            
            # TODO: Figure out a better way to handle streaming text for large files like Crate geometry.
            # Large chunks of text (e.g. 2.2 billion characters) will cause Qt to segfault when creating a QString.
            if length > LINE_LIMIT:
                length = LINE_LIMIT
                truncated = True
                fileText = fileText[:length]
                warning = "Extremely large file! Capping display at {:,d} lines.".format(LINE_LIMIT)
            
            loadingProgressBar.setMaximum(length - 1)
            if self.stopLoadingTab:
                loadingProgressLabel.setText("Parsing text")
                logger.debug("Parsing text.")
            else:
                loadingProgressLabel.setText("Parsing text for links")
                logger.debug("Parsing text for links.")
            finalText = ""
            exists = PathCacheDict()
            
            for i in range(length):
                # Processing events allows us to catch the stop signal.
                QtCore.QCoreApplication.instance().processEvents()
                loadingProgressBar.setValue(i)
                
                # Escape HTML characters for proper display.
                # Do this before we add any actual HTML characters.
                lineOfText = cgi.escape(fileText[i])
                if len(lineOfText) > LINE_CHAR_LIMIT:
                    if usd:
                        match = self.usdArrayRegEx.match(lineOfText)
                        if match:
                            # Try to display just the first and last items in the long array with an ellipsis in the middle.
                            # This drastically improves text browser interactivity and syntax highlighting time.
                            logger.debug("Hiding long array on line {}".format(i))
                            
                            # Try to split to the first true item based on open parentheses.
                            # This is hacky and prone to error if users have hand-edited the files.
                            innerData = match.group(2)
                            if innerData.startswith("(("):
                                split = ")),"
                            elif innerData.startswith("("):
                                split = "),"
                            else:
                                split = ","
                            innerData = innerData.split(split, 1)[0] + split + "<span title='Long array truncated for display performance'> &hellip; </span>" + innerData.rsplit(split, 1)[-1].lstrip()
                            
                            finalText += "{}{}{}\n".format(match.group(1), innerData, match.group(3))
                            continue
                    logger.debug("Skipping link parsing for long line")
                    finalText += lineOfText
                    continue
                
                if self.stopLoadingTab:
                    # If the user has pressed stop, load the rest of the document
                    # without doing the expensive parsing for links.
                    finalText += lineOfText
                    continue
                
                # Find links.
                # These will search for multiple, non-overlapping links on each line.
                offset = 0
                for m in self.re_usd.finditer(lineOfText):
                    # linkPath = `str` displayed file path
                    # fullPath = `str` absolute file path
                    # Example: <a href="fullPath">linkPath</a>
                    linkPath = m.group(1)
                    start = m.start(1)
                    end = m.end(1)
                    
                    try:
                        if os.path.isabs(linkPath):
                            fullPath = os.path.abspath(utils.expandPath(linkPath, fileStr, sdf_format_args))
                        else:
                            # Relative path from the current file to the link.
                            fullPath = os.path.abspath(os.path.join(os.path.dirname(fileStr), utils.expandPath(linkPath, fileStr, sdf_format_args)))
                        
                        # Override any previously set sdf format args.
                        local_sdf_args = sdf_format_args.copy()
                        if m.group(3):
                            for kv in m.group(3).split("&amp;"):
                                k, v = kv.split("=", 1)
                                local_sdf_args[k] = v
                        if local_sdf_args:
                            queryParams = ["sdf=" + "+".join("{}:{}".format(k, v) for k, v in sorted(local_sdf_args.items(), key=lambda x: x[0]))]
                        else:
                            queryParams = []
                        
                        # .usdz file references (e.g. @set.usdz[foo/bar.usd]@)
                        if m.group(2):
                            queryParams.append("layer=" + m.group(2))
                        
                        # Make the HTML link.
                        if exists[fullPath]:
                            _, fullPathExt = os.path.splitext(fullPath)
                            if fullPathExt == ".usdc" or (fullPathExt == ".usd" and utils.isUsdCrate(fullPath)):
                                queryParams.insert(0, "binary=1")
                                htmlLink = '<a class="binary" href="{}?{}">{}</a>'.format(fullPath, "&".join(queryParams), linkPath)
                            else:
                                queryStr = "?" + "&".join(queryParams) if queryParams else ""
                                htmlLink = '<a href="{}{}">{}</a>'.format(fullPath, queryStr, linkPath)
                        elif '*' in linkPath or '&lt;UDIM&gt;' in linkPath or '.#.' in linkPath:
                            # Create an orange link for files with wildcards in the path, designating zero or more files may exist.
                            queryStr = "?" + "&".join(queryParams) if queryParams else ""
                            htmlLink = '<a title="Multiple files may exist" class="mayNotExist" href="{}{}">{}</a>'.format(fullPath, queryStr, linkPath)
                        else:
                            raise ValueError
                    except ValueError:
                        # File doesn't exist or path cannot be resolved.
                        # Color it red, but don't make it an actual link.
                        htmlLink = '<span title="File not found" class="tooltip badLink">{}</span>'.format(linkPath)
                    # Calculate difference in length between new link and original text so that we know where
                    # in the string to start the replacement when we have multiple matches in the same line.
                    lineOfText = lineOfText[:start + offset] + htmlLink + lineOfText[end + offset:]
                    offset += len(htmlLink) - end + start
                finalText += lineOfText
            logger.debug("Done parsing text for links.")
            
            if len(finalText) > CHAR_LIMIT:
                truncated = True
                finalText = finalText[:CHAR_LIMIT]
                warning = "Extremely large file! Capping display at {:,d} characters.".format(CHAR_LIMIT)
            
            # Wrap the final text in a proper HTML document.
            if self.preferences['teletype'] and ext in ["log", "txt"]: # TODO: Add this to config and/or preferences.
                finalText = HTML_BODY.format(self.convertTeletype(finalText))
            else:
                finalText = HTML_BODY.format(finalText)
            
            # Change highlighter based on the file type.
            loadingProgressLabel.setText("Highlighting text")
            self.setHighlighter(ext)
            
            # Set the text.
            logger.debug("Setting HTML")
            self.currTab.textBrowser.setHtml(finalText)
            logger.debug("Setting plain text")
            self.currTab.textEditor.setPlainText("".join(fileText))
            del finalText, fileText
            self.currTab.isNewTab = False
            
            logger.debug("Setting scroll position")
            # Set focus and scroll to given position.
            # For some reason this never seems to work the first time.
            self.currTab.getCurrentTextWidget().setFocus()
            self.currTab.getCurrentTextWidget().horizontalScrollBar().setValue(hScrollPos)
            self.currTab.getCurrentTextWidget().verticalScrollBar().setValue(vScrollPos)
            
            # Scroll to line number.
            if link.hasQuery():
                line = utils.queryItemValue(link, "line")
                if line is not None:
                    try:
                        line = int(line)
                    except ValueError:
                        logger.warning("Invalid line number in query string: {}".format(line))
                    else:
                        self.goToLineNumber(line)
            
            logger.debug("Updating history")
            if isNewFile:
                self.currTab.updateHistory(link, truncated=truncated)
            self.currTab.updateFileStatus(truncated=truncated)
            
            logger.debug("Cleanup")
            # Since we dirty the tab anytime the text is changed,
            # undirty it, as we just loaded this file.
            self.setDirtyTab(False)
            
            # Done!
            self.statusbar.removeWidget(loadingProgressBar)
            self.statusbar.removeWidget(loadingProgressLabel)
            self.statusbar.showMessage("Done", 2000)
        except Exception:
            return self.setSourceFinish(False, "An unexpected error occurred while reading the file: {}".format(fileStr), traceback.format_exc())
        else:
            return self.setSourceFinish(warning=warning)
    
    def setSourceFinish(self, success=True, warning=None, details=None):
        """ Finish updating UI after loading a new source.
        
        :Parameters:
            success : `bool`
                If the file was loaded successfully or not
            warning : `str` | None
                Optional warning message
            details : `str` | None
                Optional details for the warning message
        :Returns:
            Success
        :Rtype:
            `bool`
        """
        # Clear link since we don't want any previous links to carry over.
        self.linkHighlighted = QtCore.QUrl("")
        self.actionStop.setEnabled(False)
        self.updateButtons()
        self.restoreOverrideCursor()
        if warning:
            self.showWarningMessage(warning, details)
        return success
    
    def setSources(self, files):
        """ Open multiple files in new tabs.
        
        :Parameters:
            files : `list`
                List of string-based paths to open
        """
        prevPath = self.currTab.getCurrentPath()
        for path in files:
            self.setSource(utils.expandUrl(path, prevPath), newTab=True)
    
    def validateFileSize(self, path):
        """ If a file's size is above a certain threshold, confirm the user still wants to open the file.
        
        :Parameters:
            path : `str`
                File path
        :Returns:
            If we should open the file or not
        :Rtype:
            `bool`
        """
        size = QtCore.QFileInfo(path).size()
        if size >= 104857600: # 100 MB
            self.restoreOverrideCursor()
            try:
                dlg = QtWidgets.QMessageBox.question(self, "Large File",
                    "This file is {} and may be slow to load. Are you sure you want to continue?\n\n{}".format(utils.humanReadableSize(size), path),
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                return dlg == QtWidgets.QMessageBox.Yes
            finally:
                self.setOverrideCursor()
        return True
    
    def addItemToMenu(self, path, menu, maxLen=None, start=0, end=None):
        """ Add a path to a history menu.
        
        :Parameters:
            path : `str`
                The full path to add to the history menu.
            menu : `QtGui.QMenu`
                Menu to add history item to.
            maxLen : `int`
                Optional maximum number of history items in the menu.
            start : `int`
                Optional number of actions at the start of the menu to ignore.
            end : `int`
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
            logger.error("Invalid start/end values provided for inserting action in menu.\n"\
                          "start: {}, end: {}, menu length: {}".format(start, end, numAllActions))
        elif numActions == 0:
            # There are not any actions yet, so just add or insert it.
            action = RecentFile(path, menu)
            action.openFile.connect(self.setSource)
            if start != 0 and numAllActions > start:
                menu.insertAction(actions[start], action)
            else:
                menu.addAction(action)
        else:
            alreadyInMenu = False
            for action in actions[start:end]:
                if path == action.path:
                    alreadyInMenu = True
                    # Move to the top if there is more than one action and it isn't already at the top.
                    if numActions > 1 and action != actions[start]:
                        menu.removeAction(action)
                        menu.insertAction(actions[start], action)
                    break
            if not alreadyInMenu:
                action = RecentFile(path, menu)
                action.openFile.connect(self.setSource)
                menu.insertAction(actions[start], action)
                if maxLen is not None and numActions == maxLen:
                    menu.removeAction(actions[start + maxLen - 1])
    
    @Slot()
    @Slot(bool)
    def goPressed(self, *args):
        """ Handle loading the current path in the address bar.
        """
        # Check if text has changed.
        text = utils.expandUrl(self.addressBar.text().strip())
        if text != self.currTab.getCurrentUrl():
            self.setSource(text)
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
        self.currTab = self.tabWidget.widget(idx)
        if prevMode != self.currTab.inEditMode:
            self.editModeChanged.emit(self.currTab.inEditMode)
        
        self.updateButtons()
        
        # Highlighting can be very slow on bigger files. Don't worry about
        # updating it if we're closing tabs while quitting the app.
        if not self.quitting:
            self.findHighlightAll()
    
    def updateButtons(self):
        """ Update button states, text fields, and other GUI elements.
        """
        self.addressBar.setText(self.currTab.getCurrentUrl().toString())
        self.breadcrumb.setText(self.currTab.breadcrumb)
        self.updateEditButtons()
        
        if self.currTab.isNewTab:
            self.setWindowTitle(self.app.appDisplayName)
            self.actionBack.setEnabled(False)
            self.actionForward.setEnabled(False)
            self.actionRefresh.setEnabled(False)
            self.actionFileInfo.setEnabled(False)
            self.actionTextEditor.setEnabled(False)
            self.actionOpenWith.setEnabled(False)
        else:
            self.setWindowTitle("{} - {}".format(self.app.appDisplayName, self.tabWidget.tabText(self.tabWidget.currentIndex())))
            self.actionBack.setEnabled(self.currTab.isBackwardAvailable())
            self.actionForward.setEnabled(self.currTab.isForwardAvailable())
            self.actionRefresh.setEnabled(True)
            self.actionFileInfo.setEnabled(True)
            self.actionTextEditor.setEnabled(True)
            self.actionOpenWith.setEnabled(True)
        
        path = self.currTab.getCurrentPath()
        usd = utils.isUsdFile(path)
        self.actionUsdView.setEnabled(usd)
        
        status = self.currTab.getFileStatus()
        self.fileStatusButton.setText(status.text)
        self.fileStatusButton.setIcon(status.icon)
        self.actionEdit.setEnabled(status.writable)
        
        # Emit a signal that buttons are updating due to a file change.
        # Useful for plug-ins that may need to update their actions' enabled state.
        self.updatingButtons.emit()
    
    def updateEditButtons(self):
        """ Toggle edit action and button text.
        """
        if self.currTab.inEditMode:
            self.actionEdit.setVisible(False)
            self.actionBrowse.setVisible(True)
            self.actionSave.setEnabled(True)
            self.actionSaveAs.setEnabled(True)
            self.currTab.textEditor.setUndoRedoEnabled(True)
            self.actionPaste.setEnabled(self.currTab.textEditor.canPaste())
            self.actionUndo.setEnabled(self.currTab.textEditor.document().isUndoAvailable())
            self.actionRedo.setEnabled(self.currTab.textEditor.document().isRedoAvailable())
            self.actionFind.setText("&Find/Replace...")
            self.actionFind.setIcon(QtGui.QIcon.fromTheme("edit-find-replace"))
            self.actionCommentOut.setEnabled(True)
            self.actionUncomment.setEnabled(True)
            self.actionIndent.setEnabled(True)
            self.actionUnindent.setEnabled(True)
        else:
            self.actionEdit.setVisible(True)
            self.actionBrowse.setVisible(False)
            self.actionSave.setEnabled(False)
            # allow to always save as a new file. self.actionSaveAs.setEnabled(False)
            self.actionUndo.setEnabled(False)
            self.actionRedo.setEnabled(False)
            self.actionCut.setEnabled(False)
            self.actionPaste.setEnabled(False)
            self.actionFind.setText("&Find...")
            self.actionFind.setIcon(QtGui.QIcon.fromTheme("edit-find"))
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
    
    def launchProcess(self, args, **kwargs):
        """ Launch a program with the path `str` as an argument.
        
        Any additional keyword arguments are passed to the Popen object.
        
        :Parameters:
            args : `list` | `str`
                A sequence of program arguments with the program as the first arg.
                If also passing in shell=True, this should be a single string.
        :Returns:
            Returns process ID or None
        :Rtype:
            `subprocess.Popen` | None
        """
        with self.overrideCursor():
            try:
                if kwargs.get("shell"):
                    # With shell=True, convert args to a string to call Popen with.
                    logger.debug("Running Popen with shell=True")
                    if isinstance(args, list):
                        args = subprocess.list2cmdline(args)
                    logger.info(args)
                else:
                    # Leave args as a list for Popen, but still log the string command.
                    logger.info(subprocess.list2cmdline(args))
                p = subprocess.Popen(args, **kwargs)
                return p
            except Exception:
                self.restoreOverrideCursor()
                self.showCriticalMessage("Operation failed. {} may not be installed.".format(args[0]), traceback.format_exc())
    
    """
    def diffTwoTabs(self):
        import difflib
        lines1 = self.tabWidget.widget(0).textEditor.toPlainText().split('\n')
        filename1 = self.tabWidget.widget(0).getCurrentPath()
        lines2 = self.tabWidget.widget(1).textEditor.toPlainText().split('\n')
        filename2 = self.tabWidget.widget(1).getCurrentPath()
        differ = difflib.HtmlDiff(tabsize=4)
        html = '<html><head></head><body>' + differ.make_table(lines1, lines2, filename1, filename2, context=True, numlines=6) + '</body></html>'
        self.newTab()
        self.currTab.textBrowser.setHtml(html)
        print(html)
    """
    
    @Slot(bool)
    def viewSource(self, checked=False):
        """ For debugging, view the source HTML of the text browser widget.
        
        :Parameters:
            checked : `bool`
                Just for signal
        """
        html = self.currTab.textBrowser.toHtml()
        self.newTab()
        self.currTab.textBrowser.setPlainText(html)
    
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
            QtWidgets.QMessageBox(QtWidgets.QMessageBox.NoIcon, title or self.windowTitle(), msg, QtWidgets.QMessageBox.Ok, self).exec_()
    
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
    
    @Slot(bool)
    def setDirtyTab(self, dirty=True):
        """ Set the dirty state of the current tab.
        
        :Parameters:
            dirty : `bool`
                If the current tab is dirty.
        """
        self.currTab.isNewTab = False
        self.currTab.textEditor.document().setModified(dirty)
        path = self.currTab.getCurrentPath()
        if not path:
            fileName = "(Untitled)"
            tipSuffix = ""
        else:
            fileName = QtCore.QFileInfo(path).fileName()
            tipSuffix = " - {}".format(path)
            if self.currTab.fileFormat == FILE_FORMAT_USDC:
                tipSuffix += " (binary)"
            elif self.currTab.fileFormat == FILE_FORMAT_USDZ:
                tipSuffix += " (zip)"
        text = "*%s*" % fileName if dirty else fileName
        idx = self.tabWidget.currentIndex()
        self.tabWidget.setTabText(idx, text)
        self.tabWidget.setTabToolTip(idx, "{}{}".format(text, tipSuffix))
        self.setWindowTitle("%s - %s" % (self.app.appDisplayName, text))
        self.actionDiffFile.setEnabled(dirty)
    
    def dirtySave(self):
        """ Present a save dialog for dirty tabs to know if they're safe to close/reload or not.
        
        :Returns:
            False if Cancel selected.
            True if Discard selected.
            True if Save selected (and actually saving).
        :Rtype:
            `bool`
        """
        if self.currTab.isDirty():
            dlg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "Save File",
                "The document has been modified.", QtWidgets.QMessageBox.Save |
                QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel, self)
            dlg.setDefaultButton(QtWidgets.QMessageBox.Save)
            dlg.setInformativeText("Do you want to save your changes?")
            btn = dlg.exec_()
            if btn == QtWidgets.QMessageBox.Cancel:
                return False
            elif btn == QtWidgets.QMessageBox.Save:
                if not self.saveTab():
                    return False
            else: # Discard
                self.setDirtyTab(False)
        return True
    
    @Slot(str)
    def onOpen(self, path):
        """ Open the path in a new tab.
        
        :Parameters:
            path : `str`
                File to open
        """
        self.setSource(QtCore.QUrl(path), newTab=True)
    
    @Slot()
    def onOpenLinkNewWindow(self):
        """ Open the currently highlighted link in a new window.
        """
        window = self.newWindow()
        window.setSource(self.linkHighlighted)
    
    @Slot()
    def onOpenLinkNewTab(self):
        """ Open the currently highlighted link in a new tab.
        """
        self.setSource(self.linkHighlighted, newTab=True)
    
    @Slot()
    def onOpenLinkWith(self):
        """ Show the "Open With..." dialog for the currently highlighted link.
        """
        self.launchProgramOfChoice(self.linkHighlighted.toString(QtCore.QUrl.RemoveQuery))
    
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
        self.currTab.historyIndex = self.currTab.findPath(path)
        self.currTab.updateBreadcrumb()
        self.setSource(self.currTab.getCurrentUrl(), isNewFile=False)
    
    @Slot(str)
    def onBreadcrumbHovered(self, path):
        """ Slot called when the mouse is hovering over a breadcrumb link.
        """
        self.statusbar.showMessage(path, 2000)


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
        
        # Testing a better completer capable of working on absolute and relative file paths.
        '''
        self.completer().highlighted.connect(self.onCompleterActivated)
        self.completer().highlighted.connect(self.onCompleterHighlighted)
    
    def keyPressEvent(self, e):
        """ Override the completer behavior to allow relative file paths.
        
        TODO:
        With or without this method, the completer doesn't always work.
        Most often, changing the selection in the completer isn't updating the text in the address bar, which causes problems when you finally select something.
        Sometimes, it also stops popping up altogether.
        It appears I'm not the only one with this problem: http://www.qtcentre.org/threads/54378-QCompleter-with-QFileSystemModel-not-always-popping-up
        """
        super(AddressBar, self).keyPressEvent(e)
        # Don't change completion when things like Ctrl+<key> are pressed.
        if (self.completer() == self.customCompleter and
            QtWidgets.QApplication.keyboardModifiers() in (QtCore.Qt.ShiftModifier,  QtCore.Qt.NoModifier) and
            e.key() != QtCore.Qt.Key_Escape):
            t = self.text()
            print(t)
            if not t:
                self.customCompleter.setCompletionPrefix("")
                self.customCompleter.popup().hide()
            else:
                info = QtCore.QFileInfo(t)
                if info.isRelative():
                    t = self.window().includeWidget.fileModel.rootPath() + '/' + t
                    #t = self.customCompleter.model().rootPath() + '/' + t
                self.customCompleter.setCompletionPrefix(t)
                #print("{} {} {}".format(self.customCompleter.completionPrefix(), self.customCompleter.currentIndex().data().toString(), self.customCompleter.currentCompletion()))
                self.customCompleter.complete()
    
    # For debugging: When the completer breaks and stops updating the line edit as you select a popup item, these signals stop getting fired.
    @Slot(str)
    def onCompleterActivated(self, path):
        print('onCompleterActivated')
        #if self.text() != path:
        #    print("onCompleterActivated: setting text in address bar to activated completer path")
        #    self.setText(path)
    
    @Slot(str)
    def onCompleterHighlighted(self, path):
        print('onCompleterHighlighted')
        #if self.text() != path:
        #    print("onCompleterHighlighted: setting text in address bar to highlighted completer path")
        #    self.setText(path)
    '''
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


# TODO: Try switching between an absolute and relative completer.
class AddressBarCompleter(QtWidgets.QCompleter):
    """Custom completer for AddressBar.
    """
    def __init__(self, model, parent=None):
        super(AddressBarCompleter, self).__init__(model, parent)
        '''
        self.local_completion_prefix = ""
        self.setModel(model)
    
    def setModel(self, model):
        self.source_model = model
        super(AddressBarCompleter, self).setModel(self.source_model)
    
    def updateModel(self):
        local_completion_prefix = self.local_completion_prefix
        class InnerProxyModel(QtGui.QSortFilterProxyModel):
            def filterAcceptsRow(self, sourceRow, sourceParent):
                index0 = self.sourceModel().index(sourceRow, 0, sourceParent)
                return local_completion_prefix.lower() in self.sourceModel().data(index0).toString().lower()
        proxy_model = InnerProxyModel()
        proxy_model.setSourceModel(self.source_model)
        super(AddressBarCompleter, self).setModel(proxy_model)
    '''
    def pathFromIndex(self, index):
        #if index.isValid():
        #    print('pathFromIndex', index.data().toString())
        result = super(AddressBarCompleter, self).pathFromIndex(index)
        #print('pathFromIndex result: {}'.format(result))
        return result
    
    def splitPath(self, path):
        #print('splitPath {}'.format(path))
        result = super(AddressBarCompleter, self).splitPath(path)
        #print('splitPath result: {}'.format(', '.join(result)))
        return result
        '''
        self.local_completion_prefix = path
        self.updateModel()
        #return ""
        result = super(AddressBarCompleter, self).splitPath(path)
        print('splitPath result: {}'.format(', '.join(result)))
        return result'''


class RecentFile(QtWidgets.QAction):
    """ Action representing an individual file in the Recent Files menu.
    """
    openFile = Signal(QtCore.QUrl)
    
    def __init__(self, path, parent):
        """ Create the action.
        
        :Parameters:
            path : `str`
                Absolute path to open.
            parent : `QtGui.QMenu`
                Menu to add action to.
        """
        super(RecentFile, self).__init__(parent)
        self.path = path
        
        # Don't show any query strings or SDF_FORMAT_ARGS in the menu.
        displayName = path.split("?", 1)[0].split(":SDF_FORMAT_ARGS:", 1)[0]
        # Escape any ampersands so that we don't get underlines for Alt+<key> shortcuts.
        displayName = QtCore.QFileInfo(displayName).fileName().replace("&", "&&")
        self.setText(displayName)
        self.setStatusTip(self.path)
        self.triggered.connect(self.onClick)
    
    @Slot(bool)
    def onClick(self, *args):
        """ Signal to open the selected file in the current tab.
        """
        self.openFile.emit(QtCore.QUrl(self.path))


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
        if not (e.buttons() & QtCore.Qt.LeftButton):
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
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Tab"), self, self.nextTab)
    
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
    
    def nextTab(self):
        """ Switch to the next tab. If on the last tab, go back to the first.
        """
        i = self.currentIndex() + 1
        self.setCurrentIndex(0 if i == self.count() else i)


class TextBrowser(QtWidgets.QTextBrowser):
    """
    Customized QTextBrowser to override mouse events.
    """
    def __init__(self, parent=None):
        """ Create and initialize the text browser.
        
        :Parameters:
            parent : `BrowserTab`
                Browser tab containing this text browser widget
        """
        super(TextBrowser, self).__init__(parent)
    
    def copySelectionToClipboard(self):
        """ Store current selection to the middle mouse selection.
        
        Doing this on selectionChanged signal instead of mouseReleaseEvent causes the following to be output in Qt5:
        "QXcbClipboard: SelectionRequest too old"
        
        For some reason, this isn't needed for QTextEdit but is for QTextBrowser?
        """
        cursor = self.textCursor()
        if cursor.hasSelection():
            selection = cursor.selectedText().replace(u'\u2029', '\n')
            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.setText(selection, clipboard.Selection)
    
    def mouseReleaseEvent(self, event):
        """ Add support for middle mouse button clicking of links.
        
        :Parameters:
            event : `QtGui.QMouseEvent`
                Mouse release event
        """
        window = self.window()
        link = window.linkHighlighted
        if link.toString():
            if event.button() & QtCore.Qt.LeftButton:
                # Only open the link if the user hasn't changed the selection of text while clicking.
                # BUG: Won't let user click any highlighted portion of a link.
                if not self.textCursor().hasSelection():
                    window.setSource(link, newTab=event.modifiers() & QtCore.Qt.ControlModifier)
            elif event.button() & QtCore.Qt.MidButton:
                window.setSource(link, newTab=True)
        self.copySelectionToClipboard()


class TextEdit(QtWidgets.QTextEdit):
    """
    Customized QTextEdit to allow entering spaces with the Tab key.
    """
    def __init__(self, parent=None, tabSpaces=4, useSpaces=True):
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
    
    def keyPressEvent(self, e):
        """ Override the Tab key to insert spaces instead.
        
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
                    # Otherwise, QTextEdit already handles inserting the tab character.
                    self.insertPlainText(" " * self.tabSpaces)
                    return
        elif e.key() == QtCore.Qt.Key_Backtab and e.modifiers() == QtCore.Qt.ShiftModifier and self.textCursor().hasSelection():
            self.unindentText()
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
                for i in range(len(commentStart)):
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
            for i in range(len(commentStart)):
                cursor.movePosition(cursor.NextCharacter, cursor.KeepAnchor)
            # If the selection is all on the same line and matches the comment string, remove it.
            if block.contains(cursor.selectionEnd()) and cursor.selectedText() == commentStart:
                cursor.deleteChar()
            # Remove the end comment string.
            cursor.setPosition(end - len(commentStart))
            block = cursor.block()
            cursor.movePosition(cursor.EndOfBlock)
            for i in range(len(commentEnd)):
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
        while cursor.position() <= end and not cursor.atEnd():
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
        while cursor.position() <= end and not cursor.atEnd():
            currBlock = cursor.blockNumber()
            
            for i in range(self.tabSpaces):
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


class BrowserTab(QtWidgets.QWidget):
    """
    A QWidget that contains custom objects for each tab in the browser.
    This primarily consists of a text browser and text editor.
    """
    changeTab = Signal(QtWidgets.QWidget)
    restoreTab = Signal(QtWidgets.QWidget)
    openFile = Signal(str)
    
    def __init__(self, parent=None):
        """ Create and initialize the tab.
        
        :Parameters:
            parent : `TabWidget`
                Tab widget containing this widget
        """
        super(BrowserTab, self).__init__(parent)
        
        if self.window().app.opts['dark']:
            color = QtGui.QColor(35, 35, 35).name()
        else:
            color = self.style().standardPalette().base().color().darker(105).name()
        self.setStyleSheet("QTextBrowser{{background-color:{}}}".format(color))
        self.inEditMode = False
        self.isActive = True # Track if this tab is open or has been closed.
        self.isNewTab = True
        self.setAcceptDrops(True)
        self.breadcrumb = ""
        self.history = [] # List of FileStatus objects
        self.historyIndex = -1 # First file opened will be 0.
        self.fileFormat = FILE_FORMAT_NONE # Used to differentiate between things like usda and usdc.
        font = parent.font()
        prefs = parent.window().preferences
        
        # Text browser.
        self.textBrowser = TextBrowser(self)
        self.textBrowser.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.textBrowser.setFont(font)
        # Don't let the browser handle links, since we have our own, special handling. # TODO: Should we do a file:// URL handler instead?
        self.textBrowser.setOpenLinks(False)
        self.textBrowser.setVisible(not self.inEditMode)
        
        # Text editor.
        self.textEditor = TextEdit(self)
        self.textEditor.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.textEditor.setAcceptRichText(False)
        self.textEditor.setFont(font)
        self.textEditor.setWordWrapMode(QtGui.QTextOption.NoWrap)
        self.textEditor.setVisible(self.inEditMode)
        self.setTabSpaces(prefs['useSpaces'], prefs['tabSpaces'])
        
        # Line numbers.
        self.lineNumbers = LineNumbers(self, widget=self.getCurrentTextWidget())
        self.lineNumbers.setVisible(prefs['lineNumbers'])
        
        # Menu item to be used in dropdown list of currently open tabs.
        self.action = QtWidgets.QAction("(Untitled)", None)
        self.action.triggered.connect(self.onActionTriggered)
        
        # Add widget to layout and layout to tab
        self.browserLayout = QtWidgets.QHBoxLayout()
        self.browserLayout.setContentsMargins(2,5,5,5)
        self.browserLayout.setSpacing(2)
        self.browserLayout.addWidget(self.lineNumbers)
        self.browserLayout.addWidget(self.textBrowser)
        self.browserLayout.addWidget(self.textEditor)
        self.setLayout(self.browserLayout)
    
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
    
    def findPath(self, path):
        """ Find the index of the given path in the tab's history.
        
        :Parameters:
            path : `str`
                Path to search for in history.
        :Returns:
            Index of the given path in the history, or 0 if not found.
        :Rtype:
            `int`
        """
        for i in range(self.historyIndex + 1):
            if self.history[i].url.toString() == path:
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
            Ex: /studio/filename.usd?line=14
        :Rtype:
            `QtCore.QUrl`
        """
        return self.getFileStatus().url
    
    def getCurrentTextWidget(self):
        """ Get the current text widget (browser or editor).
        
        :Returns:
            The current text widget, based on edit mode
        :Rtype:
            `TextBrowser` | `QtGui.QTextEdit`
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
            # I haven't been able to reproduce this, but it failed once before. Try to get some more logging to debug the problem.
            assert self.historyIndex < len(self.history), "Error: history index = {} but history length is {}. History: {}".format(self.historyIndex, len(self.history), self.history)
            return self.history[self.historyIndex]
        return FileStatus()
    
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
        """ Slot called when a file action is activated
        (e.g. a file from the Recent Files menu).
        """
        if self.isActive:
            self.changeTab.emit(self)
        else:
            self.restoreTab.emit(self)
    
    def setTabSpaces(self, useSpaces=True, tabSpaces=4):
        """ Set the width of a tab character in spaces, both for display and editing.
        
        :Parameters:
            useSpaces : `bool`
                Use spaces instead of a tab character
            spaces : `int`
                Tab size in spaces
        """
        font = self.parent().font()
        width = tabSpaces * QtGui.QFontMetricsF(font).averageCharWidth()
        self.textBrowser.setTabStopWidth(width)
        self.textEditor.setTabStopWidth(width)
        self.textEditor.tabSpaces = tabSpaces
        self.textEditor.useSpaces = useSpaces
    
    def updateHistory(self, url, update=False, truncated=False):
        """ Add a newly created file to the tab's history.
        
        :Parameters:
            url : `QtCore.QUrl`
                Link for file to add to history list.
            update : `bool`
                Update the path's file status cache.
            truncated : `bool`
                If the file was truncated on read, and therefore should never be edited.
        """
        self.historyIndex += 1
        # Cut off any forward history.
        self.history = self.history[:self.historyIndex]
        self.history.append(FileStatus(url, update=update, truncated=truncated))
        self.updateBreadcrumb()
    
    def updateBreadcrumb(self):
        """ Update the breadcrumb of file browsing paths and the action for the
        currently open file, which lets us restore the tab after it is closed.
        """
        # Limit the length of the breadcrumb trail.
        # This is pretty much an arbitrary number.
        maxLen = 100
        
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
            crumbLen += len(path) + 3 # +3 for the space between crumbs.
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
            window.showCriticalMessage("An unexpected error occurred while querying the file status.", traceback.format_exc())


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
    
    # The widget class to build the application's main window.
    uiSource = UsdMngrWindow
    
    # List of all open windows.
    _windows = []
    
    appDisplayName = "USD Manager"
    
    def run(self):
        """ Launch the application.
        """
        self.appPath = sys.argv[0]
        self.appName = os.path.basename(self.appPath)
        self.tmpDir = None
        
        parser = argparse.ArgumentParser(prog=os.path.basename(self.appPath),
            description = 'File Browser/Text Editor for quick navigation and\n'
                'editing among text-based files that reference other files.\n\n')
        parser.add_argument('fileName', nargs='*', help='The file(s) to view.')
        parser.add_argument("-dark",
            action="store_true",
            help="Use usdview-like dark Qt theme"
        )
        parser.add_argument("-info",
            action="store_true",
            help="Log info messages"
        )
        parser.add_argument("-debug",
            action="store_true",
            help="Log debugging messages"
        )
        results = parser.parse_args()
        self.opts = {
            'dir': os.getcwd(),
            'info': results.info,
            'debug': results.debug,
            'dark': results.dark
        }
        
        # Initialize the application and settings.
        self._set_log_level()
        logger.debug("Qt version: {} {}".format(Qt.__binding__, Qt.__binding_version__))
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
            logger.info("Loading app config from {}".format(appConfigPath))
            with open(appConfigPath) as f:
                self.appConfig = json.load(f)
        except Exception as e:
            logger.error("Failed to load app config from {}: {}".format(appConfigPath, e))
            self.appConfig = {}
        
        # Documentation URL.
        self.appURL = self.appConfig.get("appURL", "https://github.com/dreamworksanimation/usdmanager")
        
        # Create a main window.
        window = self.newWindow()
        
        # Open any files passed in by the user.
        if results.fileName:
            window.setSources(results.fileName)
        
        # Start the application loop.
        self.mainLoop()
    
    def _set_log_level(self):
        """ Set the logging level.
        
        Call this after each component in the case of misbehaving libraries.
        """
        logger.setLevel(logging.WARNING)
        if self.opts['info']:
            logger.setLevel(logging.INFO)
        if self.opts['debug']:
            logger.setLevel(logging.DEBUG)
    
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
            `QtGui.QWidget`
        """
        window = self.createWindowFrame()
        self._windows.append(window)
        window.show()
        return window
    
    def mainLoop(self):
        """ Start the application loop.
        """
        if not App._eventLoopStarted:
            # Create a temp directory for cache-like files.
            self.tmpDir = tempfile.mkdtemp(prefix=self.appName)
            logger.debug("Temp directory: {}".format(self.tmpDir))
            App._eventLoopStarted = True
            self.app.exec_()
    
    @Slot()
    def onExit(self):
        """ Callback when the application is exiting.
        """
        App._eventLoopStarted = False
        
        # Clean up our temp dir.
        if self.tmpDir is not None:
            shutil.rmtree(self.tmpDir, ignore_errors=True)


class Settings(QtCore.QSettings):
    """ Add a method to get `bool` values from settings, since bool is stored as the `str` "true" or "false."
    """
    def boolValue(self, key, default=False):
        """ Boolean values are saved to settings as the string "true" or "false".
        Convert a setting back to a bool, since we don't have QVariant objects in Qt.py.

        :Parameters:
            key : `str`
                Settings key
        :Returns:
            True of the value is "true"; otherwise False.
            False if the value is undefined.
        :Rtype:
            `bool`
        """
        val = self.value(key)
        return default if val is None else val == "true"


if __name__ == '__main__':
    App().run()
