import { NotFoundState } from "@/components/states/NotFoundState";

export default function NotFoundPage() {
  return (
    <section
      className="kern-content-state"
      aria-live="polite"
      aria-atomic="true"
    >
      <NotFoundState />
    </section>
  );
}
