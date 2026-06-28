# web/ — Next.js triage dashboard

Placeholder skeleton. The full Next.js (App Router) + TypeScript + Tailwind app is
scaffolded in a later phase (after the Phase 1 data verification is confirmed).

Planned structure (per CLAUDE.md):

```
web/
├── app/page.tsx              # triage dashboard
├── app/components/           # KpiCards, TriageTable, DecisionBadge, RiskBadge, FilterTabs, PatientModal
└── lib/supabase.ts           # @supabase/supabase-js read client
```

Reads Supabase via `@supabase/supabase-js`. Deployed on Vercel. Read-only.
