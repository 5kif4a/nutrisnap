---
name: commit-push
description: Generate a conventional commit message from current changes and push to remote. Use when the user says "commit", "commit and push", "запушь", "закоммить", "сохрани изменения", or any variation that implies committing local changes.
---

# Commit & Push

You generate a high-quality commit message from the current working tree changes and push to the remote `main` branch.

## Workflow

1. **Inspect the working tree** in parallel (single message, multiple Bash calls):
   - `git status` — what's changed (NEVER use `-uall`)
   - `git diff HEAD` — staged + unstaged diff
   - `git log --oneline -10` — recent commit style to match
   - `git branch --show-current` — confirm we're on main (or warn)

2. **Categorize the change.** Pick exactly ONE conventional type:
   - `feat:` — new user-facing feature or capability
   - `fix:` — bug fix
   - `refactor:` — restructuring without behavior change
   - `docs:` — documentation only
   - `chore:` — tooling, deps, configs
   - `test:` — adding/updating tests
   - `ci:` — workflows, deploy configs
   - `perf:` — performance improvement

3. **Write the message.** Format:
   ```
   <type>: <imperative summary, ≤72 chars, lowercase, no period>

   <optional body — only if non-obvious WHY, wrapped at 72 chars>
   ```
   - Imperative mood ("add X" not "added X")
   - Focus on **why**, not what (the diff shows what)
   - No trailing period in subject
   - Skip the body for trivial changes

4. **Safety checks before staging:**
   - **Scan for secrets in the diff**: `OPENAI_API_KEY=`, `BOT_TOKEN=`, `sk-`, JWT-like strings, `*.env` (not `.env.example`), `credentials*`, `*.pem`. If anything looks like a real secret — STOP and warn the user explicitly. Never commit `.env`, `.env.local`, files in `.gitignore`.
   - **Confirm branch**: if not on `main`, mention it but proceed.
   - **No `git add .`** — stage modified/added files explicitly by listing them from `git status`. This avoids accidentally including stray files.

5. **Commit:**
   ```bash
   git add <explicit files>
   git commit -m "$(cat <<'EOF'
   <type>: <summary>

   <optional body>
   EOF
   )"
   ```
   Use HEREDOC for proper formatting. **Do NOT add Co-Authored-By trailer.**

6. **Push** to remote main:
   ```bash
   git push origin main
   ```
   Never `--force` to main. If the push is rejected (non-fast-forward), stop and tell the user — don't try to resolve automatically.

7. **Report** the result concisely:
   ```
   ✅ Committed <abbrev-sha>: <subject>
   ✅ Pushed to origin/main
   ```

## Examples of good messages

- `feat: add quick add from recent and frequent foods`
- `fix: handle empty initData in dev mode`
- `refactor: split nutrition lookup into per-source services`
- `docs: clarify FOR UPDATE usage in concurrency guide`
- `ci: run evals only on backend changes`
- `chore: bump python-telegram-bot to 22.7`

## Bad examples (avoid)

- ❌ `update files` — non-informative
- ❌ `WIP` — leave for personal branches, never main
- ❌ `feat: added quick add feature for recent foods.` — past tense, trailing period, redundant "feature"
- ❌ Including hook footers from previous commits (Co-Authored-By, 🤖 banners)

## When NOT to commit

Refuse to commit and tell the user if:
- Working tree is clean (nothing to commit)
- The diff includes obvious secrets
- There are merge conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) in tracked files
- Tests/lint were modified to disable failing checks (suggests broken code being hidden)

## Do not do

- ❌ Don't `git push --force` or `--force-with-lease` to main
- ❌ Don't `git commit --amend` (always new commit unless user asks)
- ❌ Don't `git commit --no-verify` (don't skip hooks)
- ❌ Don't run `git config` changes
- ❌ Don't add Claude/Anthropic footer to commits
