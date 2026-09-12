export function formatAgentName(firstName: string, templateName?: string): string {
  const role = !templateName || templateName === "General Purpose" ? "Assistant" : templateName;
  const prefix = `${firstName} the `;
  return prefix + Array.from(role).slice(0, 255 - prefix.length).join("");
}
