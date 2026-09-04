export function UnavailableState() {
  return (
    <div className="kern-state">
      <div className="kern-state-mark" aria-hidden="true">
        <svg viewBox="0 0 20 20" fill="none">
          <rect
            x="3.5"
            y="5"
            width="13"
            height="10"
            rx="2"
            stroke="currentColor"
            strokeWidth="1.5"
          />
          <path
            d="M7 10h6"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </div>
      <h2>Feature unavailable</h2>
      <p>
        This destination is intentionally a placeholder until its implementation
        ticket is complete.
      </p>
    </div>
  );
}
