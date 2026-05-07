import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/lib/auth";
import AppShell from "@/components/AppShell";

const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

async function fetchPublicConfig(): Promise<{ site_favicon_url?: string; site_logo_url?: string; site_name?: string }> {
  try {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const res = await fetch(`${apiUrl}/api/public/config`, { next: { revalidate: 3600 } });
    if (res.ok) return res.json();
  } catch {
    // ignore — use defaults
  }
  return {};
}

export async function generateMetadata(): Promise<Metadata> {
  const cfg = await fetchPublicConfig();
  return {
    metadataBase: new URL("https://icreateflow.com"),
    title: cfg.site_name ? `${cfg.site_name} — The promotion engine behind every drop` : "Icreateflow — The promotion engine behind every drop",
    description: "Promotion and distribution platform for artists, brands, movies and podcasts. Push your catalog across TikTok, YouTube, Instagram and Facebook on a schedule, toward a view target.",
    ...(cfg.site_favicon_url ? { icons: { icon: cfg.site_favicon_url } } : {}),
  };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cfg = await fetchPublicConfig();

  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`} suppressHydrationWarning data-scroll-behavior="smooth">
      <head>
        <Script id="theme-init" strategy="beforeInteractive">{`
          (function(){try{var t=localStorage.getItem('theme');if(t!=='light')document.documentElement.classList.add('dark')}catch(e){document.documentElement.classList.add('dark')}})()
        `}</Script>
        {cfg.site_favicon_url && (
          <link rel="icon" href={cfg.site_favicon_url} />
        )}
      </head>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased" suppressHydrationWarning>
        <AuthProvider>
          <AppShell logoUrl={cfg.site_logo_url}>{children}</AppShell>
        </AuthProvider>
        <Toaster />
      </body>
    </html>
  );
}
