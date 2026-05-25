/**
 * Command-type catalogue + payload shape builders.
 *
 * The Issue-command dialog steps the user through a host selection, a
 * command-type card, and a per-type payload form. We keep the per-type
 * defaults + builders + validators in a single place so the dialog stays
 * declarative and we can unit-test the payload shape per type.
 *
 * Backend contract:
 *   - "shell"           -> { cmd: string, timeout_s?: number }
 *   - "reboot"          -> { delay_s: number }
 *   - "ssh-rotate"      -> { algorithm?: "ed25519" }
 *   - "apt-update"      -> { reboot_if_needed: boolean }
 *   - "exec-script"     -> { script: string, args?: string[] }
 */

export type CommandTypeId = 'shell' | 'reboot' | 'ssh-rotate' | 'apt-update' | 'exec-script';

export interface CommandTypeMeta {
  id: CommandTypeId;
  label: string;
  description: string;
  defaultRequiresApproval: boolean;
}

export const COMMAND_TYPES: ReadonlyArray<CommandTypeMeta> = [
  {
    id: 'shell',
    label: 'Shell',
    description: 'Run an arbitrary shell command on the target host.',
    defaultRequiresApproval: true,
  },
  {
    id: 'reboot',
    label: 'Reboot',
    description: 'Restart the host after an optional delay.',
    defaultRequiresApproval: true,
  },
  {
    id: 'ssh-rotate',
    label: 'Rotate SSH key',
    description: 'Generate a new agent signing key.',
    defaultRequiresApproval: true,
  },
  {
    id: 'apt-update',
    label: 'apt-update',
    description: 'Run unattended package updates.',
    defaultRequiresApproval: false,
  },
  {
    id: 'exec-script',
    label: 'Exec script',
    description: 'Run a server-managed signed script.',
    defaultRequiresApproval: true,
  },
] as const;

export type ShellPayload = { cmd: string; timeout_s?: number };
export type RebootPayload = { delay_s: number };
export type SshRotatePayload = { algorithm: 'ed25519' };
export type AptUpdatePayload = { reboot_if_needed: boolean };
export type ExecScriptPayload = { script: string; args?: string[] };

export type CommandFormState = {
  shell: { cmd: string; timeoutS: number };
  reboot: { delayS: number };
  'ssh-rotate': Record<string, never>;
  'apt-update': { rebootIfNeeded: boolean };
  'exec-script': { script: string; args: string };
};

export const DEFAULT_FORM_STATE: CommandFormState = {
  shell: { cmd: '', timeoutS: 60 },
  reboot: { delayS: 5 },
  'ssh-rotate': {},
  'apt-update': { rebootIfNeeded: false },
  'exec-script': { script: '', args: '' },
};

/**
 * Build the API payload for a given command type from the local form state.
 * Throws when the input is invalid so the dialog can surface the message
 * inline before issuing.
 */
export function buildPayload(
  type: CommandTypeId,
  state: CommandFormState,
): Record<string, unknown> {
  switch (type) {
    case 'shell': {
      const cmd = state.shell.cmd.trim();
      if (cmd.length === 0) {
        throw new Error('Shell command cannot be empty.');
      }
      const payload: ShellPayload = { cmd };
      if (state.shell.timeoutS > 0) payload.timeout_s = state.shell.timeoutS;
      return payload as unknown as Record<string, unknown>;
    }
    case 'reboot': {
      const delayS = Math.max(0, Math.floor(state.reboot.delayS));
      return { delay_s: delayS } satisfies RebootPayload;
    }
    case 'ssh-rotate':
      return { algorithm: 'ed25519' } satisfies SshRotatePayload;
    case 'apt-update':
      return { reboot_if_needed: state['apt-update'].rebootIfNeeded } satisfies AptUpdatePayload;
    case 'exec-script': {
      const script = state['exec-script'].script.trim();
      if (script.length === 0) {
        throw new Error('Script name cannot be empty.');
      }
      const raw = state['exec-script'].args.trim();
      const args = raw.length === 0 ? undefined : raw.split(/\s+/);
      const payload: ExecScriptPayload = { script };
      if (args) payload.args = args;
      return payload as unknown as Record<string, unknown>;
    }
  }
}

/** Whether the user can proceed past the host-selection step. */
export function isHostSelectionValid(hostIds: ReadonlyArray<string>): boolean {
  return hostIds.length > 0;
}

/** Whether the per-type payload form is in a submittable state. */
export function isPayloadValid(type: CommandTypeId, state: CommandFormState): boolean {
  try {
    buildPayload(type, state);
    return true;
  } catch {
    return false;
  }
}

/** Pretty short-summary of the payload used in the confirm step. */
export function summarizePayload(payload: Record<string, unknown>): string {
  return JSON.stringify(payload, null, 2);
}
