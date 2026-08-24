import React from "react";

interface BrandIconProps {
  size?: number;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Renders an SVG brand mark tinted to the current text color via CSS mask.
 * The source SVGs live in /public/brand and keep their original (filled) art;
 * masking lets us recolor them to match the surrounding UI without inlining
 * large path data.
 */
function MaskGlyph({
  src,
  size = 14,
  className,
  style,
}: BrandIconProps & { src: string }) {
  return (
    <span
      aria-hidden
      className={className}
      style={{
        display: "inline-block",
        width: size,
        height: size,
        flexShrink: 0,
        backgroundColor: "currentColor",
        WebkitMaskImage: `url(${src})`,
        maskImage: `url(${src})`,
        WebkitMaskRepeat: "no-repeat",
        maskRepeat: "no-repeat",
        WebkitMaskPosition: "center",
        maskPosition: "center",
        WebkitMaskSize: "contain",
        maskSize: "contain",
        ...style,
      }}
    />
  );
}

export function OpenClawIcon(p: BrandIconProps) {
  return <MaskGlyph src="/brand/openclaw.svg" {...p} />;
}

export function HermesIcon(p: BrandIconProps) {
  return <MaskGlyph src="/brand/hermes.svg" {...p} />;
}

/**
 * Renders a full-color brand mark as-is (unlike MaskGlyph, which tints a mark to
 * the surrounding text color). Communication platforms are recognized by their
 * real colors — Slack's mark is four colors, so masking it to one would flatten
 * the exact thing that makes it recognizable at a glance.
 */
function ColorGlyph({
  src,
  size = 14,
  className,
  style,
  label,
}: BrandIconProps & { src: string; label: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- small static local SVG, not a candidate for next/image optimization
    <img
      src={src}
      alt={label}
      className={className}
      style={{ width: size, height: size, flexShrink: 0, ...style }}
    />
  );
}

export function SlackIcon(p: BrandIconProps) {
  return <ColorGlyph src="/brand/slack.svg" label="Slack" {...p} />;
}

export function DiscordIcon(p: BrandIconProps) {
  return <ColorGlyph src="/brand/discord.svg" label="Discord" {...p} />;
}

export function TelegramIcon(p: BrandIconProps) {
  return <ColorGlyph src="/brand/telegram.svg" label="Telegram" {...p} />;
}

/** Brand icon element for a communication platform key (e.g. "slack"), or null if unknown. */
export function platformIcon(platformKey: string, props: BrandIconProps = {}): React.ReactNode | null {
  switch (platformKey) {
    case "slack": return <SlackIcon {...props} />;
    case "discord": return <DiscordIcon {...props} />;
    case "telegram": return <TelegramIcon {...props} />;
    default: return null;
  }
}
