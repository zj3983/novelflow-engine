"use client";

import type { BookLibraryCatalogResponse, BookLibraryItem, ChapterBundle } from "../lib/api";

type BookLibraryBrowserProps = {
  catalog: BookLibraryCatalogResponse | null;
  history: ChapterBundle[];
  selectedSourceItemId: string | null;
  selectedHistoryChapter: number | null;
  onSelectSourceItem: (item: BookLibraryItem) => void;
  onSelectHistoryChapter: (chapterNumber: number) => void;
};

function sectionHeading(sectionId: string): string {
  if (sectionId === "source_docs") {
    return "源书目录";
  }
  if (sectionId === "source_state") {
    return "状态文件";
  }
  if (sectionId === "runtime_chapters") {
    return "运行章节";
  }
  return sectionId;
}

export function BookLibraryBrowser({
  catalog,
  history,
  selectedSourceItemId,
  selectedHistoryChapter,
  onSelectSourceItem,
  onSelectHistoryChapter,
}: BookLibraryBrowserProps) {
  const selectedItem =
    catalog?.sections.flatMap((section) => section.items).find((item) => item.item_id === selectedSourceItemId) ??
    null;

  return (
    <section className="book-library-browser">
      <p className="book-import__title">目录浏览器</p>
      {catalog ? (
        <div className="book-library-browser__sections">
          {catalog.sections.map((section) => (
            <section key={section.section_id} className="book-library-browser__section">
              <p className="character-card__title">{sectionHeading(section.section_id)}</p>
              <div className="book-library-browser__items">
                {section.items.length ? (
                  section.items.map((item) => (
                    <button
                      key={item.item_id}
                      type="button"
                      className={`book-library-browser__item${
                        item.item_id === selectedSourceItemId ? " book-library-browser__item--active" : ""
                      }`}
                      onClick={() => onSelectSourceItem(item)}
                    >
                      <span className="book-library-browser__item-title">{item.title}</span>
                      <span className="book-library-browser__item-meta">{item.filename}</span>
                      <span className="book-library-browser__item-preview">{item.preview || "无预览"}</span>
                    </button>
                  ))
                ) : (
                  <p className="hint">暂无条目</p>
                )}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <p className="hint">先校验或载入一个书籍目录，浏览器才会显示内容。</p>
      )}

      <section className="book-library-browser__section">
        <p className="character-card__title">工作台历史</p>
        {history.length ? (
          <div className="book-library-browser__items">
            {history.map((chapter) => (
              <button
                key={chapter.chapter_number}
                type="button"
                className={`book-library-browser__item${
                  chapter.chapter_number === selectedHistoryChapter ? " book-library-browser__item--active" : ""
                }`}
                onClick={() => onSelectHistoryChapter(chapter.chapter_number)}
              >
                <span className="book-library-browser__item-title">第 {chapter.chapter_number} 章</span>
                <span className="book-library-browser__item-meta">
                  chapter-{chapter.chapter_number.toString().padStart(4, "0")}
                </span>
                <span className="book-library-browser__item-preview">
                  {chapter.chapter_summary?.summary || chapter.body.slice(0, 80)}
                </span>
              </button>
            ))}
          </div>
        ) : (
          <p className="hint">当前工作台还没有生成历史章节。</p>
        )}
      </section>

      {selectedItem ? (
        <section className="book-library-browser__preview" aria-label="目录预览">
          <p className="character-card__title">预览内容</p>
          <p className="hint">文件：{selectedItem.filename}</p>
          <p className="hint">类型：{selectedItem.kind}</p>
          {selectedItem.parsed_characters?.length ? (
            <p className="hint">角色：{selectedItem.parsed_characters.join("、")}</p>
          ) : null}
          <pre className="book-library-browser__preview-text">{selectedItem.content || selectedItem.preview}</pre>
        </section>
      ) : null}
    </section>
  );
}
