import { LoadingState } from "@/components/states/LoadingState";

export default function Loading() {
  return (
    <section className="kern-content-state" aria-live="polite" aria-atomic="true">
      <LoadingState />
    </section>
  );
}
