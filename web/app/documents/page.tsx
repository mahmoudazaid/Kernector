import { DocumentsPanel } from "@/components/documents/DocumentsPanel";

/** Same-origin BFF so kernector_session reaches FastAPI (#447). */
const BFF = "";

export default function DocumentsPage() {
  return <DocumentsPanel apiBaseUrl={BFF} />;
}
