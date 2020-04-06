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
import logging

from Qt.QtCore import QFileInfo, QUrl
from Qt.QtGui import QIcon


# Set up logging.
logger = logging.getLogger(__name__)
logging.basicConfig()


class FileStatus(object):
    """ File status cache class allowing overriding with additional statuses for custom integration of things like a
    revision control system.
    """
    FILE_NEW          = 0  # New file, never saved.      Ok to edit, save.
    FILE_NOT_WRITABLE = 1  # File not writable.          Nothing allowed.
    FILE_WRITABLE     = 2  # File writable.              Ok to edit, save.
    FILE_TRUNCATED    = 4  # File was truncated on read. Nothing allowed.
    
    def __init__(self, url=None, update=True, truncated=False):
        """ Initialize the FileStatus cache
        
        :Parameters:
            url : `QtCore.QUrl`
                File URL
            update : `bool`
                Immediately update file status or not, like checking if it's writable.
            truncated : `bool`
                If the file was truncated on read, and therefore should never be edited.
        """
        self.url = url if url else QUrl()
        self.path = "" if self.url.isEmpty() else self.url.path()
        self.status = self.FILE_NEW
        self.fileInfo = None
        if update:
            self.updateFileStatus(truncated)
    
    def updateFileStatus(self, truncated=False):
        """ Cache the status of a file.
        
        :Parameters:
            truncated : `bool`
                If the file was truncated on read, and therefore should never be edited.
        """
        if self.path:
            if self.fileInfo is None:
                self.fileInfo = QFileInfo(self.path)
                self.fileInfo.setCaching(False)
            if truncated:
                self.status = self.FILE_TRUNCATED
            elif self.fileInfo.isWritable():
                self.status = self.FILE_WRITABLE
            else:
                self.status = self.FILE_NOT_WRITABLE
        else:
            self.status = self.FILE_NEW
    
    @property
    def icon(self):
        """ Get an icon to display representing the file's status.
        
        :Returns:
            Icon (may be blank)
        :Rtype:
            `QIcon`
        """
        if self.status == self.FILE_NOT_WRITABLE:
            return QIcon(":images/images/lock")
        return QIcon()
    
    @property
    def text(self):
        """ Get a status string to display for the file.
        
        :Returns:
            File status (may be an empty string)
        :Rtype:
            `str`
        """
        if self.status == self.FILE_NEW:
            return ""
        elif self.status == self.FILE_NOT_WRITABLE:
            return "File not writable"
        elif self.status == self.FILE_WRITABLE:
            return "File writable"
        elif self.status == self.FILE_TRUNCATED:
            return "File too large to fully display"
        else:
            logger.error("Unexpected file status code: {}".format(self.status))
            return ""
    
    @property
    def writable(self):
        """ Get if the file is writable.
        
        :Returns:
            If the file is writable
        :Rtype:
            `bool`
        """
        return self.status in [self.FILE_NEW, self.FILE_WRITABLE]
