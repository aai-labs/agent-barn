const mediumDateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatDate(value: string | Date): string {
  return mediumDateTimeFormatter.format(
    typeof value === "string" ? new Date(value) : value,
  );
}
