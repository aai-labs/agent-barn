import { createQueryKeyStructure } from "@/shared/query-keys";

export const USERS_PAGE_SIZE = 12;
export const usersKey = createQueryKeyStructure("users");

const UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const LOWER = "abcdefghijklmnopqrstuvwxyz";
const DIGITS = "0123456789";
const ALL = UPPER + LOWER + DIGITS;

export function generateStrongPassword(length = 16): string {
  const pick = (chars: string) =>
    chars[Math.floor(Math.random() * chars.length)];

  const result = [pick(UPPER), pick(LOWER), pick(DIGITS)];
  for (let i = result.length; i < length; i++) {
    result.push(pick(ALL));
  }

  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }

  return result.join("");
}
