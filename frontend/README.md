# QueryDoctor AI — web app

Next.js 16 (App Router) + TypeScript + Tailwind CSS 4 + Vitest. See the root [README](../README.md) and [docs/design/](../docs/design/).

```bash
pnpm install
pnpm dev          # http://localhost:3000
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

`typecheck` runs `next typegen` first, because route types such as `LayoutProps` are generated into `.next/types`.
`AGENTS.md` in this folder is maintained by Next.js itself: read `node_modules/next/dist/docs/` before relying on remembered Next.js APIs.
