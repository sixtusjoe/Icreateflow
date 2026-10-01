import AuthShell from "@/components/auth/AuthShell";

// Read outside render, so the year is a plain value by the time the
// component draws (react-hooks/purity forbids reading the clock in render).
function currentYear() {
  return new Date().getFullYear();
}

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <AuthShell year={currentYear()}>{children}</AuthShell>;
}
