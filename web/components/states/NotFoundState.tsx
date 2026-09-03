import Link from "next/link";

export function NotFoundState() {
  return (
    <div className="kern-state">
      <h2>Page not found</h2>
      <p>The requested route does not exist.</p>
      <Link className="kern-btn kern-btn-secondary" href="/">
        Return to Dashboard
      </Link>
    </div>
  );
}
