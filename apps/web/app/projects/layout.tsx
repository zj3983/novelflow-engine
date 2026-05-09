import type { ReactNode } from "react";

import { WorkspaceShell } from "../../components/ws/WorkspaceShell";

export default function ProjectsRootLayout({ children }: { children: ReactNode }) {
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
