import type { ReactNode } from "react";

import { ProjectWorkspaceProvider } from "../../../components/ws/ProjectWorkspaceProvider";
import { safeDecodeURIComponent } from "../../../lib/routing";

type Props = {
  children: ReactNode;
  params: { id: string };
};

export default function ProjectWorkspaceLayout({ children, params }: Props) {
  return (
    <ProjectWorkspaceProvider projectId={safeDecodeURIComponent(params.id)}>
      {children}
    </ProjectWorkspaceProvider>
  );
}
