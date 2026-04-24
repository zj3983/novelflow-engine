"use client";

import type { BookLibraryCatalogResponse, BookLibraryItem } from "../lib/api";

type BookLibraryBrowserProps = {
  catalog: BookLibraryCatalogResponse | null;
  selectedSourceItemId: string | null;
  onSelectSourceItem: (item: BookLibraryItem) => void;
};

function emptyHint(catalog: BookLibraryCatalogResponse | null): string {
  if (!catalog) {
    return "先校验或导入一个书籍目录，浏览器才会显示内容。";
  }
  if (!catalog.can_bootstrap) {
    return "当前目录还不能直接导入，先补齐缺失文件。";
  }
  return "选择任意文件，右侧会显示它的内容预览。";
}

export function BookLibraryBrowser({
  catalog,
  selectedSourceItemId,
  onSelectSourceItem,
}: BookLibraryBrowserProps) {
  const selectedItem =
    catalog?.sections.flatMap((section) => section.items).find((item) => item.item_id === selectedSourceItemId) ?? null;

  return (
    <section className="book-library-browser" aria-label="目录浏览器">
      <div className="book-library-browser__header">
        <p className="book-library-browser__title">目录浏览器</p>
        <p className="hint">{emptyHint(catalog)}</p>
      </div>

      {catalog ? (
        <div className="book-library-browser__sections">
          {catalog.sections.map((section) => (
            <section key={section.section_id} className="book-library-browser__section">
              <p className="character-card__title">{section.title}</p>
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
                      <span className="book-library-browser__item-preview">{item.preview || "暂无预览"}</span>
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
        <p className="hint">还没有导入目录，先从左侧开始导入。</p>
      )}

      {selectedItem ? (
        <section className="book-library-browser__preview" aria-label="文件预览">
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
