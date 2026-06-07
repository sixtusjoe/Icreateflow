/**
 * Structured data (schema.org JSON-LD) for the site.
 * Rendered once in the root layout so every page carries Organization +
 * WebSite + SoftwareApplication markup for rich results.
 */

const BASE = "https://icreateflow.com";

// When social profiles exist, add their full URLs here and they flow into the
// Organization schema automatically, e.g.:
//   "https://twitter.com/icreateflow", "https://instagram.com/icreateflow"
const SOCIAL_PROFILES: string[] = [];

export function SiteJsonLd() {
  const graph = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": `${BASE}/#organization`,
        name: "Icreateflow",
        url: BASE,
        logo: `${BASE}/brand-logo.png`,
        description:
          "Promotion and distribution platform for artists, brands, movies and podcasts.",
        ...(SOCIAL_PROFILES.length ? { sameAs: SOCIAL_PROFILES } : {}),
      },
      {
        "@type": "WebSite",
        "@id": `${BASE}/#website`,
        url: BASE,
        name: "Icreateflow",
        publisher: { "@id": `${BASE}/#organization` },
        inLanguage: "en-US",
      },
      {
        "@type": "SoftwareApplication",
        "@id": `${BASE}/#software`,
        name: "Icreateflow",
        applicationCategory: "BusinessApplication",
        operatingSystem: "Web",
        url: BASE,
        description:
          "Push your catalog across TikTok, YouTube, Instagram and Facebook on a schedule, toward a view target, until the numbers land.",
        publisher: { "@id": `${BASE}/#organization` },
        offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
      },
    ],
  };

  return (
    <script
      type="application/ld+json"
      // JSON-LD is static, trusted content — safe to inline.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(graph) }}
    />
  );
}
