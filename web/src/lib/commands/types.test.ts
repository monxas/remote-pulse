import { describe, it, expect } from 'vitest';
import {
  COMMAND_TYPES,
  DEFAULT_FORM_STATE,
  buildPayload,
  isHostSelectionValid,
  isPayloadValid,
  summarizePayload,
  type CommandFormState,
  type CommandTypeId,
} from './types';

function freshState(): CommandFormState {
  return structuredClone(DEFAULT_FORM_STATE);
}

describe('IssueCommandDialog form logic', () => {
  describe('isHostSelectionValid', () => {
    it('rejects an empty selection', () => {
      expect(isHostSelectionValid([])).toBe(false);
    });
    it('accepts a single host', () => {
      expect(isHostSelectionValid(['host-1'])).toBe(true);
    });
    it('accepts many hosts', () => {
      expect(isHostSelectionValid(['a', 'b', 'c'])).toBe(true);
    });
  });

  describe('COMMAND_TYPES catalogue', () => {
    it('exposes all five canonical command types', () => {
      const ids = COMMAND_TYPES.map((t) => t.id);
      expect(ids).toEqual(['shell', 'reboot', 'ssh-rotate', 'apt-update', 'exec-script']);
    });
    it('marks shell + reboot + ssh-rotate + exec-script as requiring approval by default', () => {
      const requiringApproval = COMMAND_TYPES.filter((t) => t.defaultRequiresApproval).map(
        (t) => t.id,
      );
      expect(requiringApproval.sort()).toEqual(
        ['shell', 'reboot', 'ssh-rotate', 'exec-script'].sort(),
      );
    });
  });

  describe('buildPayload', () => {
    it('builds a shell payload with cmd + timeout_s', () => {
      const state = freshState();
      state.shell.cmd = '  systemctl status nginx  ';
      state.shell.timeoutS = 30;
      expect(buildPayload('shell', state)).toEqual({
        cmd: 'systemctl status nginx',
        timeout_s: 30,
      });
    });

    it('omits timeout_s when zero', () => {
      const state = freshState();
      state.shell.cmd = 'ls';
      state.shell.timeoutS = 0;
      expect(buildPayload('shell', state)).toEqual({ cmd: 'ls' });
    });

    it('rejects an empty shell command', () => {
      const state = freshState();
      state.shell.cmd = '   ';
      expect(() => buildPayload('shell', state)).toThrow(/empty/i);
    });

    it('floors and clamps the reboot delay', () => {
      const state = freshState();
      state.reboot.delayS = 12.7;
      expect(buildPayload('reboot', state)).toEqual({ delay_s: 12 });
      state.reboot.delayS = -5;
      expect(buildPayload('reboot', state)).toEqual({ delay_s: 0 });
    });

    it('ssh-rotate is a static ed25519 payload', () => {
      expect(buildPayload('ssh-rotate', freshState())).toEqual({ algorithm: 'ed25519' });
    });

    it('apt-update carries the reboot-if-needed flag', () => {
      const state = freshState();
      expect(buildPayload('apt-update', state)).toEqual({ reboot_if_needed: false });
      state['apt-update'].rebootIfNeeded = true;
      expect(buildPayload('apt-update', state)).toEqual({ reboot_if_needed: true });
    });

    it('exec-script splits args on whitespace', () => {
      const state = freshState();
      state['exec-script'].script = 'backup-postgres';
      state['exec-script'].args = '  --full   --gzip ';
      expect(buildPayload('exec-script', state)).toEqual({
        script: 'backup-postgres',
        args: ['--full', '--gzip'],
      });
    });

    it('exec-script omits args when blank', () => {
      const state = freshState();
      state['exec-script'].script = 'noop';
      expect(buildPayload('exec-script', state)).toEqual({ script: 'noop' });
    });

    it('exec-script requires a script name', () => {
      const state = freshState();
      expect(() => buildPayload('exec-script', state)).toThrow(/script/i);
    });
  });

  describe('isPayloadValid', () => {
    it('returns false for incomplete state, true for complete', () => {
      const state = freshState();
      const cases: ReadonlyArray<[CommandTypeId, boolean]> = [
        ['shell', false],
        ['reboot', true],
        ['ssh-rotate', true],
        ['apt-update', true],
        ['exec-script', false],
      ];
      for (const [type, expected] of cases) {
        expect(isPayloadValid(type, state)).toBe(expected);
      }
      state.shell.cmd = 'ls';
      state['exec-script'].script = 'noop';
      expect(isPayloadValid('shell', state)).toBe(true);
      expect(isPayloadValid('exec-script', state)).toBe(true);
    });
  });

  describe('summarizePayload', () => {
    it('pretty-prints with 2-space indent', () => {
      expect(summarizePayload({ a: 1, b: 'x' })).toBe('{\n  "a": 1,\n  "b": "x"\n}');
    });
  });
});
