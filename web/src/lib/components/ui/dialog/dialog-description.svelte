<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import { cn } from '$lib/utils';

  type Props = DialogPrimitive.DescriptionProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<DialogPrimitive.Description bind:ref class={cn('text-sm text-muted', className)} {...rest} />
