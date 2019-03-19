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
from Qt.QtCore import QObject


class Plugin(QObject):
    """ Classes in modules in the plugins directory that inherit from Plugin will be automatically initialized when the
    main window loads.
    """
    def __init__(self, parent, **kwargs):
        """ Initialize the plugin.
        
        :Parameters:
            parent : `UsdMngrWindow`
                Main window
        """
        super(Plugin, self).__init__(parent, **kwargs)
