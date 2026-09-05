type UnavailableStateProps = {
  title?: string;
  description?: string;
};

export function UnavailableState({
  title = "Feature unavailable",
  description = "This destination is intentionally a placeholder until its implementation ticket is complete.",
}: UnavailableStateProps) {
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
      <h2>{title}</h2>
      <p>{description}</p>
    </div>
  );
}
