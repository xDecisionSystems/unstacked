# Plan: separate public and management sites

## Scope

Create a deployment split only. The current Unstacked username/password login,
sessions, groups, and permissions remain unchanged. This plan does not add
OAuth, SSO, a ChatGPT write API, or an embedded AI feature.

## Outcome

The workspace will be available through two hostnames:

- `public.<domain>` — anonymous, read-only public content.
- `manage.<domain>` — the existing full Unstacked application, including its
  current login process, editor, settings, administration, backups, and API.

```
Internet
  |
  +-- public.<domain> -> Cloudflare Tunnel -> static public-site service
  |
  +-- manage.<domain> -> Cloudflare Tunnel -> existing Unstacked service
```

The management service remains the only writer of the content repository and
database. The public service receives only a completed static build mounted
read-only; it has no database, credentials, Git metadata, edit routes, API,
or access to operational settings.

## Public-content contract

The public static build must include only content explicitly marked public.
It must exclude all private and draft material, including page titles,
navigation entries, card images, other assets, links, and search-index
records. The existing public visibility setting is the sole source of truth;
default visibility remains private.

This must be a new, filtered public build. It cannot reuse the current full
MkDocs export because that export intentionally includes every non-draft page
and therefore remains private.

## Implementation phases

### 1. Public-build service

1. Define a single reusable eligibility check for public books, pages,
   homepage widgets, and assets.
2. Create an isolated staging copy containing only eligible content.
3. Run `mkdocs build --strict` against that staging copy.
4. Atomically publish the successful output, retaining the previous known-good
   public site when a build fails.
5. Use the existing repository lock so a build never reads a half-saved
   workspace.

### 2. Public-site runtime

1. Add a separate static-server container/service.
2. Mount only the generated public artifact read-only.
3. Do not mount `data/`, the source content repository, or any secret files.
4. Configure safe static behavior: no directory listing, no executable
   uploads, appropriate security headers, and cache invalidation after a
   successful publication.

### 3. Management-site boundary

1. Keep the existing FastAPI service and its current local login process
   unchanged.
2. Give management a distinct hostname from public content.
3. Preserve all current CSRF, rate limiting, session, ACL, and admin controls.
4. Ensure the public hostname can never route to editor, login, admin, API,
   import/export, backup, users, or settings endpoints.

### 4. Publication automation

1. Queue a public rebuild after a successful change that affects public
   content, visibility, navigation, homepage content, featured state, branding,
   or a public card image.
2. Coalesce rapid edits in a background worker so content saves do not wait
   for MkDocs.
3. Expose a sanitized last-build status and an administrator-only “build public
   site now” action on the management site.

### 5. Cloudflare Tunnel deployment

1. Create separate public-hostname mappings for `public.<domain>` and
   `manage.<domain>`.
2. Route each hostname only to the matching local service.
3. Keep origin ports closed to the Internet; Tunnel uses outbound connections.
4. Optionally add Cloudflare Access to `manage.<domain>` as an extra gate,
   while retaining Unstacked’s current login as the application login.
5. Configure public-cache purge or revalidation after successful publication.

### 6. Verification and documentation

1. Test that anonymous visitors can see only public home, book, page, search,
   and asset output.
2. Test that private content cannot be inferred through URLs, redirects,
   navigation, static search data, assets, or error responses.
3. Test that a failed public build preserves the previous publication.
4. Test that management remains fully functional with the current login flow.
5. Run ruff, full tests, strict MkDocs builds, and Docker Compose verification
   for both services.
6. Document Cloudflare DNS/Tunnel setup, rollback, cache behavior, and the
   separation between the full private export and the filtered public build.

## Non-goals

- No OAuth or external identity provider.
- No change to current Unstacked usernames, passwords, sessions, or groups.
- No ChatGPT/AI write access.
- No public management API.
- No change to the file-based content model, Git history, or four-table
  database boundary.

## Acceptance criteria

- The public hostname serves only explicitly public, non-draft material.
- The public service cannot write to the workspace or read application secrets.
- The management hostname retains the existing Unstacked login process and all
  management capabilities.
- A failed public publication cannot replace the prior known-good public site.
- Both hostnames can be routed independently through Cloudflare Tunnel.
