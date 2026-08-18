# GitHub Actions Setup — Political Tracker Agent

This repo runs the agent daily via `.github/workflows/agent-daily.yml`
(`0 14 * * *` UTC = 9 AM EST / 10 AM EDT), plus manual runs via
`workflow_dispatch`. Before it can run successfully, four repository
secrets must be configured.

**Never commit secret values into this repo.** Add them only through the
GitHub Secrets UI below — that's what keeps them out of git history and
encrypted at rest.

## Step 1 — Open the secrets page

Go to:
https://github.com/torrink/political-market-tracker/settings/secrets/actions

## Step 2 — Click "New repository secret"

## Step 3 — Add these 4 secrets (exact names, case-sensitive)

| Secret name        | Value                                                    |
|---------------------|-----------------------------------------------------------|
| `SUPABASE_URL`       | Your Supabase project URL (Supabase dashboard → Project Settings → API → Project URL) |
| `SUPABASE_KEY`       | Your Supabase anon/service key (Supabase dashboard → Project Settings → API → Project API keys) |
| `CONGRESS_API_KEY`   | Your Congress.gov API key (from your api.congress.gov registration) |
| `NTFY_TOPIC`         | Your ntfy.sh topic name (pick any hard-to-guess string - anyone who knows it can read your alerts, since ntfy topics aren't private by default) |

Paste each value directly into the "Secret" field in the GitHub UI — do not
paste them into any file, commit, PR description, or issue.

## Step 4 — Test with a manual run

1. Go to the **Actions** tab:
   https://github.com/torrink/political-market-tracker/actions
2. In the left sidebar, click **Political Tracker Agent (Daily)**.
3. Click the **Run workflow** dropdown (top right of the runs list), then
   the green **Run workflow** button.
4. Click into the new run to watch logs live. Check the **Run agent** step
   for errors, and **Log success** / **Log failure** for the final status.

## Troubleshooting

- **"Run workflow" button not visible**: the workflow file must exist on
  the default branch (`main`) first — push it, then refresh the Actions tab.
- **Secret not found / empty env var**: secret names are case-sensitive and
  must match exactly `SUPABASE_URL`, `SUPABASE_KEY`, `CONGRESS_API_KEY`,
  `NTFY_TOPIC`.
- **Rotating a leaked key**: if a key was ever pasted into a file, commit,
  chat log, or issue, treat it as compromised — rotate it in Supabase /
  Congress.gov and update the GitHub secret with the new value.
