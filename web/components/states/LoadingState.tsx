export function LoadingState() {
  return (
    <div className="kern-state">
      <div className="kern-skeleton" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <h2>Loading page shell…</h2>
      <p>The global loading boundary keeps the surrounding navigation available.</p>
    </div>
  );
}
