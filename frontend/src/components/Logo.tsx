/**
 * Icreateflow mark — a lime broadcast signal (dot + three radiating arcs)
 * on the brand's foreground-colored rounded tile. The tile flips with the
 * theme (black in dark mode, near-black in light mode) because it uses
 * `bg-foreground`; the mark itself stays lime in both modes.
 */
export default function Logo({
  size = 32,
  radius,
  className = "",
}: {
  size?: number;
  radius?: number;
  className?: string;
}) {
  const r = radius ?? Math.round(size * 0.22);
  return (
    <div
      className={`inline-flex shrink-0 items-center justify-center bg-foreground ${className}`}
      style={{ width: size, height: size, borderRadius: r }}
      aria-label="Icreateflow"
    >
      <svg
        viewBox="0 0 64 64"
        width={Math.round(size * 0.78)}
        height={Math.round(size * 0.78)}
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        <circle cx="20" cy="32" r="3.5" fill="#D4F33D" />
        <path
          d="M27 24 A10 10 0 0 1 27 40"
          stroke="#D4F33D"
          strokeWidth="3.5"
          strokeLinecap="round"
          fill="none"
        />
        <path
          d="M35 18 A17 17 0 0 1 35 46"
          stroke="#D4F33D"
          strokeWidth="3.5"
          strokeLinecap="round"
          fill="none"
          opacity="0.65"
        />
        <path
          d="M43 12 A24 24 0 0 1 43 52"
          stroke="#D4F33D"
          strokeWidth="3.5"
          strokeLinecap="round"
          fill="none"
          opacity="0.35"
        />
      </svg>
    </div>
  );
}
