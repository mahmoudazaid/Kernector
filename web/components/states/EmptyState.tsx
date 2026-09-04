export function EmptyState() {
  return (
    <div className="kern-state">
      <div className="kern-state-mark" aria-hidden="true">
        <svg viewBox="0 0 20 20" fill="none">
          <rect
            x="3"
            y="4"
            width="14"
            height="12"
            rx="2"
            stroke="currentColor"
            strokeWidth="1.5"
          />
          <path d="M3 8h14" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </div>
      <h2>Nothing here yet</h2>
      <p>
        Neutral empty state; feature-specific actions belong to later tickets.
      </p>
    </div>
  );
}
