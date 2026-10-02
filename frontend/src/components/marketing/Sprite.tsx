/**
 * The icons the public pages draw many times, defined once as SVG symbols
 * and drawn with <svg><use href="#tt" /></svg>. The platform marks match
 * PlatformIcon in the kit; "mark" is the logo's broadcast signal, as in
 * Logo.tsx.
 */
export default function Sprite() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
      <symbol id="tt" viewBox="0 0 24 24"><path fill="currentColor" d="M21 8.6a6.6 6.6 0 0 1-4.6-1.9v7.9a6.2 6.2 0 1 1-5.4-6.1v2.9a3.3 3.3 0 1 0 2.5 3.2V2h2.9A6.6 6.6 0 0 0 21 6.7z" /></symbol>
      <symbol id="yt" viewBox="0 0 24 24"><path fill="currentColor" d="M23 12s0-3.8-.5-5.6a2.9 2.9 0 0 0-2-2C18.7 4 12 4 12 4s-6.7 0-8.5.5a2.9 2.9 0 0 0-2 2C1 8.2 1 12 1 12s0 3.8.5 5.6a2.9 2.9 0 0 0 2 2C5.3 20 12 20 12 20s6.7 0 8.5-.5a2.9 2.9 0 0 0 2-2C23 15.8 23 12 23 12zM9.8 15.4V8.6l5.8 3.4z" /></symbol>
      <symbol id="ig" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="5" /><circle cx="12" cy="12" r="4" /></g><circle cx="17.3" cy="6.7" r="1.1" fill="currentColor" /></symbol>
      <symbol id="fb" viewBox="0 0 24 24"><path fill="currentColor" d="M22 12a10 10 0 1 0-11.6 9.9v-7h-2.5V12h2.5V9.8c0-2.5 1.5-3.9 3.8-3.9 1.1 0 2.2.2 2.2.2v2.5h-1.3c-1.2 0-1.6.8-1.6 1.6V12h2.8l-.4 2.9h-2.4v7A10 10 0 0 0 22 12z" /></symbol>
      <symbol id="xx" viewBox="0 0 24 24"><path fill="currentColor" d="M18.9 2H22l-7 8 8.2 12h-6.4l-5-7.3L5.9 22H2.8l7.5-8.6L2.5 2h6.6l4.5 6.6zm-1.1 18h1.7L7.3 3.8H5.5z" /></symbol>
      <symbol id="arr" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" d="M5 12h14M13 6l6 6-6 6" /></symbol>
      <symbol id="chk" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" d="M5 12.5l4.5 4.5L19 7.5" /></symbol>
      <symbol id="mark" viewBox="0 0 64 64"><circle cx="20" cy="32" r="3.5" fill="#D4F33D" /><path d="M27 24 A10 10 0 0 1 27 40" stroke="#D4F33D" strokeWidth="3.5" strokeLinecap="round" fill="none" /><path d="M35 18 A17 17 0 0 1 35 46" stroke="#D4F33D" strokeWidth="3.5" strokeLinecap="round" fill="none" opacity=".65" /><path d="M43 12 A24 24 0 0 1 43 52" stroke="#D4F33D" strokeWidth="3.5" strokeLinecap="round" fill="none" opacity=".35" /></symbol>
    </svg>
  );
}

/** One sprite icon. */
export function Icon({ id, size, className }: { id: string; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} className={className} aria-hidden="true">
      <use href={`#${id}`} />
    </svg>
  );
}
