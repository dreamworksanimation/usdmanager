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
from __future__ import absolute_import, division, print_function

from setuptools import setup, find_packages
from glob import glob


PACKAGE = "usdmanager"
import sys
if sys.version_info[0] < 3:
    execfile("{}/version.py".format(PACKAGE))
else:
    exec(open("{}/version.py".format(PACKAGE)).read())
VERSION = __version__


setup(
    name=PACKAGE,
    version=VERSION,
    description="Tool for browsing, editing, and managing USD and other text files.",
    author="DreamWorks Animation",
    author_email="usdmanager@dreamworks.com",
    maintainer="Mark Sandell, DreamWorks Animation",
    maintainer_email="mark.sandell@dreamworks.com",
    url="https://github.com/dreamworksanimation/usdmanager",
    long_description=open("README.md").read(),
    classifiers=[
        # Get classifiers from:
        # https://pypi.python.org/pypi?%3Aaction=list_classifiers
        "Development Status :: 4 - Beta",
        "Natural Language :: English",
        "Operating System :: POSIX",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "License :: OSI Approved :: Apache Software License",
    ],
    packages=find_packages(),
    # package_data will only find files that are located within python packages
    package_data={
        "usdmanager": [
            "highlighters/*.py",
            "parsers/*.py",
            "plugins/*.py",
            "*.json",
            "*.ui"
        ]
    },
    # data_files will find all other files. It is a list of two member tuples.
    # The first item of the tuple is the desired destination folder
    # The second member of the tuple is a list of source files.
    # Given data_files=[("xml_data", ["xml_examples/xml1.xml"])], xml1.xml will
    # be copied to the "xml_data" folder of the destination package.
    # the xml_examples folder will not be copied or created.
    data_files=[("usdmanager", ["usdmanager/usdviewstyle.qss"])],
    scripts=glob("scripts/*"),
    install_requires=[
        "Qt.py>=1.1",
        "setuptools",  # For pkg_resources
    ],
    setup_requires=[
        "setuptools>=2.2",
    ],
    tests_require=[],
    dependency_links=[],
)
