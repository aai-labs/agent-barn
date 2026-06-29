interface LogoMarkProps {
  size?: number;
}

export function LogoMark({ size = 26 }: LogoMarkProps) {
  const radius = size <= 28 ? 8 : 12;
  const padding = Math.round(size * 0.14);

  return (
    <div
      aria-label="Agent Barn"
      style={{
        width: size,
        height: size,
        background: "var(--ink)",
        borderRadius: radius,
        display: "grid",
        placeItems: "center",
        flexShrink: 0,
        padding,
        boxSizing: "border-box",
      }}
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 100 100"
        aria-hidden
        style={{ display: "block", width: "100%", height: "100%" }}
      >
        {/* Outer barn silhouette */}
        <path
          d="M50,8 L82,28 L88,88 L12,88 L18,28 Z"
          stroke="var(--bg)"
          strokeWidth="8"
          strokeLinejoin="round"
          strokeLinecap="round"
          fill="none"
        />
        {/* Inner house outline */}
        <path
          d="M50,30 L70,43 L70,70 L30,70 L30,43 Z"
          stroke="var(--bg)"
          strokeWidth="6"
          strokeLinejoin="round"
          fill="none"
        />
        {/* Door / focal dot */}
        <circle cx="50" cy="55" r="6" fill="var(--bg)" />
      </svg>
    </div>
  );
}
