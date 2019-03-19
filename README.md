![USD Manager](docs/_static/logo_512.png?raw=true "USD Manager")

[Website](http://www.usdmanager.org)

USD Manager is an open-source, python-based Qt tool for browsing, managing, and editing text-based files like USD,
combining the best features from your favorite web browser and text editor into one application, with hooks to deeply
integrate with other pipeline tools. It is developed and maintained by [DreamWorks Animation](http://www.dreamworksanimation.com)
for use with USD and other hierarchical, text-based workflows, primarily geared towards feature film production. While
primarily designed around PyQt4, USD Manager uses the Qt.py compatibility library to allow working with PyQt4, PyQt5,
PySide, or PySide2 for Qt bindings.

### Development Repository

This GitHub repository hosts the trunk of the USD Manager development. This implies that it is the newest public
version with the latest features and bug fixes. However, it also means that it has not undergone a lot of testing and
is generally less stable than the [production releases](https://github.com/dreamworksanimation/usdmanager/releases).

### License

USD Manager is released under the [Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0), which is
a free, open-source, and detailed software license developed and maintained by the Apache Software Foundation.

Contents
========

- [Installing USD Manager](#installing-usd-manager)
  * [Requirements](#requirements)
  * [Install with setup.py](#install-with-setuppy)
- [Using USD Manager](#using-usd-manager)
  * [Keyboard shortcuts](#keyboard-shortcuts)
- [Development / Customization](#development---customization)
- [Contributing](#contributing)

Installing USD Manager
======================

Requirements
------------

usdmanager requires Python 2, [Qt.py](https://github.com/mottosso/Qt.py) (can be handled by setup.py), and one of
Qt.py's 4 supported Qt bindings, which will need to be installed separately.

Install with setup.py
---------------------

For a site-wide install, try:
```
python setup.py install
```

For a personal install, try:
```
python setup.py install --user
```

Studios with significant python codebases or non-trivial installs may need to customize setup.py

Your PATH and PYTHONPATH will need to be set appropriately to launch usdmanager,
and this will depend on your setup.py install settings.

For more OS-specific installation notes, known issues, and common problems, see [Installing USD Manager](docs/installation.md).

Using USD Manager
=================

Once you have installed usdmanager, you can launch from the command line:

```
usdmanager
```

You can also specify one or more files to open directly:

```
usdmanager shot.usd
```

For more documentation on usage, see [Using USD Manager](docs/usage.md)

Keyboard shortcuts
------------------

For a full list of keyboard shortcuts, see [Keyboard Shortcuts](docs/keyboardShortcuts.rst)

Development / Customization
===========================

Most customization of the app is through the [usdmanager/config.json](usdmanager/config.json) file.

For a full list of all customization options, see [Development / Customization](docs/development.md)

Contributing
============

Developers who wish to contribute code to be considered for inclusion in the USD Manager distribution must first
complete the [Contributor License Agreement](http://www.dreamworksanimation.com/usdmanager/USDManagerContributorLicenseAgreement.pdf)
and submit it to DreamWorks (directions in the CLA). We prefer code submissions in the form of pull requests to this
repository.

_Every commit must be signed off_.  That is, every commit log message must include a "`Signed-off-by`" line (generated, for example, with
"`git commit --signoff`"), indicating that the committer wrote the code and has the right to release it under the
[Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0) license. See http://developercertificate.org/ for more
information on this requirement.

1. Fork the repository on GitHub
2. Clone it locally
3. Build a local copy
```
python setup.py install --user
```
4. Write code, following the [style guide](docs/contributing.md).
5. Test it
6. Update any manual documentation pages (like this one) and run sphinx-apidoc with the following command:
```
sphinx-apidoc -o ./docs/api/ -e -P -f ./usdmanager/
```
7. Test that the documentation builds without errors with:
```
sphinx-build -b html docs/ docs/_build
```
8. Commit changes to the dev branch, signing off on them per the code signing instructions, then
push the changes to your fork on GitHub
9. Make a pull request targeting the dev branch

Pull requests should be rebased on the latest dev commit and squashed to as few logical commits as possible, preferably
one. Each commit should pass tests without requiring further commits.