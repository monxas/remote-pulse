<script lang="ts">
  import { Copy, KeyRound, Loader2, Plus, ShieldCheck, Trash2 } from '@lucide/svelte';
  import { Badge } from '$lib/components/ui/badge';
  import { Button } from '$lib/components/ui/button';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Input } from '$lib/components/ui/input';
  import {
    createSettingsGroupsQuery,
    createEnrollLinksQuery,
    createCreateEnrollLinkMutation,
    createRevokeEnrollLinkMutation,
  } from '$lib/queries';
  import type { EnrollLinkOut, EnrollLinkSummary, SettingsGroup } from '$lib/api';

  // Reuse the groups query so the dropdown stays in sync with /settings.
  const groupsQuery = createSettingsGroupsQuery();
  const linksQuery = createEnrollLinksQuery();
  const createLink = createCreateEnrollLinkMutation();
  const revokeLink = createRevokeEnrollLinkMutation();

  const groups = $derived<SettingsGroup[]>($groupsQuery.data?.groups ?? []);
  const links = $derived<EnrollLinkSummary[]>($linksQuery.data?.links ?? []);

  // ---- Form state ----
  // The form intentionally falls back to the historical defaults already
  // used by the CLI / Telegram path (24h, 1 use, group "default"), so the
  // dashboard behaves identically to the existing tooling.
  let groupName = $state('default');
  // Input is bound as string (HTML inputs always are); coerce on submit.
  let ttlHours = $state('24');
  let maxUses = $state('1');
  let label = $state('');

  // Last successful creation — surfaced in a "result card" with copy +
  // revocation. Cleared when the user submits again or revokes it.
  let lastIssued = $state<EnrollLinkOut | null>(null);

  // When the groups query finishes loading the very first time, prefer to
  // pre-select a real group rather than the literal string "default" if it
  // does not exist in the tenant.
  $effect(() => {
    if (!groups.length) return;
    if (!groups.some((g) => g.name === groupName)) {
      // groups.length > 0 already guards against undefined here.
      groupName = groups[0]!.name;
    }
  });

  function submit(e: Event): void {
    e.preventDefault();
    const ttl = Number(ttlHours);
    const uses = Number(maxUses);
    if (!groupName || !Number.isFinite(ttl) || !Number.isFinite(uses)) return;
    $createLink.mutate(
      {
        group_name: groupName,
        ttl_hours: ttl,
        max_uses: uses,
        label: label.trim() || null,
      },
      {
        onSuccess: (data) => {
          lastIssued = data;
        },
      },
    );
  }

  async function copy(text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard may be unavailable (insecure context, locked-down browser).
      // We deliberately swallow — the URL is still visible inline.
    }
  }

  function confirmRevoke(link: EnrollLinkSummary): void {
    const ok = window.confirm(
      `Revoke magic-link for group "${link.group_name}"? Future installs using this URL will fail.`,
    );
    if (!ok) return;
    $revokeLink.mutate(link.token_jti, {
      onSuccess: () => {
        if (lastIssued?.token_jti === link.token_jti) {
          lastIssued = null;
        }
      },
    });
  }

  function fmtDate(iso: string): string {
    try {
      return new Date(iso).toLocaleString();
    } catch {
      return iso;
    }
  }

  function remainingHours(iso: string): string {
    const ms = new Date(iso).getTime() - Date.now();
    if (!Number.isFinite(ms) || ms <= 0) return 'expired';
    const h = Math.floor(ms / 3_600_000);
    if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
    if (h >= 1) return `${h}h`;
    const m = Math.max(1, Math.floor(ms / 60_000));
    return `${m}m`;
  }

  const isAdminOnlyError = $derived(
    $linksQuery.isError && $linksQuery.error?.message?.toLowerCase().includes('admin'),
  );
</script>

<svelte:head>
  <title>Enroll · Remote-Pulse</title>
</svelte:head>

<section class="space-y-6" data-testid="enroll-page">
  <header class="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <h1 class="text-2xl font-bold tracking-tight">Enroll an agent</h1>
      <p class="text-sm text-muted">
        Generate a single-use magic-link to bootstrap a new Remote-Pulse agent. The link embeds a
        signed JWT and an install command for the target OS.
      </p>
    </div>
    <Badge variant="default" class="self-start sm:self-end">
      <ShieldCheck class="mr-1 size-3.5" aria-hidden="true" />
      admin required
    </Badge>
  </header>

  <!-- ====================== ISSUE FORM ====================== -->
  <Card data-testid="enroll-form-card">
    <CardHeader>
      <CardTitle class="text-base">
        <KeyRound class="mr-1 inline size-4" aria-hidden="true" />
        New magic-link
      </CardTitle>
    </CardHeader>
    <CardContent>
      <form class="grid gap-4 sm:grid-cols-2" onsubmit={submit}>
        <label class="space-y-1 text-sm">
          <span class="font-medium">Group</span>
          <select
            class="block w-full rounded border border-border-default bg-base px-2 py-1.5 text-sm"
            bind:value={groupName}
            data-testid="enroll-group"
            disabled={$createLink.isPending}
          >
            {#if groups.length === 0}
              <option value="default">default</option>
            {:else}
              {#each groups as g (g.name)}
                <option value={g.name}>{g.name}</option>
              {/each}
            {/if}
          </select>
        </label>

        <label class="space-y-1 text-sm">
          <span class="font-medium">TTL (hours)</span>
          <Input
            type="number"
            min="1"
            max="720"
            bind:value={ttlHours}
            data-testid="enroll-ttl"
            disabled={$createLink.isPending}
          />
        </label>

        <label class="space-y-1 text-sm">
          <span class="font-medium">Max uses</span>
          <Input
            type="number"
            min="1"
            max="100"
            bind:value={maxUses}
            data-testid="enroll-max-uses"
            disabled={$createLink.isPending}
          />
        </label>

        <label class="space-y-1 text-sm">
          <span class="font-medium">Label <span class="text-muted">(optional)</span></span>
          <Input
            type="text"
            maxlength={120}
            bind:value={label}
            placeholder="e.g. Mac mini Mario"
            data-testid="enroll-label"
            disabled={$createLink.isPending}
          />
        </label>

        <div class="sm:col-span-2 flex justify-end">
          <Button type="submit" disabled={$createLink.isPending} data-testid="enroll-submit">
            {#if $createLink.isPending}
              <Loader2 class="mr-1 size-4 animate-spin" aria-hidden="true" />
              Generating…
            {:else}
              <Plus class="mr-1 size-4" aria-hidden="true" />
              Generate magic-link
            {/if}
          </Button>
        </div>
      </form>
    </CardContent>
  </Card>

  <!-- ====================== ISSUED LINK ====================== -->
  {#if lastIssued}
    <Card data-testid="enroll-result-card">
      <CardHeader>
        <CardTitle class="text-base">Magic-link ready</CardTitle>
      </CardHeader>
      <CardContent class="space-y-3 text-sm">
        <p class="text-muted">
          Hand this URL to whoever is installing the agent. It works for {lastIssued.max_uses}
          {lastIssued.max_uses === 1 ? 'install' : 'installs'} and expires in
          {lastIssued.expires_in_hours}h.
        </p>

        <div class="flex flex-wrap items-start gap-2">
          <code
            class="break-all rounded bg-muted/10 px-2 py-1 font-mono text-xs flex-1"
            data-testid="enroll-url"
          >
            {lastIssued.url}
          </code>
          <Button
            size="sm"
            variant="outline"
            onclick={() => void copy(lastIssued!.url)}
            data-testid="enroll-copy-unix"
          >
            <Copy class="mr-1 size-3.5" aria-hidden="true" />
            Copy
          </Button>
        </div>

        <details class="text-xs text-muted">
          <summary class="cursor-pointer">Windows install URL</summary>
          <div class="mt-2 flex flex-wrap items-start gap-2">
            <code class="break-all rounded bg-muted/10 px-2 py-1 font-mono flex-1">
              {lastIssued.install_url_windows}
            </code>
            <Button
              size="sm"
              variant="outline"
              onclick={() => void copy(lastIssued!.install_url_windows)}
            >
              <Copy class="mr-1 size-3.5" aria-hidden="true" />
              Copy
            </Button>
          </div>
        </details>

        <details class="text-xs text-muted">
          <summary class="cursor-pointer">Raw JWT (advanced)</summary>
          <code class="mt-2 block break-all rounded bg-muted/10 px-2 py-1 font-mono">
            {lastIssued.token}
          </code>
        </details>
      </CardContent>
    </Card>
  {/if}

  <!-- ====================== ACTIVE LINKS ====================== -->
  <Card>
    <CardHeader>
      <CardTitle class="text-base">Active magic-links</CardTitle>
    </CardHeader>
    <CardContent class="p-0">
      {#if $linksQuery.isPending}
        <div class="flex items-center gap-2 px-4 py-8 text-sm text-muted">
          <Loader2 class="size-4 animate-spin" aria-hidden="true" />
          Loading links…
        </div>
      {:else if $linksQuery.isError}
        <div class="space-y-2 px-4 py-6 text-sm">
          <p class="text-danger">
            {#if isAdminOnlyError}
              You need the admin role to issue magic-links.
            {:else}
              Failed to load links: {$linksQuery.error?.message ?? 'unknown error'}
            {/if}
          </p>
          {#if !isAdminOnlyError}
            <Button size="sm" onclick={() => void $linksQuery.refetch()}>Retry</Button>
          {/if}
        </div>
      {:else if links.length === 0}
        <div class="px-4 py-8 text-center text-sm text-muted">
          No active magic-links. Generate one above to enroll a new agent.
        </div>
      {:else}
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-muted/5 text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th class="px-4 py-2">Group</th>
                <th class="px-4 py-2">Issued by</th>
                <th class="px-4 py-2">Expires</th>
                <th class="px-4 py-2">Uses</th>
                <th class="px-4 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {#each links as link (link.token_jti)}
                <tr class="border-t border-border-default" data-testid="enroll-link-row">
                  <td class="px-4 py-2 font-medium">{link.group_name}</td>
                  <td class="px-4 py-2 text-muted">{link.issued_by}</td>
                  <td class="px-4 py-2">
                    <div>{remainingHours(link.expires_at)}</div>
                    <div class="text-xs text-muted">{fmtDate(link.expires_at)}</div>
                  </td>
                  <td class="px-4 py-2 text-muted">
                    {link.used_count} / {link.max_uses}
                  </td>
                  <td class="px-4 py-2 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onclick={() => confirmRevoke(link)}
                      disabled={$revokeLink.isPending}
                      data-testid="enroll-revoke-btn"
                      aria-label={`Revoke magic-link for ${link.group_name}`}
                    >
                      <Trash2 class="mr-1 size-3.5" aria-hidden="true" />
                      Revoke
                    </Button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </CardContent>
  </Card>
</section>
