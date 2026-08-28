const GENERATED_LABEL = /\[(?:synthetic\s+(?:demo\s+)?(?:review|reply|follow-up|post)|synthetic\s+security-test\s+review)\]\s*/gi;
const THREAD_LABEL = /^\s*\[(?:level\s+\d+[^\]]*|root|reply\s+depth=\d+)\]\s*/gim;
const DISCLOSURE = /\s*(?:Merchant identity is source-backed; this post, media and promotions are synthetic\.|It is not a real user visit; prices and hours are synthetic\.)/gi;

/** Keep legacy seeded content readable while hiding generator/provenance markup. */
export function cleanDisplayContent(value: string | null | undefined): string {
  return (value ?? '')
    .replace(THREAD_LABEL, '')
    .replace(GENERATED_LABEL, '')
    .replace(/\bThis generated scenario describes\s+/gi, '')
    .replace(DISCLOSURE, '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .join('\n')
    .trim();
}
