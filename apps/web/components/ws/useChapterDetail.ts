"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchFileChapter,
  type ChapterBundle,
  type FileStoryOverview,
  type StoryResponse,
} from "../../lib/api";

function isFileStory(story: StoryResponse | FileStoryOverview | null): story is FileStoryOverview {
  return Boolean(story && "storage_source" in story && story.storage_source === "file");
}

export function useChapterDetail({
  projectId,
  story,
  chapterNumber,
  refreshVersion,
}: {
  projectId: string;
  story: StoryResponse | FileStoryOverview | null;
  chapterNumber: number;
  refreshVersion: number;
}) {
  const [chapter, setChapter] = useState<ChapterBundle | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);
  const requestSequence = useRef(0);

  useEffect(() => {
    const sequence = ++requestSequence.current;
    let cancelled = false;

    if (!story || chapterNumber <= 0) {
      setChapter(null);
      setLoading(false);
      setError(null);
      return () => {
        cancelled = true;
      };
    }

    if (!isFileStory(story)) {
      const history = story.history ?? [];
      setChapter(history.find((item) => item.chapter_number === chapterNumber) ?? history.at(-1) ?? null);
      setLoading(false);
      setError(null);
      return () => {
        cancelled = true;
      };
    }

    setLoading(true);
    setError(null);
    fetchFileChapter(story.story_id || projectId, chapterNumber)
      .then((nextChapter) => {
        if (!cancelled && sequence === requestSequence.current) setChapter(nextChapter);
      })
      .catch((reason) => {
        if (!cancelled && sequence === requestSequence.current) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      })
      .finally(() => {
        if (!cancelled && sequence === requestSequence.current) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [chapterNumber, projectId, refreshVersion, reloadVersion, story]);

  const reload = useCallback(() => setReloadVersion((current) => current + 1), []);
  return { chapter, loading, error, reload };
}
