import { SettingsPanel } from "@/components/settings/SettingsPanel";

/** Same-origin BFF so kernector_session reaches FastAPI (#447). */
const BFF = "";

export default function SettingsPage() {
  return <SettingsPanel apiBaseUrl={BFF} />;
}
