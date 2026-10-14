# Contributing

Thank you for contributing to Codex Shiftline.

1. Open an issue or discuss a proposed functional change before larger refactors.
2. Keep the tool Python standard-library-only and Linux compatible (Python 3.9+).
3. Add tests for profile isolation, writer-lock behavior, and unsafe concurrency cases.
4. Run `python3 -m unittest discover -s tests -v` and `python3 -m py_compile shiftline.py`.
5. Never include real credentials or session history in tests or example output.
6. Preserve the upstream attribution and MIT license notice.

No live account-login test is run automatically in CI.