# Installing USD Manager

USD Manager has primarily been developed for and tested on Linux. While the basics should work on other platforms, they
have not been as heavily tested. Notes to help with installation on specific operating systems can be added here.

**_These steps provide an example only and may need to be modified based on your specific setup and needs._**

## Contents

- [Prerequisites](#prerequisites)
- [Install with setup.py](#install-with-setup-py)
- [OS Specific Notes](#os-specific-notes)
  * [Linux](#linux)
  * [Mac (OSX)](#mac-osx)
  * [Windows](#windows)
- [Common Problems](#common-problems)

## Prerequisites
- Install Python 2 ([https://www.python.org/downloads/](https://www.python.org/downloads/)), or 3 if on the python3 branch.
  * **Windows:** Ensure the install location is part of your PATH variable (newer installs should have an option for this)
- Install one of the recommended Python Qt bindings
  * **Python 2:** PyQt4 or PySide
  * **Python 3:** PyQt5 or PySide2, example:
    ```
    pip install PySide2
    ```

## Install with setup.py

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

## OS Specific Notes

### Linux

#### Known Issues
- Print server may not recognize network printers.

### Mac (OSX)

#### Installation
1. Launch Terminal
2. ```cd``` to the downloaded usdmanager folder (you should see a setup.py file in here).
3. Customize usdmanager/config.json if needed.
4. Run ```python setup.py install``` (may need to prepend the command with ```sudo``` and/or add the ```--user``` flag)
5. Depending on where you installed it (e.g. /Users/username/Library/Python/3.7/bin), update your $PATH to include the relevant bin directory by editing /etc/paths or ~/.zshrc.

#### Known Issues
- Since this is not installed as an entirely self-contained package, the application name (and icon) will by Python, not USD Manager.

### Windows

#### Installation
1. Launch Command Prompt
2. ```cd``` to the downloaded usdmanager folder (you should see a setup.py file in here).
3. Customize usdmanager/config.json if needed.
4. Run ```python setup.py install``` (may need the ```--user``` flag)

If setup.py complains about missing setuptools, you can install it via pip. If you installed a new enough python version, pip should already be handled for you, but you may still need to add it to your PATH. pip should already live somewhere like this (C:\Python27\Scripts\pip.exe or C:\Users\username\AppData\Local\Microsoft\WindowsApps\pip.exe), but if needed, you can permanently add it to your environment with this (adjusting the path as needed): ```setx PATH "%PATH%;C:\Python27\Scripts"```

1. Upgrade pip if needed
 1. Launch Command Prompt in Administrator mode
 2. Run ```pip install pip --upgrade``` (may need the ```--user``` flag)
2. Install setuptools if needed
 1. Run ```pip install setuptools```
3. Re-run the setup.py step above for usdmanager
4. If you don't modify your path, you should now be able to run something like this to launch the program: ```python C:\Python27\Scripts\usdmanager``` or from the install directory itself, e.g. ``` python .\build\scripts-3.8\usdmanager```

#### Known Issues
- Since this is not installed as an entirely self-contained package, the application name (and icon) will by Python, not USD Manager.

## Common Problems
- Can't open files in external text editor
  * In Preferences, update your default text editor
  * **Windows:** Try ```notepad```, ```notepad.exe```, or ```"C:\Windows\notepad.exe"``` (including the quotation marks on that last one)
