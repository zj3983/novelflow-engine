type ChapterDirection = {
  id: string;
};

export function resolveChapterDirectionId(
  currentId: string,
  options: readonly ChapterDirection[] | undefined,
  recommendedId: string | undefined,
): string {
  const safeOptions = Array.isArray(options) ? options : [];
  if (currentId && safeOptions.some((option) => option.id === currentId)) {
    return currentId;
  }
  if (recommendedId && safeOptions.some((option) => option.id === recommendedId)) {
    return recommendedId;
  }
  return safeOptions[0]?.id ?? "";
}
