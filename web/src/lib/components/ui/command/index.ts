import { Command as CommandPrimitive } from 'bits-ui';
import Command from './command.svelte';
import CommandInput from './command-input.svelte';
import CommandList from './command-list.svelte';
import CommandEmpty from './command-empty.svelte';
import CommandGroup from './command-group.svelte';
import CommandItem from './command-item.svelte';

const CommandSeparator = CommandPrimitive.Separator;

export {
  Command,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandSeparator,
};
