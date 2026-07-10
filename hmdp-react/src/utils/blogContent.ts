const LEGACY_LINE_BREAK_PATTERN = /<br\s*\/?\s*>/gi;

/**
 * Preserve line breaks from legacy posts without interpreting user content as HTML.
 * React will escape the returned string when it is rendered as a text child.
 */
export function normalizeBlogContent(content: string | null | undefined): string {
  return (content ?? '').replace(LEGACY_LINE_BREAK_PATTERN, '\n');
}
