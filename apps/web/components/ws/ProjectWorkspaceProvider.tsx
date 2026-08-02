"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  fetchFileStoryOverview,
  fetchProject,
  fetchStory,
  type ChapterIndexEntry,
  type FileStoryOverview,
  type ProjectResponse,
  type StoryResponse,
} from "../../lib/api";

const LAST_PROJECT_STORAGE_KEY = "novel-autogrowth.last-project-id";

export type WorkspaceStory = StoryResponse | (FileStoryOverview & { history?: never });

type ProjectWorkspaceContextValue = {
  projectId: string;
  encodedProjectId: string;
  project: ProjectResponse | null;
  story: WorkspaceStory | null;
  chapterIndex: ChapterIndexEntry[];
  loading: boolean;
  error: string | null;
  refreshVersion: number;
  refresh: (options?: { invalidateChapter?: boolean }) => Promise<void>;
};

const ProjectWorkspaceContext = createContext<ProjectWorkspaceContextValue | null>(null);

type ProjectWorkspaceProviderProps = {
  projectId: string;
  children: ReactNode;
};

type ProjectWorkspaceViewInput = {
  hasCurrentProject: boolean;
  project: ProjectResponse | null;
  story: WorkspaceStory | null;
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

export function normalizeStoryChapterIndex(story: StoryResponse | null): ChapterIndexEntry[] {
  return (story?.history ?? []).map((chapter) => ({
    chapter_number: chapter.chapter_number,
    chapter_title: chapter.chapter_title || `第${chapter.chapter_number}章`,
    body_chars: (chapter.body || "").replace(/\s+/g, "").length,
    summary: chapter.chapter_summary?.summary || "",
    next_focus: chapter.next_outline || chapter.chapter_intent?.next_focus || "",
    has_quality_report: Boolean(chapter.quality_report),
    has_simulation: Boolean(
      chapter.simulation_status ||
        chapter.simulation_plan ||
        chapter.event_plan ||
        chapter.chapter_intent ||
        chapter.character_moves?.length ||
        chapter.scene_cards?.length ||
        chapter.world_events?.length ||
        chapter.next_outline,
    ),
  }));
}

export function ProjectWorkspaceProvider({ projectId, children }: ProjectWorkspaceProviderProps) {
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [story, setStory] = useState<WorkspaceStory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [overviewVersion, setOverviewVersion] = useState(0);
  const [chapterRefreshVersion, setChapterRefreshVersion] = useState(0);
  const activeProjectId = useRef(projectId);
  const mountedRef = useRef(true);
  const refreshToken = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

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
          const isFileProject = projectId.startsWith("file:") || proj.storage_source === "file";
          const nextStory = isFileProject
            ? await fetchFileStoryOverview(proj.active_story_id)
            : await fetchStory(proj.active_story_id);
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
  }, [overviewVersion, projectId]);

  const refresh = useCallback(async (options?: { invalidateChapter?: boolean }) => {
    const token = ++refreshToken.current;
    const requestedProjectId = activeProjectId.current;
    setError(null);
    if (options?.invalidateChapter !== false) {
      setChapterRefreshVersion((current) => current + 1);
    }
    try {
      const nextProject = await fetchProject(requestedProjectId);
      if (!mountedRef.current || activeProjectId.current !== requestedProjectId || token !== refreshToken.current) return;
      setProject(nextProject);
      if (!nextProject.active_story_id) {
        setStory(null);
        return;
      }
      const isFileProject = requestedProjectId.startsWith("file:") || nextProject.storage_source === "file";
      const nextStory = isFileProject
        ? await fetchFileStoryOverview(nextProject.active_story_id)
        : await fetchStory(nextProject.active_story_id);
      if (mountedRef.current && activeProjectId.current === requestedProjectId && token === refreshToken.current) setStory(nextStory);
    } catch (err) {
      if (!mountedRef.current || activeProjectId.current !== requestedProjectId || token !== refreshToken.current) return;
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    }
  }, []);

  const hasCurrentProject = activeProjectId.current === projectId;
  const currentView = selectProjectWorkspaceView({ hasCurrentProject, project, story, loading, error });
  const chapterIndex = useMemo(() => {
    if (!currentView.story) return [];
    if ("chapters" in currentView.story) return currentView.story.chapters;
    return normalizeStoryChapterIndex(currentView.story);
  }, [currentView.story]);

  const value = useMemo<ProjectWorkspaceContextValue>(
    () => ({
      projectId,
      encodedProjectId: encodeURIComponent(projectId),
      project: currentView.project,
      story: currentView.story,
      chapterIndex,
      loading: currentView.loading,
      error: currentView.error,
      refreshVersion: chapterRefreshVersion,
      refresh,
    }),
    [chapterIndex, chapterRefreshVersion, currentView.error, currentView.loading, currentView.project, currentView.story, projectId, refresh],
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
