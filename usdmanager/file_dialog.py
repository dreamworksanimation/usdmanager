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
from Qt.QtCore import QDir
from Qt.QtWidgets import QFileDialog

from .constants import FILE_FILTER


class FileDialog(QFileDialog):
    """
    Override the QFileDialog to provide hooks for customization.
    """
    def __init__(self, parent=None, caption="", directory="", filters=None, selectedFilter="", showHidden=False):
        """ Initialize the dialog.

        :Parameters:
            parent : `QtCore.QObject`
                Parent object
            caption : `str`
                Dialog title
            directory : `str`
                Starting directory
            filters : `list` | None
                List of `str` file filters. Defaults to constants.FILE_FILTER
            selectedFilter : `str`
                Selected file filter
            showHidden : `bool`
                Show hidden files
        """
        super(FileDialog, self).__init__(parent, caption, directory, ';;'.join(filters or FILE_FILTER))

        # The following line avoids this warning with Qt5:
        # "GtkDialog mapped without a transient parent. This is discouraged."
        self.setOption(QFileDialog.DontUseNativeDialog)

        if selectedFilter:
            self.selectNameFilter(selectedFilter)
        if showHidden:
            self.setFilter(self.filter() | QDir.Hidden)
