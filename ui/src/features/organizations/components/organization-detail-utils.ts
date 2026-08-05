export function organizationInitials(name: string) {
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word[0])
    .join("");
  return (letters || name).slice(0, 2).toUpperCase();
}
