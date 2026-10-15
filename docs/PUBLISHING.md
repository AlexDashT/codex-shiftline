# Publishing this repository

1. Review README.md, LICENSE, NOTICE.md, SECURITY.md and `shiftline.py`.
2. Verify no credentials are staged: `git status`, `git diff --cached`, and `git grep -n -i -E '(access_token|refresh_token|OPENAI_API_KEY|sk-[a-zA-Z0-9])'` (inspect matches; source references may be legitimate).
3. Run: `python3 -m unittest discover -s tests -v`.
4. Confirm GitHub Actions checks succeed and install manually on a disposable Ubuntu account.
5. Verify the interactive picker via `shiftline switch main`, the all-sessions option `shiftline switch main --all`, and the direct-resume option `shiftline switch main --last`.
6. Only after end-to-end verification, create an official release tag:
   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   ```

Do not publish a release as fully tested on real accounts until that is actually verified.
