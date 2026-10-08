/** DhanDrishti mark: an eye whose iris is a rising signal. Mirrors src/app/icon.svg. */
export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <defs>
        <linearGradient id="dd-logo-g" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#14b8a6" />
          <stop offset="1" stopColor="#4cc3f0" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="#0b1220" />
      <path
        d="M3.5 16C7 10.5 11.2 8 16 8s9 2.5 12.5 8C25 21.5 20.8 24 16 24S7 21.5 3.5 16Z"
        fill="none"
        stroke="url(#dd-logo-g)"
        strokeWidth="2.4"
        strokeLinejoin="round"
      />
      <path
        d="M9.5 19.5 13.5 16l3 2.2 5.2-5.7"
        fill="none"
        stroke="#e8edf5"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="22" cy="12.2" r="2.1" fill="#5eead4" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <div className="flex items-center gap-3">
      <LogoMark />
      <div className="leading-tight">
        <div className="text-[15px] font-bold tracking-[0.14em] text-ink">DHANDRISHTI</div>
        <div className="text-[11px] text-muted">See the signal. Understand the stock.</div>
      </div>
    </div>
  );
}
