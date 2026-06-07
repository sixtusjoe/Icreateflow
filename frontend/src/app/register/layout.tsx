import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Create account",
  description: "Create your Icreateflow account and start promoting your catalog.",
  robots: { index: false, follow: true },
};

export default function RegisterLayout({ children }: { children: React.ReactNode }) {
  return children;
}
