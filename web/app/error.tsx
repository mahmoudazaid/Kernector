"use client";

import { ErrorState } from "@/components/states/ErrorState";

type ErrorPageProps = {
  reset: () => void;
};

export default function ErrorPage({ reset }: ErrorPageProps) {
  return (
    <section className="kern-content-state" aria-live="polite" aria-atomic="true">
      <ErrorState onRetry={reset} />
    </section>
  );
}
