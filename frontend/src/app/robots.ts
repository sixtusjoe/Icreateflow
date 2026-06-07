import type { MetadataRoute } from "next";

const BASE = "https://icreateflow.com";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // Auth-gated app surfaces, admin, OAuth round-trips and the API
        // never belong in a search index.
        disallow: [
          "/dashboard",
          "/brands",
          "/clipping",
          "/posts",
          "/schedule",
          "/music",
          "/settings",
          "/account",
          "/admin",
          "/oauth",
          "/login",
          "/register",
          "/api/",
        ],
      },
    ],
    sitemap: `${BASE}/sitemap.xml`,
    host: BASE,
  };
}
