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
from Qt import QtCore, QtGui

from ..highlighter import createMultilineRule, MasterHighlighter
from ..constants import USD_EXTS


class MasterUSDHighlighter(MasterHighlighter):
    """ USD syntax highlighter
    """
    extensions = USD_EXTS
    comment = "#"
    multilineComment = ('/*', '*/')
    
    def getRules(self):
        return [
            [   # Symbols and booleans
                # \u2026 is the horizontal ellipsis we insert in the middle of long arrays.
                "(?:[>(){}[\]=@" + u"\u2026" + "]|</|true|false)",
                QtCore.Qt.darkMagenta, # Light theme
                QtGui.QColor("#CCC"), # Dark theme
                QtGui.QFont.Bold
            ],
            [   # Keyword actions/descriptors
                # add append prepend del delete custom uniform rel
                r"\b(?:a(?:dd|ppend)|prepend|del(?:ete)?|custom|uniform|varying|rel)\b",
                QtGui.QColor("#4b7029"),
                QtGui.QColor("#4b7029"),
                QtGui.QFont.Bold
            ],
            [   # Keywords
                # references payload defaultPrim doc subLayers specializes active assetInfo hidden kind inherits
                # instanceable customData variant variants variantSets config connect default dictionary displayUnit
                # nameChildren None offset permission prefixSubstitutions properties relocates reorder rootPrims scale
                # suffixSubstitutions symmetryArguments symmetryFunction timeSamples
                r"\b(?:references|payload|d(?:efaultPrim|oc)|s(?:ubLayers|pecializes)|a(?:ctive|ssetInfo)|hidden|kind|"
                r"in(?:herits|stanceable)|customData|variant(?:s|Sets)?|config|connect|default|dictionary|displayUnit|"
                r"nameChildren|None|offset|permission|prefixSubstitutions|properties|relocates|reorder|rootPrims|scale"
                r"|suffixSubstitutions|symmetryArguments|symmetryFunction|timeSamples)\b",
                QtGui.QColor("#649636"),
                QtGui.QColor("#649636"),
                QtGui.QFont.Bold
            ],
            [   # Datatypes (https://graphics.pixar.com/usd/docs/api/_usd__page__datatypes.html)
                # bool uchar int uint int64 uint64 int2 int3 int4 half half2 half3 half4 float float2 float3 float4
                # double double2 double3 double4 string token asset matrix matrix2d matrix3d matrix4d quatd quatf quath
                # color3d color3f color3h color4d color4f color4h normal3d normal3f normal3h point3d point3f point3h
                # vector3d vector3f vector3h frame4d texCoord2d texCoord2f texCoord2h texCoord3d texCoord3f texCoord3h
                r"\b(?:bool|uchar|u?int(?:64)?|int[234]|half[234]?|float[234]?|double[234]?|string|token|asset|"
                r"matrix[234]d|quat[dfh]|color[34][dfh]|normal3[dfh]|point3[dfh]|vector3[dfh]|frame4d|"
                r"texCoord[23][dfh])\b",
                QtGui.QColor("#678CB1"),
                QtGui.QColor("#678CB1"),
                QtGui.QFont.Bold,
                False,
                QtCore.Qt.CaseInsensitive
            ],
            [   # Schemas
                # TODO: Can this query USD to see what schemas are defined?
                # Xform Scope Shader Sphere Subdiv Camera Cube Curve Mesh Material PointInstancer Plane
                r"\b(?:Xform|S(?:cope|hader|phere|ubdiv)|C(?:amera|ube|urve)|M(?:esh|aterial)|"
                r"P(?:ointInstancer|lane))\b",
                QtGui.QColor("#997500"),
                QtGui.QColor("#997500"),
                QtGui.QFont.Bold
            ],
            [   # Specifiers
                # def over class variantSet
                r"\b(?:def|over|class|variantSet)\b",
                QtGui.QColor("#8080FF"),
                QtGui.QColor("#8080FF"),
                QtGui.QFont.Bold
            ],
            self.ruleNumber,
            self.ruleDoubleQuote,
            self.ruleSingleQuote,
            self.ruleLink,
            self.ruleComment
        ]
    
    def createRules(self):
        super(MasterUSDHighlighter, self).createRules()
        
        # Support triple quote strings. Doesn't deal with escaped quotes.
        self.multilineRules.append(createMultilineRule('"""', '"""', QtCore.Qt.darkGreen, QtGui.QColor(25, 255, 25)))
