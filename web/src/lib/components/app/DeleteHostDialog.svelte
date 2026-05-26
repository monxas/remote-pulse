<script lang="ts">
  import { AlertTriangle, Loader2 } from '@lucide/svelte';
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
  } from '$lib/components/ui/dialog';
  import { Button } from '$lib/components/ui/button';
  import { createDeleteHostMutation } from '$lib/queries';

  type Props = {
    open: boolean;
    onOpenChange: (next: boolean) => void;
    hostId: string;
    hostname: string;
    /** Invoked after a successful delete (typically navigates away). */
    onDeleted?: () => void;
  };

  let { open = $bindable(false), onOpenChange, hostId, hostname, onDeleted }: Props = $props();

  const mutation = createDeleteHostMutation();

  function close(): void {
    if ($mutation.isPending) return;
    onOpenChange(false);
  }

  function confirm(): void {
    $mutation.mutate(hostId, {
      onSuccess: () => {
        onOpenChange(false);
        onDeleted?.();
      },
    });
  }
</script>

<Dialog {open} {onOpenChange}>
  <DialogContent class="max-w-md" role="alertdialog" data-testid="host-delete-dialog">
    <DialogHeader>
      <DialogTitle class="flex items-center gap-2">
        <AlertTriangle class="size-5 text-danger" aria-hidden="true" />
        Delete this host?
      </DialogTitle>
      <DialogDescription>
        This permanently deletes <span class="font-mono">{hostname}</span> and all its history (heartbeats,
        commands, SSH keys). This action cannot be undone.
      </DialogDescription>
    </DialogHeader>

    <DialogFooter>
      <Button
        variant="outline"
        onclick={close}
        disabled={$mutation.isPending}
        data-testid="host-delete-cancel"
      >
        Cancel
      </Button>
      <Button
        variant="danger"
        onclick={confirm}
        disabled={$mutation.isPending}
        data-testid="host-delete-confirm"
      >
        {#if $mutation.isPending}
          <Loader2 class="mr-2 size-4 animate-spin" aria-hidden="true" />
          Deleting…
        {:else}
          Delete host
        {/if}
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
