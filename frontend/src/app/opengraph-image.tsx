import { ImageResponse } from "next/og";

export const alt = "Icreateflow — The promotion engine behind every drop";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background:
            "radial-gradient(120% 120% at 0% 0%, #1a1a1a 0%, #0a0a0a 55%)",
          padding: "72px",
          color: "#ffffff",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 14,
              background: "#ffffff",
              color: "#0a0a0a",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 34,
              fontWeight: 800,
            }}
          >
            i
          </div>
          <div style={{ fontSize: 34, fontWeight: 700, letterSpacing: -0.5 }}>
            Icreateflow
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div
            style={{
              fontSize: 76,
              fontWeight: 800,
              lineHeight: 1.05,
              letterSpacing: -2,
              maxWidth: 980,
            }}
          >
            The promotion engine behind every drop
          </div>
          <div style={{ fontSize: 30, color: "#a1a1aa", maxWidth: 920 }}>
            Push your catalog across TikTok, YouTube, Instagram &amp; Facebook —
            on a schedule, toward a view target.
          </div>
        </div>

        <div style={{ display: "flex", gap: 14 }}>
          {["TikTok", "YouTube", "Instagram", "Facebook"].map((p) => (
            <div
              key={p}
              style={{
                fontSize: 24,
                fontWeight: 600,
                color: "#e4e4e7",
                border: "1px solid #3f3f46",
                borderRadius: 999,
                padding: "10px 24px",
              }}
            >
              {p}
            </div>
          ))}
        </div>
      </div>
    ),
    { ...size },
  );
}
