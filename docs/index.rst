.. USD Manager documentation master file, created by
   sphinx-quickstart on Tue Mar 12 10:59:49 2019.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

USD Manager
===========

.. image:: ./_static/logo_512.png
   :target: ./_static/logo_512.png
   :alt: USD Manager


`Website <http://www.usdmanager.org>`_

USD Manager is an open-source, python-based Qt tool for browsing, managing, and editing text-based files like USD,
combining the best features from your favorite web browser and text editor into one application, with hooks to deeply
integrate with other pipeline tools. It is developed and maintained by `DreamWorks Animation <http://www.dreamworksanimation.com>`_
for use with USD and other hierarchical, text-based workflows, primarily geared towards feature film production. While
primarily designed around PyQt4, USD Manager uses the Qt.py compatibility library to allow working with PyQt4, PyQt5,
PySide, or PySide2 for Qt bindings.

Development Repository
^^^^^^^^^^^^^^^^^^^^^^

This GitHub repository hosts the trunk of the USD Manager development. This implies that it is the newest public
version with the latest features and bug fixes. However, it also means that it has not undergone a lot of testing and
is generally less stable than the `production releases <https://github.com/dreamworksanimation/usdmanager/releases>`_.

License
^^^^^^^

USD Manager is released under the `Apache 2.0`_ license, which is a free, open-source, and detailed software license
developed and maintained by the Apache Software Foundation.

Contents
========

User Documentation

.. toctree::
   :maxdepth: 2

   Installing USD Manager <installation>
   Using USD Manager <usage>
   Keyboard Shortcuts <keyboardShortcuts>
   Development / Customization <development>
   Contributing <contributing>

API Documentation

.. toctree::
   :maxdepth: 3

   api/usdmanager

.. _Apache 2.0: https://www.apache.org/licenses/LICENSE-2.0