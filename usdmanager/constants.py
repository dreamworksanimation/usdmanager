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
Constant values
"""
# USD file extensions.
USD_EXTS = ("usd", "usda", "usdc", "usdz")

# File filters for the File > Open... and File > Save As... dialogs.
FILE_FILTER = (
    "USD Files (*.{})".format(" *.".join(USD_EXTS)),
    "USD - ASCII (*.usd *.usda)",
    "USD - Crate (*.usd *.usdc)",
    "USD - Zip (*.usdz)",
    "All Files (*)"
)

# Format of the currently active file. Also, the index in the file filter list for that type.
# Used for things such as differentiating between file types when using the generic .usd extension.
FILE_FORMAT_USD  = 0  # Generic USD file (usda or usdc)
FILE_FORMAT_USDA = 1  # ASCII USD file
FILE_FORMAT_USDC = 2  # Binary USD crate file
FILE_FORMAT_USDZ = 3  # Zip-compressed USD package
FILE_FORMAT_NONE = 4  # Generic text file

# Default template for display files with links.
# When dark theme is enabled, this is overridden in __init__.py.
HTML_BODY = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" "http://www.w3.org/TR/REC-html40/strict.dtd">
<html><head><style type="text/css">
a.mayNotExist {{color:#C90}}
a.binary {{color:#69F}}
.badLink {{color:red}}
</style></head><body style="white-space:pre">{}</body></html>"""

# Set a length limit on parsing for links and syntax highlighting on long lines. 999 chosen semi-arbitrarily to speed
# up things like crate files with really long timeSamples lines that otherwise lock up the UI.
# TODO: Potentially truncate the display of long lines, too, since it can slow down interactivity of the Qt UI. Maybe make it a [...] link to display the full line again?
LINE_CHAR_LIMIT = 999

# Truncate loading files with more lines than this.
# Display can slow down and/or become unusable with too many lines.
# This number is less important than the total number of characters and can be overridden in Preferences.
LINE_LIMIT = 50000

# Truncate loading files with more total chars than this.
# QString crashes at ~2.1 billion chars, but display slows down way before that.
CHAR_LIMIT = 100000000

# Number of recent files and tabs to remember.
RECENT_FILES = 20
RECENT_TABS = 10

# Shell character escape codes that can be converted for HTML display.
TTY2HTML = (
    ('[0m', '</span>'),
    ('\x1b[40m', '<span style="background-color:black">'),
    ('\x1b[44m', '<span style="background-color:blue">'),
    ('\x1b[46m', '<span style="background-color:cyan">'),
    ('\x1b[42m', '<span style="background-color:green">'),
    ('\x1b[45m', '<span style="background-color:magenta">'),
    ('\x1b[41m', '<span style="background-color:red">'),
    ('\x1b[47m', '<span style="background-color:white">'),
    ('\x1b[43m', '<span style="background-color:yellow">'),
    ('\x1b[30m', '<span style="font-family:monospace; color:black">'),
    ('\x1b[34m', '<span style="font-family:monospace; color:#0303ab">'),
    ('\x1b[36m', '<span style="font-family:monospace; color:cyan">'),
    ('\x1b[32m', '<span style="font-family:monospace; color:#38bc38">'),
    ('\x1b[35m', '<span style="font-family:monospace; color:magenta">'),
    ('\x1b[31m', '<span style="font-family:monospace; color:#aa0000">'),
    ('\x1b[37m', '<span style="font-family:monospace; color:gray">'),
    ('\x1b[33m', '<span style="font-family:monospace; color:#bd7d3e">'),
    ('\x1b[7m', '<span style="color:white; background-color:black">'),
    ('\x1b[0m', '<span style="color:#38bc38">'),
    ('\x1b[4m', '<span style="color:#38bc38; text-decoration:underline">'),
    ('\x1b[1m', '<span style="font-weight:bold">')
)
