/**
 * The visible title and description for one settings card.
 *
 * Distinct from the `title`/`description` props on {@link SettingsSection}, which are
 * deliberately not rendered — those identify the card to assistive tech and tests while
 * the surrounding page owns the visible heading. A card whose content is not
 * self-describing needs a heading of its own, and this keeps every such heading in one
 * shape rather than each card inventing its own type scale.
 */
export function SettingsSectionHeading({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="min-w-0">
      <h3 className="m-0 text-[0.95rem] font-semibold" style={{ color: "var(--ink)" }}>
        {title}
      </h3>
      <p className="mb-0 mt-0.5 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
        {description}
      </p>
    </div>
  );
}
