"use client";

import { useEffect, useRef, useState } from "react";

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
  const requestSequence = useRef(0);
  const fileStory = isFileStory(story);
  const fileStoryId = fileStory ? story.story_id || projectId : "";
  const nonFileHistory = !fileStory && story ? story.history : null;
  const hasStory = story !== null;

  useEffect(() => {
    const sequence = ++requestSequence.current;
    let cancelled = false;

    if (!hasStory || chapterNumber <= 0) {
      setChapter(null);
      setLoading(false);
      setError(null);
      return () => {
        cancelled = true;
      };
    }

    if (!fileStory) {
      const history = nonFileHistory ?? [];
      setChapter(history.find((item) => item.chapter_number === chapterNumber) ?? history.at(-1) ?? null);
      setLoading(false);
      setError(null);
      return () => {
        cancelled = true;
      };
    }

    setLoading(true);
    setError(null);
    fetchFileChapter(fileStoryId, chapterNumber)
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
  }, [chapterNumber, fileStory, fileStoryId, hasStory, nonFileHistory, refreshVersion]);

  return { chapter, loading, error };
}
