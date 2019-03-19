# Using USD Manager

Once you have installed usdmanager, you can launch from the command line:

```
usdmanager
```

You can also specify one or more files to open directly:

```
usdmanager shot.usd
```

## Contents

- [Browse Mode](#browse-mode)
  * [Browsing Standard Features](#browsing-standard-features)
- [Edit Mode](#edit-mode)
  * [Editing Standard Features](#editing-standard-features)
- [USD Crate](#usd-crate)
- [Preferences](#preferences)
  * [Tabbed Browsing](#tabbed-browsing)
  * [Font](#font)
  * [Programs](#programs)
- [Commands](#commands)
  * [File Info...](#file-info)
  * [Diff File...](#diff-file)
  * [Comment Out](#comment-out)
  * [Uncomment](#uncomment)
  * [Indent](#indent)
  * [Unindent](#unindent)
  * [Open with usdview...](#open-with-usdview)
  * [Open with text editor...](#open-with-text-editor)
  * [Open with...](#open-with)

## Browse Mode

Browse mode is the standard mode that the application launches in, which displays text-based files like a typical web
browser. Additionally, it attempts to parse the given file for links to other files, such as USD references and
payloads, images, and models, looking for anything inside of 'single quotes,' "double quotes," and @at symbols@.
These links can then be followed like links on a website. Links to files that exist are colored blue, wildcard links
to zero or more files are colored yellow, and paths we think are links that cannot be resolved to a valid path are red.
Binary USD Crate files are highlighted in purple instead of blue.

### Browsing Standard Features
The browser boasts many standard features, including tabbed browsing with rearrangeable tabs, a navigational history
per tab, a recent files list (File > Open Recent), and the ability to restore closed Tabs (History > Recently Closed
Tabs).

## Edit Mode

The program can switch back and forth between browsing (the default) and editing. Before switching to the editor, the
file must be writable. If using files in a revision control system, this is where custom plug-ins can come in handy to
allow you to check in and out files so that you have write permissions before switching to Edit mode.

To switch between Browse mode and Edit mode, hit the Ctrl+E keyboard shortcut, click the Browser/Editor button above
the address bar (to the right of the zoom buttons), or click File -> Browse Mode (or File -> Edit Mode). If you have
modified the file without saving, you will be prompted to save your changes before continuing.

### Editing Standard Features
The editor includes many standard features such as cut/copy/paste support, comment/uncomment macros, and find/replace
functionality.

Files that have been modified are marked as dirty with asterisk around the file name in tabs and the window title.
Before saving a modified file, you can choose to diff your file (Commands -> Diff file...) if you want to see what you
changed. The diffing tool can be modified per user in preferences (Edit > Preferences...) or with the "diffTool" key in
the app config file.

## USD Crate

Binary USD Crate files are supported within the app. You can view and edit them just like using usdedit, but under the
hood, the app is converting back and forth between binary and ASCII formats as needed. Any edits to the file are saved
in the original file format, so opening a binary .usd or .usdc file will save back out in binary. You can force a file
to ASCII by saving with the .usda extension. Similarly, you can force a formerly ASCII-based file to the binary Crate
format by saving with the .usdc extension. Currently, there is no UI to switch between ASCII and binary other than
setting the file extension in the Save As dialog.

## Preferences

Most user preferences can be accessed under the Edit > Preferences... menu option. Preferences in this dialog are saved
for future sessions.

### Tabbed Browsing
Like many web browsers, files can be viewed in multiple tabs. The "+" button on the upper-left of the browser portion
adds a new tab, and the "x" closes the current tab. You can choose to always open files in new tabs under
Edit > Preferences... On the General tab, select "Open files in new tabs."

Alternatively, you can open a file in the current tab by left-clicking the link, and open a file in a new tab by
Ctrl+left-clicking or middle-mouse-clicking the link. There is also a right-click menu item to open the link in a new
tab. To navigate among tabs, you can simply click on the desired tab, or use "Ctrl+Tab" to move forward and
"Ctrl+Shift+Tab" to move backwards.

### Font
Font sizes can be adjusted with the "Zoom In," "Zoom Out," and "Normal Size" options under the "View" menu, or with the
keyboard shortcuts: Ctrl++, Ctrl+-, and Ctrl+0. This size will be applied to all future tabs and is saved as a
preference for your next session. You can also choose a default font for the displayed document in the Preferences
dialog.

### Programs
The extensions that usdmanager searches for when creating links to files can be adjusted under the Programs tab of the
Preferences dialog. If an extension is not on this page, usdmanager will not know to look for it. Any file type that
you wish to display in-app should be listed on the first line in a comma-separated list. File types that you wish to
open in external programs such as an image viewer can be designated in the lower section. If you always want .jpg files
to open in a fullscreen version of eog, for example, set "eog --fullscreen" for the program and ".jpg" for the
extension.

## Commands

Commands may be accessed through the "Commands" menu or by right-clicking inside the browser portion of the program.

_Additional commands beyond the basics provided here can be added via the app config file and
plug-in system. For details, see "Menu plug-ins" in the "Development / Customization" section._

### File Info...
View information about the current file, including the owner, size, permissions, and last modified time.

### Diff File...
If you have made changes to the file without saving, you can use this command to compare the changes to the version
currently saved on disk. The program saves a temporary version of your changes and launches the original and temp files
via the diff tool of your choice (default: xdiff), which can be managed via the Preferences dialog and the app config
file.

### Comment Out
Comment out the selected lines with the appropriate symbol for the current file type. Supports USD, Lua, Python, HTML,
and XML comments, defaulting to # for the comment string if the language is unknown.

### Uncomment
Uncomment the selected lines. See "Comment Out" above for supported languages.

### Indent
Indent the selected lines by one tab stop (4 spaces).

### Unindent
Unindent the selected lines by one tab stop (4 spaces).

### Open with usdview...
For USD files, launch the current file in usdview.

### Open with text editor...
The command launches the current file in a text editor of your choice. By default, usdmanager uses $EDITOR, and nedit
if that environment variable is not defined. You can set your preferred editor using the Preferences dialog under
Edit > Preferences.... This preference will be saved for future sessions.

### Open with...
If usdmanager does not open a file with the program you desire, you can use "Open with..." to enter a program (and any
extra flags) of your choosing. The file is appended at the end of what you enter. To open a link in this manner,
right-click the link and select "Open link with..." from the context menu.
