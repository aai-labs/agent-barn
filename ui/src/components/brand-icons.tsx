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
