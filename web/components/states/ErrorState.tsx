"use client";

import { Button } from "@/components/ui/Button";

type ErrorStateProps = {
  onRetry?: () => void;
};

export function ErrorState({ onRetry }: ErrorStateProps) {
  return (
    <div className="kern-state kern-state-error" role="alert">
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
