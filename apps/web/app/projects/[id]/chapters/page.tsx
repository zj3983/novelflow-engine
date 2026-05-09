"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";

export default function ProjectChaptersPage() {
  const router = useRouter();
  const { encodedProjectId } = useProjectWorkspace();

  useEffect(() => {
    router.replace(`/projects/${encodedProjectId}/write`);
  }, [encodedProjectId, router]);

  return null;
}
