import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Icreateflow — The promotion engine behind every drop",
    short_name: "Icreateflow",
    description:
      "Promotion and distribution platform for artists, brands, movies and podcasts. Push your catalog across TikTok, YouTube, Instagram and Facebook on a schedule, toward a view target.",
    start_url: "/",
    display: "standalone",
    background_color: "#0a0a0a",
    theme_color: "#0a0a0a",
    icons: [
      { src: "/brand-logo.png", sizes: "any", type: "image/png" },
      { src: "/apple-icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
    ],
  };
}
