import { ConfigPageClient } from "../../components/config/ConfigPageClient";
import { WorkspaceShell } from "../../components/ws/WorkspaceShell";

export default function ConfigPage() {
  return (
    <WorkspaceShell>
      <ConfigPageClient />
    </WorkspaceShell>
  );
}
