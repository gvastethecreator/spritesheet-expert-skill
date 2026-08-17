# Quality audit — 2026-08-15

| Gate | Result |
| --- | --- |
| pnpm lock/install | PASS — root validator graph |
| Python dependency pins | PASS — latest registry versions recorded |
| Bun classification | PASS — no operational Bun |
| Doctor/test/validation/smoke | PASS — 651 tests, routing/skill validators, and smoke pipeline |
| CI portability | PASS — dedicated pnpm setup on Ubuntu 24.04 and Windows 2025 |
| Public language | PASS — README and Pages are English |
| README evidence | PASS — four real review sheets in a 2 × 2 tour |
| GitHub Pages | PASS — static, responsive, accessible source and pinned deployment workflow |
| `.gitignore`/scratch | PASS — caches, generated outputs, and coverage ignored |
| Browser QA | PASS — Pages and Motion Reference Workbench at desktop/mobile widths; no overflow, broken media, console errors, or Spanish UI strings |
| GitHub metadata | PASS — English description, homepage, topics, sponsor link, and workflow-based Pages configuration |
| Code map | PARTIAL — 4 nodes, 5 edges, 5 flows, no unknown edges; shared browser verifier passes every check except `cardMotion` and dependent `reducedMotion` because its hover probe returns no card |
| Diff hygiene | PASS |

Optional Lucida, rembg/BiRefNet, and video lanes remain capability-scoped; the core package does not
silently install or claim their runtime evidence.
