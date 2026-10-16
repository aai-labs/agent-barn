export function userInitials(user: { fullName?: string | null; email?: string | null }) {
  return (user.fullName ?? user.email ?? "U")
    .split(" ")
    .map((word) => word[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function organizationInitials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? words[0][0] + words[1][0] : name.slice(0, 2);
  return letters.toUpperCase();
}

/** The avatar fill the top bar already uses for the signed-in user. */
export const USER_AVATAR_BACKGROUND = "linear-gradient(135deg, #4338ca, #7c3aed)";
