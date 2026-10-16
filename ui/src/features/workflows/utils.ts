const KEY_MAX = 64;

/** FNV-1a over UTF-8 bytes: a short, deterministic suffix that reduces normalization collisions. */
function labelHash(label: string): string {
  let hash = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(label)) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

/**
 * Derives the internal input key from its human label. Accents fold to ASCII,
 * apostrophes drop, every other run of punctuation or spaces becomes one
 * hyphen, and keys gain an `input-` prefix unless they start with a letter. Letters or digits that have
 * no ASCII form, and labels too long for a key, add a label hash so different
 * labels are less likely to share a key; schema validation still rejects collisions. Labels that differ only by case, accents or
 * punctuation derive the same key and are reported as duplicates.
 */
export function inputKeyFromLabel(label: string): string {
  const folded = label
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/['’]/g, "")
    .trim();
  if (!folded) return "";
  let key = folded.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const lossy = /[\p{L}\p{N}]/u.test(folded.replace(/[a-z0-9]/g, ""));
  if (!/^[a-z]/.test(key)) key = key ? `input-${key}` : "input";
  if (lossy || key.length > KEY_MAX)
    key = `${key.slice(0, KEY_MAX - 9).replace(/-+$/, "")}-${labelHash(folded)}`;
  return key;
}
