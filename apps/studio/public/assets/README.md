# Studio asset sources

All assets are served locally. No runtime third-party image calls are made.

- `tasks/*.svg`: official Phosphor duotone assets, MIT. Source: https://github.com/phosphor-icons/core/tree/main/assets/duotone. License: `PHOSPHOR-LICENSE.txt`.
- `integrations/python.svg`, `opentelemetry.svg`, `sqlite.svg`: official Simple Icons vectors, CC0. Source: https://github.com/simple-icons/simple-icons/tree/develop/icons. License: `SIMPLE-ICONS-LICENSE.txt`. Marks identify actual technologies used by this project; their owners retain their trademarks.
- Graph layout uses unmodified `elkjs` 0.12.1 under EPL-2.0, one of its offered licenses. Source: https://github.com/kieler/elkjs. License: `ELK-LICENSE.md`. npm pins the released source package in the Studio lockfile. Graph node and edge drawing uses React Flow.

Phosphor assets identify task categories for scanning only; their appearance does not imply a task's control, approval or payment authority.
