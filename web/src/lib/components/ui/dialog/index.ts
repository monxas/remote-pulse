import { Dialog as DialogPrimitive } from 'bits-ui';
import Dialog from './dialog.svelte';
import DialogContent from './dialog-content.svelte';
import DialogOverlay from './dialog-overlay.svelte';
import DialogHeader from './dialog-header.svelte';
import DialogFooter from './dialog-footer.svelte';
import DialogTitle from './dialog-title.svelte';
import DialogDescription from './dialog-description.svelte';

const DialogTrigger = DialogPrimitive.Trigger;
const DialogClose = DialogPrimitive.Close;
const DialogPortal = DialogPrimitive.Portal;

export {
  Dialog,
  DialogTrigger,
  DialogClose,
  DialogPortal,
  DialogContent,
  DialogOverlay,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
};
