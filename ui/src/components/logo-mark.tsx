interface LogoMarkProps {
  size?: number;
}

/** The Agent Barn mark: the orange pixel barn, the same drawing as the favicon (`app/icon.svg`). */
export function LogoMark({ size = 26 }: LogoMarkProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="-0.7 -0.7 8.4 8.4"
      role="img"
      aria-label="Agent Barn"
      width={size}
      height={size}
      style={{ display: "block", flexShrink: 0 }}
    >
      <path
        fill="#f45a17"
        shapeRendering="crispEdges"
        d="M2 0h3v1h1v1h1v5H6V6H2v1H0V2h1V1h1V0Zm0 4v1h4V4H2Z"
      />
    </svg>
  );
}
