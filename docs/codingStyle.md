Introduction
============
This document details the coding practices that are used in the USD Manager codebase. Contributed code should conform to these guidelines to maintain consistency and maintainability. If there is a rule that you would like clarified, changed, or added, please send a note to [usdmanager@dreamworks.com](mailto:usdmanager@dreamworks.com).

In general, Python's [PEP 8 style guide](https://www.python.org/dev/peps/pep-0008) should be followed, with the few exceptions or clarifications noted below:

Naming Conventions
==================
In general, follow Qt naming conventions:
* Class names should be CapitalizedWords with an uppercase starting letter.
* Variable, function, and method names should be mixedCase with a lowercase starting letter.
* Global constants should be UPPER_CASE_WITH_UNDERSCORES; otherwise, names_with_underscores should be avoided.

Formatting
==========
* Indentation is 4 spaces. Do not use tabs.
* Line length generally should not exceed 120 characters, especially for comments, but this is not a strict requirement.
* Use Unix-style carriage returns ("\n") rather than Windows/DOS ones ("\r\n").

General
=======
* For new files, be sure to use the right license boilerplate per our license policy.
