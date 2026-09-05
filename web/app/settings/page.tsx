import { loadPublicEnv } from "@/lib/env";
import { SettingsPanel } from "@/components/settings/SettingsPanel";

export default function SettingsPage() {
  const env = loadPublicEnv();
  return <SettingsPanel apiBaseUrl={env.NEXT_PUBLIC_API_BASE_URL} />;
}
