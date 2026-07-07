#
# Copyright 2021 DreamWorks Animation L.L.C.
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
MoonRay's Render Data Layer (RDL) syntax highlighter
"""
from __future__ import absolute_import
from .lua import MasterLuaHighlighter


class MasterRdlHighlighter(MasterLuaHighlighter):
    """ RDL syntax highlighter for MoonRay's Render Data Layer.
    """
    extensions = ["rdla", "rdlb"]

    def setLinkPattern(self, programs, dirty=True):
        """ Set the rules to search for files based on file extensions, quotes, etc.

        :Parameters:
            programs : `dict`
                extension: program pairs of strings.
        """
        self.ruleLink[0].setPattern(r'"/[^"]*"')
        if dirty:
            self.dirty()
