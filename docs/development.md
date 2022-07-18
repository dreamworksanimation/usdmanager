# Development / Customization

Most customization of the app is through the [usdmanager/config.json](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/config.json) file.

## Contents

- [File extensions](#file-extensions)
- [Syntax highlighting](#syntax-highlighting)
- [Plug-ins](#plug-ins)
- [Icons](#icons)

## File extensions

This app supports more than just USD files! It's well suited to display most text-based files, but you need to register
additional file extensions to search for. Non-text files can also be launched via the program of your choice. For
example, .exr files can be launched in your preferred image viewer, and .abc model files in a modeling playback tool
like usdview. To register files, define a "defaultPrograms" dictionary in the app config file.
The dictionary keys are file extensions (without the starting period). The value is either a blank string, which means
files of this type will be opened in this app, or a string to a command to run with the file path appended. USD file
types are already included, so you don't need to redefine these.

Additional default app settings can be optionally overridden via the [app config file](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/config.json).
Supported keys include:
- **appURL _(str)_** - Documentation URL. Defaults to the public GitHub repository.
- **defaultPrograms _({str: str})_** - File extension keys with the command to open the file type as the values.
- **diffTool _(str)_** - Diff command. Defaults to xdiff.
- **iconTheme _(str)_** - QtGui.QIcon theme name. Defaults to crystal_project.
- **textEditor _(str)_** - Text editor to use when opening files externally if $EDITOR environment variable is
not set. Defaults to nedit.
- **themeSearchPaths _([str])_** - Paths to prepend to QtGui.QIcon's theme search paths.
- **usdview** - Command to launch usdview.

Example app config JSON file:
```
{
    "defaultPrograms": {
        "txt": "",
        "log": "",
        "exr": "r_view",
        "tif": "r_view",
        "tiff": "r_view",
        "abc": "usdview",
        "tx": "rez-run openimageio_arras -- iv"
    },
    "diffTool": "python /usr/bin/meld",
    "iconTheme": "gnome",
    "textEditor": "gedit",
    "themeSearchPaths": []
}
```

## Language-specific parsing

When default path parsing logic is not good enough, you can add unique parsing for file types by subclassing the
[parser.AbstractExtParser](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/parser.py).
Save your new class in a file in the parsers directory. Set the class's extensions tuple (e.g. (".html", ".xml")) for a
simple list of file extensions to match, or override the acceptsFile method for more advanced control.

Within each parser, you can define custom menu items that will be added to the bottom of the Commands menu whenever a
parser is active. For example, the [USD parser](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/parsers/usd.py)
adds an "Open in usdview..." action.

## Syntax highlighting

To add syntax highlighting for additional languages, subclass the
[highlighter.MasterHighlighter](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/highlighter.py) class and save your new class in a file in the highlighters
directory. Set the class's extensions list variable to the languages this highlighter supports (e.g.
[".html", ".xml"]). Already supported languages include [USD](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/highlighters/usd.py),
[Lua](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/highlighters/lua.py), [Python](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/highlighters/python.py), and some basic
[HTML/XML](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/highlighters/xml.py).

## Plug-ins

Plug-ins can be added via the plugins directory. Create a new module in the [plugins](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/plugins) directory
(e.g. my_plugin.py) and define a class that inherits from the Plugin class. This allows you to add your own menu items,
customize the UI, etc.

Please be careful if you access, override or define anything in the main window, as future release may break the
functionality you added!

Example plug-in file:
```
from Qt.QtCore import Slot
from Qt.QtGui import QIcon
from Qt.QtWidgets import QMenu

from . import Plugin, images_rc


class CustomExample(Plugin):
    def __init__(self, parent):
        """ Initialize my custom plugin.
        
        :Parameters:
            parent : `UsdMngrWindow`
                Main window
        """
        super(CustomExample, self).__init__(parent)
        
        # Setup UI.
        menu = QMenu("My Menu", parent)
        parent.menubar.insertMenu(parent.helpMenu.menuAction(), menu)
        
        self.customAction = menu.addAction(QIcon(":plugins/custom_icon.png"), "Do something")
        self.customAction.triggered.connect(self.doSomething)
    
    @Slot(bool)
    def doSomething(self, checked=False):
        """ Do something.
        
        :Parameters:
            checked : `bool`
                For slot connection only.
        """
        print("Doing something")
```

## Icons

Most icons in the app come from themes pre-installed on your system, ideally following the
[freedesktop.org standards](https://standards.freedesktop.org/icon-naming-spec/icon-naming-spec-latest.html).
The preferred icon set that usdmanager was originally developed with is Crystal Project Icons. These icons are licensed
under LGPL and available via pypi and GitHub here: https://github.com/ambv/django-crystal-small. While not required for
the application to work, if you would like these icons to get the most out of the application, please install them to a
directory named crystal_project under one of the directories listed by `Qt.QtGui.QIcon.themeSearchPaths()` (e.g.
/usr/share/icons/crystal_project).

Additional icons for custom plug-ins can be placed in the plugins directory and then added to the
[usdmanager/plugins/images.qrc](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/plugins/images.qrc) file. After adding a file to images.rc, run the
following to update [usdmanager/plugins/images_rc.py](https://github.com/dreamworksanimation/usdmanager/blob/master/usdmanager/plugins/images_rc.py):

```
pyrcc4 usdmanager/plugins/images.rc > usdmanager/plugins/images_rc.py
```

If using pyrcc4, be sure to replace PyQt4 with Qt in the images_rc.py's import line.
