import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Conditionally compose Tailwind class strings while deduplicating
 * conflicting utilities. Idiomatic shadcn helper. ADR-0009 §3.2.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
