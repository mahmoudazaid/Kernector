import { UnavailableState } from "@/components/states/UnavailableState";

type RoutePlaceholderProps = {
  title: string;
};

export function RoutePlaceholder({ title }: RoutePlaceholderProps) {
  return (
    <>
      <div className="kern-breadcrumb" aria-label="Breadcrumb">
        Kernector <span>/</span> <strong>{title}</strong>
      </div>
      <div className="kern-page-heading">
        <div>
          <h1>{title}</h1>
          <p>
            Placeholder route for the Next.js presentation foundation. No
            metrics, forms, chat behavior, or mocked business data are
            introduced in this ticket.
          </p>
        </div>
        <span className="kern-status">PLANNED</span>
      </div>
      <section
        className="kern-content-state"
        aria-live="polite"
        aria-atomic="true"
      >
        <UnavailableState />
      </section>
      <footer className="kern-main-footer">
        <span>Keyboard-accessible shell</span>
        <span>Responsive breakpoint</span>
        <span>Pack-specific labels gated</span>
      </footer>
    </>
  );
}
