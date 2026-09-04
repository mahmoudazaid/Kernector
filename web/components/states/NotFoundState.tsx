import Link from "next/link";

export function NotFoundState() {
  return (
    <div className="kern-state">
      <div className="kern-state-mark" aria-hidden="true">
        <svg viewBox="0 0 20 20" fill="none">
          <path
            d="M4.5 10h11M10 4.5v11"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
          <circle
            cx="10"
            cy="10"
            r="7.25"
            stroke="currentColor"
            strokeWidth="1.5"
          />
        </svg>
      </div>
      <h2>Page not found</h2>
      <p>The requested route does not exist.</p>
      <Link className="kern-btn kern-btn-secondary" href="/">
        Return to Dashboard
      </Link>
    </div>
  );
}
