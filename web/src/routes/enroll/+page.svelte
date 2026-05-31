<script lang="ts">
  import { onDestroy } from 'svelte';
  import QRCode from 'qrcode';
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
  // Default to the new short-code defaults: 5 minutes TTL, single use.
  // The form drives ``ttl_minutes`` directly; we no longer expose the
  // legacy ``ttl_hours`` field in the UI (the API still accepts it).
  // The four preset options below cover every operationally reasonable
  // case — anything below 5 min is too tight for someone alt-tabbing
  // into a terminal; anything past 24h is a credential-lifetime smell.
  const TTL_PRESETS: ReadonlyArray<{ value: number; label: string }> = [
    { value: 5, label: '5 min (recommended)' },
    { value: 30, label: '30 min' },
    { value: 120, label: '2 hours' },
    { value: 1440, label: '24 hours (max)' },
  ];

  let groupName = $state('default');
  // Selected preset value (minutes). Bound as string because <select>
  // values are always strings; we coerce on submit.
  let ttlMinutes = $state(String(TTL_PRESETS[0]!.value));
  let maxUses = $state('1');
  let label = $state('');

  // Last successful creation — surfaced in a "hero" result card.
  let lastIssued = $state<EnrollLinkOut | null>(null);

  // Live countdown for the result card. Updated every second.
  let now = $state(Date.now());
  const tick = setInterval(() => {
    now = Date.now();
  }, 1000);
  onDestroy(() => clearInterval(tick));

  // When the groups query finishes loading the very first time, prefer to
  // pre-select a real group rather than the literal string "default".
  $effect(() => {
    if (!groups.length) return;
    if (!groups.some((g) => g.name === groupName)) {
      groupName = groups[0]!.name;
    }
  });

  function submit(e: Event): void {
    e.preventDefault();
    const ttl = Number(ttlMinutes);
    const uses = Number(maxUses);
    if (!groupName || !Number.isFinite(ttl) || !Number.isFinite(uses)) return;
    $createLink.mutate(
      {
        group_name: groupName,
        ttl_minutes: ttl,
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
      // We deliberately swallow — the value is still visible inline.
    }
  }

  function confirmRevoke(link: EnrollLinkSummary): void {
    const display = link.code ?? link.token_jti;
    const ok = window.confirm(
      `Revoke enrollment ${display} (group "${link.group_name}")? Future installs using this code will fail.`,
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

  /**
   * Compact "expires in" formatter — returns "4m 23s" / "12m" / "2h 5m"
   * depending on magnitude. Driven by the ``now`` $state so it ticks live.
   */
  function expiresIn(iso: string, nowMs: number): string {
    const ms = new Date(iso).getTime() - nowMs;
    if (!Number.isFinite(ms) || ms <= 0) return 'expired';
    const totalSec = Math.floor(ms / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    if (h >= 1) return `${h}h ${m}m`;
    if (m >= 5) return `${m}m`;
    return `${m}m ${s.toString().padStart(2, '0')}s`;
  }

  const isAdminOnlyError = $derived(
    $linksQuery.isError && $linksQuery.error?.message?.toLowerCase().includes('admin'),
  );

  // Drive the hero countdown off the $state tick.
  const heroCountdown = $derived(lastIssued ? expiresIn(lastIssued.expires_at, now) : '');

  // ---- QR code rendering ------------------------------------------------
  // We render the Unix install_url as a data-URL PNG so a second device
  // (Family-Hub tablet → phone, friend's mac → friend's phone) can scan
  // the bootstrap command without copy-pasting through a chat app. We use
  // the SVG-as-data-URL form of the `qrcode` lib because:
  //   - it scales without blur (we display at two sizes: ~140 mobile,
  //     ~180 desktop) and the dashboard is dark-first, so the contrast
  //     stays sharp;
  //   - it's ~6 KB gzipped — cheaper than wiring a Svelte action;
  //   - the data-URL renders synchronously in <img>, no flash of empty.
  // We deliberately encode the *Unix* install_url (the bash one-liner)
  // because that is the only platform where a QR scan into a phone-then-
  // -kick-back-to-laptop flow makes sense; Windows agents are PowerShell
  // and operators on Windows always copy-paste the command directly.
  let qrDataUrl = $state<string>('');
  $effect(() => {
    const url = lastIssued?.install_url;
    if (!url) {
      qrDataUrl = '';
      return;
    }
    // Medium error correction is the sweet-spot: still scans through the
    // small specular reflections you get on a tablet screen, doesn't
    // bloat the matrix to the point of unreadable cells. The ``width``
    // param controls the *intrinsic* PNG size; the CSS scales it.
    void QRCode.toDataURL(url, {
      errorCorrectionLevel: 'M',
      margin: 2,
      width: 360,
      color: {
        // Pure black-on-white so it scans reliably under any browser
        // theme — the QR spec assumes a high-contrast pair.
        dark: '#000000',
        light: '#ffffff',
      },
    })
      .then((d) => {
        qrDataUrl = d;
      })
      .catch(() => {
        // QR generation can only fail on extreme inputs (>2953 bytes).
        // Our install_url is always well under that; if we ever break
        // that bound, fall back to "no QR" silently — the copy button
        // still works.
        qrDataUrl = '';
      });
  });
</script>

<svelte:head>
  <title>Enroll · Remote-Pulse</title>
</svelte:head>

<section class="space-y-6" data-testid="enroll-page">
  <header class="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <h1 class="text-2xl font-bold tracking-tight">Enroll an agent</h1>
      <p class="text-sm text-muted">
        Generate a short, memorable enrollment code (e.g. <code class="font-mono">K7M-X3F</code>) to
        bootstrap a new Remote-Pulse agent. The code is single-use by default and expires in 5
        minutes.
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
        New enrollment code
      </CardTitle>
    </CardHeader>
    <CardContent>
      <form class="grid gap-4 sm:grid-cols-2" onsubmit={submit}>
        <label class="space-y-1 text-sm">
          <span class="font-medium">Group</span>
          <select
            class="touch-target block w-full rounded border border-border-default bg-base px-2 py-1.5 text-sm"
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
          <span class="font-medium">Expiration</span>
          <select
            class="touch-target block w-full rounded border border-border-default bg-base px-2 py-1.5 text-sm"
            bind:value={ttlMinutes}
            data-testid="enroll-ttl"
            disabled={$createLink.isPending}
          >
            {#each TTL_PRESETS as preset (preset.value)}
              <option value={String(preset.value)}>{preset.label}</option>
            {/each}
          </select>
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
              Generate code
            {/if}
          </Button>
        </div>
      </form>
    </CardContent>
  </Card>

  <!-- ====================== ISSUED CODE — HERO ====================== -->
  {#if lastIssued}
    <Card data-testid="enroll-result-card">
      <CardHeader>
        <CardTitle class="text-base">Enrollment code ready</CardTitle>
      </CardHeader>
      <CardContent class="space-y-4 text-sm">
        <!-- HERO: big monospace code on the left, scannable QR on the
             right (desktop) or stacked (mobile). The QR encodes the Unix
             install_url so a second device (operator's phone, Family Hub
             tablet → friend's phone) can scan it and paste-and-run on
             the target machine. -->
        <div
          class="flex flex-col items-center gap-4 rounded-lg bg-accent/5 px-4 py-6 sm:flex-row sm:items-center sm:justify-center sm:gap-8"
        >
          <div class="flex flex-col items-center gap-2">
            <button
              type="button"
              class="font-mono text-5xl font-bold tracking-widest tabular-nums hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded px-2"
              onclick={() => void copy(lastIssued!.code)}
              data-testid="enroll-code-hero"
              aria-label="Copy enrollment code"
            >
              {lastIssued.code}
            </button>
            <p class="text-xs text-muted" data-testid="enroll-countdown">
              Expires in <span class="font-mono">{heroCountdown}</span> · {lastIssued.max_uses}
              {lastIssued.max_uses === 1 ? 'use' : 'uses'} · group
              <span class="font-mono">{lastIssued.group_name}</span>
            </p>
          </div>
          {#if qrDataUrl}
            <div class="flex flex-col items-center gap-1" data-testid="enroll-qr">
              <img
                src={qrDataUrl}
                alt="QR code linking to the Unix install command"
                class="h-[140px] w-[140px] rounded-md bg-white p-1 sm:h-[180px] sm:w-[180px]"
                data-testid="enroll-qr-img"
              />
              <p class="text-xs text-muted">Scan to install (Unix/macOS)</p>
            </div>
          {/if}
        </div>

        <!-- Install command (Linux/macOS) -->
        <div>
          <p class="mb-1 text-xs font-medium uppercase tracking-wide text-muted">
            Linux / macOS install
          </p>
          <div class="flex flex-wrap items-start gap-2">
            <code
              class="flex-1 break-all rounded bg-muted/10 px-2 py-1 font-mono text-xs"
              data-testid="enroll-install-cmd"
            >
              {lastIssued.install_url}
            </code>
            <Button
              size="sm"
              variant="outline"
              onclick={() => void copy(lastIssued!.install_url)}
              data-testid="enroll-copy-install"
            >
              <Copy class="mr-1 size-3.5" aria-hidden="true" />
              Copy
            </Button>
          </div>
        </div>

        <!-- Install command (Windows) -->
        <details class="text-xs text-muted">
          <summary class="cursor-pointer">Windows install</summary>
          <div class="mt-2 flex flex-wrap items-start gap-2">
            <code class="flex-1 break-all rounded bg-muted/10 px-2 py-1 font-mono">
              {lastIssued.install_url_windows_short}
            </code>
            <Button
              size="sm"
              variant="outline"
              onclick={() => void copy(lastIssued!.install_url_windows_short)}
            >
              <Copy class="mr-1 size-3.5" aria-hidden="true" />
              Copy
            </Button>
          </div>
        </details>

        <!-- Legacy fallback — collapsed. JWT path still works against this
             server for back-compat; surface it for operators on old agents. -->
        <details class="text-xs text-muted" data-testid="enroll-legacy-details">
          <summary class="cursor-pointer">Advanced — legacy JWT URL</summary>
          <div class="mt-2 space-y-2">
            <p>
              The 250-char URL below is retained for backwards compatibility with pre-1.1 agents.
              Avoid logging or sharing it over insecure channels.
            </p>
            <div class="flex flex-wrap items-start gap-2">
              <code
                class="flex-1 break-all rounded bg-muted/10 px-2 py-1 font-mono"
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
          </div>
        </details>
      </CardContent>
    </Card>
  {/if}

  <!-- ====================== ACTIVE LINKS ====================== -->
  <Card>
    <CardHeader>
      <CardTitle class="text-base">Active enrollment codes</CardTitle>
    </CardHeader>
    <CardContent class="p-0">
      {#if $linksQuery.isPending}
        <div class="flex items-center gap-2 px-4 py-8 text-sm text-muted">
          <Loader2 class="size-4 animate-spin" aria-hidden="true" />
          Loading codes…
        </div>
      {:else if $linksQuery.isError}
        <div class="space-y-2 px-4 py-6 text-sm">
          <p class="text-danger-text">
            {#if isAdminOnlyError}
              You need the admin role to issue enrollment codes.
            {:else}
              Failed to load codes: {$linksQuery.error?.message ?? 'unknown error'}
            {/if}
          </p>
          {#if !isAdminOnlyError}
            <Button size="sm" onclick={() => void $linksQuery.refetch()}>Retry</Button>
          {/if}
        </div>
      {:else if links.length === 0}
        <div class="px-4 py-8 text-center text-sm text-muted">
          No active codes. Generate one above to enroll a new agent.
        </div>
      {:else}
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-muted/5 text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th class="px-4 py-2">Code</th>
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
                  <td class="px-4 py-2 font-mono font-medium" data-testid="enroll-row-code">
                    {link.code ?? '—'}
                  </td>
                  <td class="px-4 py-2">{link.group_name}</td>
                  <td class="px-4 py-2 text-muted">{link.issued_by}</td>
                  <td class="px-4 py-2">
                    <div>{expiresIn(link.expires_at, now)}</div>
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
                      aria-label={`Revoke enrollment code for ${link.group_name}`}
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
