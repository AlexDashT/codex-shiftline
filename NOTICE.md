# Attribution and upstream relationship

**Codex Shiftline** is a separately maintained, reduced rewrite inspired by the profile-based `run` architecture of [`PavloPopravkin/codex-swap`](https://github.com/PavloPopravkin/codex-swap), originally by **Pavlo Popravkin**.

The upstream project is MIT licensed (Copyright © 2026 Pavlo Popravkin). Its copyright and license notice are retained in [LICENSE](LICENSE) for license-compliance clarity.

Shiftline's additions include isolated daemon runtime directories, writer-lock inspection, an opt-in managed-daemon stop, explicit account handoff commands, and extra CLI flag forwarding. Shiftline intentionally omits upstream's usage dashboard, backend API polling, and automatic limit-based account selection.

This is **not** an official OpenAI product, an upstream release, or a claim of endorsement by the upstream author. For the original project and its history, see the upstream repository.