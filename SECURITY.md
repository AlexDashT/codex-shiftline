# Security policy

Please **do not open a public issue** containing credentials, auth tokens, session transcripts, or sensitive host paths. Use GitHub's private vulnerability reporting feature if enabled for the repository; otherwise contact the maintainer privately before disclosing details. The maintainer should set a private security contact in repository settings.

## Risk boundaries

Shiftline runs under your own Linux user and launches `codex` using existing stored credentials. It does not encrypt `auth.json`, isolate untrusted project code, or provide a supported cross-account session transfer API.

Only use on a trusted machine. Complete running tasks before handing off; accidental daemon shutdown may interrupt work. Never upload any files from `.codex` or `.codex-*` to bug reports without careful redaction.