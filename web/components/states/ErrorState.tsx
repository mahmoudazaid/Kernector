"use client";

import { Button } from "@/components/ui/Button";

type ErrorStateProps = {
  onRetry?: () => void;
};

export function ErrorState({ onRetry }: ErrorStateProps) {
  return (
    <div className="kern-state kern-state-error" role="alert">
      <div className="kern-state-mark kern-state-mark-error" aria-hidden="true">
        <svg viewBox="0 0 20 20" fill="none">
          <circle
            cx="10"
            cy="10"
            r="7.25"
            stroke="currentColor"
            strokeWidth="1.5"
          />
          <path
            d="M10 6.5v4.25M10 13.5h.01"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </div>
      <h2>Something went wrong</h2>
      <p>A safe global error boundary without exposing internal details.</p>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
