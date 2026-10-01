/**
 * The frame both auth pages sit in: the form column on the left, the photo
 * stage on the right. It lives in the `(auth)` route group's layout rather
 * than in each page, so switching between Log in and Sign up swaps only the
 * form — the photo keeps its zoom and the cards keep their place instead of
 * re-entering on every tab press.
 *
 * There is no theme switch here, matching every other redesigned page, and
 * no Apple or Google buttons: the backend has email-and-password sign-in
 * only, and a button for a provider that does not exist teaches people a
 * way in that is not there.
 */
import Link from "next/link";
import Logo from "@/components/Logo";
import AuthStage from "./AuthStage";
import s from "./auth.module.css";

export default function AuthShell({ year, children }: { year: number; children: React.ReactNode }) {
  return (
    <div className={s.page}>
    <main className={s.frame}>
      <section className={s.side}>
        <Link href="/" className={s.brand} aria-label="Icreateflow home">
          <Logo size={26} radius={7} />
          <b>Icreateflow</b>
        </Link>

        <div className={s.center}>
          <div className={s.panel}>{children}</div>
        </div>

        <footer className={s.foot}>
          <span>&copy; {year} Icreateflow</span>
          <nav>
            <Link href="/terms">Terms</Link>
            <Link href="/privacy">Privacy</Link>
          </nav>
        </footer>
      </section>

      <AuthStage />
    </main>
    </div>
  );
}
