# Contributing

This document details the contributing requirements and coding practices that are used in the USD Manager codebase.

## Contents

- [The Contributor License Agreement](#the-contributor-license-agreement)
- [Code Signing](#code-signing)
- [Pull Requests](#pull-requests)
- [Process](#process)
- [Style Guide](#style-guide)
  * [Naming Conventions](#naming-conventions)
  * [Formatting](#formatting)
  * [General](#general)

## The Contributor License Agreement

Developers who wish to contribute code to be considered for inclusion in the USD Manager distribution must first
complete the [Contributor License Agreement](http://www.usdmanager.org/USDManagerContributorLicenseAgreement.pdf)
and submit it to DreamWorks (directions in the CLA).

## Code Signing

_Every commit must be signed off_.  That is, every commit log message must include a "`Signed-off-by`" line (generated, for example, with
"`git commit --signoff`"), indicating that the committer wrote the code and has the right to release it under the
[Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0) license. See http://developercertificate.org/ for more
information on this requirement.

## Pull Requests

Pull requests should be rebased on the latest dev commit and squashed to as few logical commits as possible, preferably
one. Each commit should pass tests without requiring further commits.

## Process

1. Fork the repository on GitHub
2. Clone it locally
3. Build a local copy
```
python setup.py install --user
```
4. Write code, following the [style guide](#style-guide).
5. Test it
6. Update any manual documentation pages (like this one) and run sphinx-apidoc with the following command:
```
sphinx-apidoc -o ./docs/api/ -e -P -f ./usdmanager/
```
7. Test that the documentation builds without errors with:
```
sphinx-build -b html docs/ docs/_build
```
6. Commit changes to the dev branch, signing off on them per the "[code signing](#code-signing)" instructions, then
push the changes to your fork on GitHub
7. Make a pull request targeting the dev branch

## Style Guide

In general, Python's [PEP 8 style guide](https://www.python.org/dev/peps/pep-0008) should be followed, with the few exceptions or clarifications noted below.
Contributed code should conform to these guidelines to maintain consistency and maintainability.
If there is a rule that you would like clarified, changed, or added,
please send a note to [usdmanager@dreamworks.com](mailto:usdmanager@dreamworks.com).

### Naming Conventions

In general, follow Qt naming conventions:
* Class names should be CapitalizedWords with an uppercase starting letter.
* Variable, function, and method names should be mixedCase with a lowercase starting letter.
* Global constants should be UPPER_CASE_WITH_UNDERSCORES; otherwise, names_with_underscores should be avoided.

### Formatting

* Indentation is 4 spaces. Do not use tabs.
* Line length generally should not exceed 120 characters, especially for comments, but this is not a strict requirement.
* Use Unix-style carriage returns ("\n") rather than Windows/DOS ones ("\r\n").

### General

* For new files, be sure to use the right license boilerplate per our license policy.
