/**
 * Icreateflow mark — a lime broadcast signal (dot + three radiating arcs)
 * on a near-black rounded tile. The tile is the same in both themes: it
 * used to be `bg-foreground`, which turned it white in dark mode, and the
 * lime mark on white read poorly — the owner asked for the light-theme
 * tile everywhere (2026-10-01).
 */
export default function Logo({
  size = 32,
  radius,
  className = "",
  src,
}: {
  size?: number;
  radius?: number;
  className?: string;
  src?: string;
}) {
  const r = radius ?? Math.round(size * 0.22);

  if (src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt="Logo"
        className={`shrink-0 object-contain ${className}`}
        style={{ width: size, height: size, borderRadius: r }}
      />
    );
  }

  return (
    <div
      className={`inline-flex shrink-0 items-center justify-center bg-[#0b0d12] ${className}`}
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
