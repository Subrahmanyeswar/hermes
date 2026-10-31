// gui/src/utils/format.ts
// Consistent, human-readable count and number formatting utilities for HERMES GUI.

/**
 * Format a file count into a truthful, human-readable string.
 * Examples:
 *  - null / undefined / < 0 => "Unknown files"
 *  - 0 => "0 files"
 *  - 1 => "1 file"
 *  - 2 => "2 files"
 *  - 1000 => "1,000 files"
 *  - isCapped=true, count=1000 => "1,000+ files"
 */
export function formatFileCount(count: number | null | undefined, isCapped: boolean = false): string {
  if (count === null || count === undefined || count < 0) {
    return 'Unknown files';
  }
  const formattedNumber = count.toLocaleString('en-US');
  const unit = count === 1 ? 'file' : 'files';
  if (isCapped) {
    return `${formattedNumber}+ ${unit}`;
  }
  return `${formattedNumber} ${unit}`;
}
