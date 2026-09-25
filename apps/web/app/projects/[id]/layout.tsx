import type { ReactNode } from "react";

import { ProjectWorkspaceProvider } from "../../../components/ws/ProjectWorkspaceProvider";
import { safeDecodeURIComponent } from "../../../lib/routing";

type Props = {
  children: ReactNode;
  params: Promise<{ id: string }>;
};

export default async function ProjectWorkspaceLayout({ children, params }: Props) {
  const { id } = await params;

  return (
    <ProjectWorkspaceProvider projectId={safeDecodeURIComponent(id)}>
      {children}
    </ProjectWorkspaceProvider>
  );
}
