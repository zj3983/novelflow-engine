"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

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

type ProjectWorkspaceViewInput = {
  hasCurrentProject: boolean;
  project: ProjectResponse | null;
  story: StoryResponse | null;
  loading: boolean;
  error: string | null;
};

export function selectProjectWorkspaceView({
  hasCurrentProject,
  project,
  story,
  loading,
  error,
}: ProjectWorkspaceViewInput) {
  return hasCurrentProject
    ? { project, story, loading, error }
    : { project: null, story: null, loading: true, error: null };
}

export function ProjectWorkspaceProvider({ projectId, children }: ProjectWorkspaceProviderProps) {
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [story, setStory] = useState<StoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const activeProjectId = useRef(projectId);

  useEffect(() => {
    try {
      window.localStorage.setItem(LAST_PROJECT_STORAGE_KEY, projectId);
    } catch {
      // localStorage can be unavailable in restricted browser contexts.
    }
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    const projectChanged = activeProjectId.current !== projectId;
    activeProjectId.current = projectId;
    setLoading(true);
    setError(null);
    if (projectChanged) {
      setProject(null);
      setStory(null);
    }

    fetchProject(projectId)
      .then(async (proj) => {
        if (cancelled) return;
        setProject(proj);
        if (!proj.active_story_id) {
          setStory(null);
          return;
        }
        try {
          const nextStory = await fetchStory(proj.active_story_id);
          if (!cancelled) setStory(nextStory);
        } catch (err) {
          if (cancelled) return;
          setStory(null);
          setError(`故事加载失败：${err instanceof Error ? err.message : String(err)}`);
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

  const hasCurrentProject = activeProjectId.current === projectId;
  const currentView = selectProjectWorkspaceView({ hasCurrentProject, project, story, loading, error });

  const value = useMemo<ProjectWorkspaceContextValue>(
    () => ({
      projectId,
      encodedProjectId: encodeURIComponent(projectId),
      project: currentView.project,
      story: currentView.story,
      loading: currentView.loading,
      error: currentView.error,
      refresh: () => setVersion((current) => current + 1),
    }),
    [currentView.error, currentView.loading, currentView.project, currentView.story, projectId],
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
