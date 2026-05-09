"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { fetchProject, fetchStory, type ProjectResponse, type StoryResponse } from "../../lib/api";

const LAST_PROJECT_STORAGE_KEY = "novel-autogrowth.last-project-id";

type ProjectWorkspaceContextValue = {
  projectId: string;
  encodedProjectId: string;
  project: ProjectResponse | null;
  story: StoryResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
};

const ProjectWorkspaceContext = createContext<ProjectWorkspaceContextValue | null>(null);

type ProjectWorkspaceProviderProps = {
  projectId: string;
  children: ReactNode;
};

export function ProjectWorkspaceProvider({ projectId, children }: ProjectWorkspaceProviderProps) {
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [story, setStory] = useState<StoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    try {
      window.localStorage.setItem(LAST_PROJECT_STORAGE_KEY, projectId);
    } catch {
      // localStorage can be unavailable in restricted browser contexts.
    }
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setProject(null);
    setStory(null);

    fetchProject(projectId)
      .then(async (proj) => {
        if (cancelled) return;
        setProject(proj);
        if (proj.active_story_id) {
          const nextStory = await fetchStory(proj.active_story_id);
          if (!cancelled) setStory(nextStory);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, version]);

  const value = useMemo<ProjectWorkspaceContextValue>(
    () => ({
      projectId,
      encodedProjectId: encodeURIComponent(projectId),
      project,
      story,
      loading,
      error,
      refresh: () => setVersion((current) => current + 1),
    }),
    [error, loading, project, projectId, story],
  );

  return <ProjectWorkspaceContext.Provider value={value}>{children}</ProjectWorkspaceContext.Provider>;
}

export function useProjectWorkspace() {
  const context = useContext(ProjectWorkspaceContext);
  if (!context) {
    throw new Error("useProjectWorkspace must be used within ProjectWorkspaceProvider");
  }
  return context;
}
