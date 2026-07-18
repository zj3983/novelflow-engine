"use client";

import { useId, useState } from "react";

import {
  bootstrapBookImport,
  fetchBookLibraryCatalog,
  listBookFolders,
  scanBookImport,
  type BookImportBootstrapResponse,
  type BookImportScanReport,
  type BookLibraryCatalogResponse,
} from "../lib/api";

type BookImportPanelProps = {
  onBootstrapDraft: (draft: BookImportBootstrapResponse["draft"]) => void;
  onCatalogLoaded: (catalog: BookLibraryCatalogResponse | null) => void;
  onLoadWorld: (draft?: BookImportBootstrapResponse["draft"]) => Promise<void>;
};

type RequestState = "idle" | "loading" | "success" | "error";

interface FolderPickerState {
  currentPath: string;
  folders: { name: string; path: string }[];
  drives: { name: string; path: string; is_drive: boolean }[];
}

function humanBool(value: boolean | null): string {
  if (value === null) {
    return "未校验";
  }
  return value ? "是" : "否";
}

function normalizeSourcePathInput(value: string): string {
  let next = value.trim();
  if (!next) {
    return next;
  }

  if ((next.startsWith('"') && next.endsWith('"')) || (next.startsWith("'") && next.endsWith("'"))) {
    next = next.slice(1, -1).trim();
  }

  const lastSegment = next.split(/[\\/]/).at(-1) ?? next;
  const looksLikeFile = /\.[a-z0-9]+$/i.test(lastSegment);
  if (looksLikeFile) {
    const separatorIndex = Math.max(next.lastIndexOf("\\"), next.lastIndexOf("/"));
    if (separatorIndex > 0) {
      next = next.slice(0, separatorIndex);
    }
  }

  return next;
}

export function BookImportPanel({
  onBootstrapDraft,
  onCatalogLoaded,
  onLoadWorld,
}: BookImportPanelProps) {
  const inputId = useId();
  const [sourcePath, setSourcePath] = useState("");
  const [report, setReport] = useState<BookImportScanReport | null>(null);
  const [scanState, setScanState] = useState<RequestState>("idle");
  const [bootstrapState, setBootstrapState] = useState<RequestState>("idle");
  const [directorBrief, setDirectorBrief] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [folderPicker, setFolderPicker] = useState<FolderPickerState | null>(null);
  const isBusy = scanState === "loading" || bootstrapState === "loading";
  const nextStepLabel = report?.can_bootstrap ? "载入并生成世界观" : report ? "补齐缺失文件" : "先校验目录";

  async function loadCatalog(trimmed: string) {
    try {
      const catalog = await fetchBookLibraryCatalog(trimmed);
      onCatalogLoaded(catalog);
    } catch {
      onCatalogLoaded(null);
    }
  }

  async function onScan() {
    const trimmed = normalizeSourcePathInput(sourcePath);
    if (!trimmed) {
      return;
    }

    if (trimmed !== sourcePath) {
      setSourcePath(trimmed);
    }
    setError(null);
    setScanState("loading");
    try {
      const next = await scanBookImport(trimmed);
      setReport(next);
      void loadCatalog(trimmed);
      setScanState("success");
    } catch (scanError) {
      setScanState("error");
      onCatalogLoaded(null);
      setError(scanError instanceof Error ? scanError.message : "目录校验失败");
    }
  }

  async function onOpenFolderPicker() {
    try {
      const result = await listBookFolders(sourcePath || "");
      setFolderPicker({
        currentPath: result.current_path,
        folders: result.folders,
        drives: result.drives,
      });
    } catch (pickerError) {
      setError(pickerError instanceof Error ? pickerError.message : "无法列出文件夹");
    }
  }

  async function onNavigateFolder(folderPath: string) {
    try {
      const result = await listBookFolders(folderPath);
      setFolderPicker({
        currentPath: result.current_path,
        folders: result.folders,
        drives: result.drives,
      });
    } catch (navigateError) {
      setError(navigateError instanceof Error ? navigateError.message : "无法进入文件夹");
    }
  }

  function onSelectFolder(folderPath: string) {
    setSourcePath(folderPath);
    setFolderPicker(null);
  }

  async function bootstrapImport(loadWorld: boolean) {
    const trimmed = normalizeSourcePathInput(sourcePath);
    if (!trimmed || (report && !report.can_bootstrap)) {
      return;
    }

    if (trimmed !== sourcePath) {
      setSourcePath(trimmed);
    }
    setError(null);
    setBootstrapState("loading");
    try {
      const response = await bootstrapBookImport(trimmed);
      setReport(response.report);
      setDirectorBrief(response.draft.summary ?? "");
      onBootstrapDraft(response.draft);
      void loadCatalog(trimmed);
      if (loadWorld) {
        await onLoadWorld(response.draft);
      }
      setBootstrapState("success");
    } catch (bootstrapError) {
      setBootstrapState("error");
      setError(
        bootstrapError instanceof Error
          ? bootstrapError.message
          : loadWorld
            ? "导入并生成世界观失败"
            : "导入失败",
      );
    }
  }

  const exists = report ? report.exists : null;
  const canBootstrap = report ? report.can_bootstrap : null;

  return (
    <section className="book-import">
      <p className="book-import__title">导入书籍目录</p>

      <div className="field">
        <label htmlFor={inputId}>本地目录路径</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            id={inputId}
            className="text-input"
            style={{ flex: 1 }}
            value={sourcePath}
            onChange={(event) => {
              setSourcePath(event.target.value);
              setReport(null);
              setDirectorBrief("");
              setError(null);
              setScanState("idle");
              setBootstrapState("idle");
              onCatalogLoaded(null);
            }}
            placeholder="例如：D:/novels/demo/story"
          />
          <button className="btn btn--ghost" type="button" onClick={() => void onOpenFolderPicker()}>
            浏览...
          </button>
        </div>
      </div>

      <div className="book-import__actions">
        <button className="btn btn--ghost" type="button" onClick={() => void onScan()} disabled={isBusy}>
          校验目录
        </button>
        <button
          className="btn btn--ghost"
          type="button"
          onClick={() => void bootstrapImport(true)}
          disabled={isBusy || !sourcePath.trim() || (report ? !report.can_bootstrap : false)}
        >
          载入并生成世界观
        </button>
      </div>

      <div className="book-import__report" aria-label="书籍导入报告">
        <p className="hint">路径状态：{sourcePath.trim() ? "已填写" : "未填写"}</p>
        <p className="hint">目录存在：{humanBool(exists)}</p>
        <p className="hint">可载入：{humanBool(canBootstrap)}</p>
        {report ? <p className="hint">已校验目录：{report.source_path}</p> : null}

        {report ? (
          <>
            <p className="hint">
              必需文件：已存在 {report.present_files.length}，缺少 {report.missing_required_files.length}
            </p>

            {report.missing_required_files.length ? (
              <>
                <p className="hint">缺少的必需文件：</p>
                <div className="book-import__files">
                  {report.missing_required_files.map((name) => (
                    <span key={`missing-${name}`} className="book-import__file book-import__file--missing">
                      {name}
                    </span>
                  ))}
                </div>
              </>
            ) : null}

            {report.present_files.length ? (
              <>
                <p className="hint">已发现的文件：</p>
                <div className="book-import__files">
                  {report.present_files.map((name) => (
                    <span key={`present-${name}`} className="book-import__file">
                      {name}
                    </span>
                  ))}
                </div>
              </>
            ) : null}

            {directorBrief ? (
              <div className="book-import__pre-read" aria-label="导演预读">
                <p className="hint">导演预读：</p>
                <pre className="book-library-browser__preview-text">{directorBrief}</pre>
              </div>
            ) : null}

            {report.warnings.length ? <p className="hint">提示：{report.warnings.join("；")}</p> : null}
          </>
        ) : (
          <p className="hint">还没有校验目录。</p>
        )}

        {scanState === "loading" ? <p className="hint">正在校验目录...</p> : null}
        {bootstrapState === "loading" ? <p className="hint">正在载入并生成世界观...</p> : null}
        {report && !report.can_bootstrap ? (
          <p className="hint">当前目录还不能直接用于继续写作，请先补齐缺失的必需文件。</p>
        ) : null}
        {report || bootstrapState === "success" ? (
          <div className="book-import__next-step">
            <p className="hint">
              {bootstrapState === "success" ? "已载入并生成世界观，可以在主工作区确认设定后开始第一章。" : `下一步：${nextStepLabel}`}
            </p>
          </div>
        ) : null}
        {error ? <p className="hint">错误：{error}</p> : null}
      </div>

      {folderPicker ? (
        <div
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0,0,0,0.45)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => setFolderPicker(null)}
        >
          <div
            style={{
              backgroundColor: "#fffaf0",
              borderRadius: 12,
              padding: 24,
              minWidth: 400,
              maxWidth: 600,
              maxHeight: "80vh",
              display: "flex",
              flexDirection: "column",
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h3 style={{ margin: 0 }}>选择目录</h3>
              <button
                onClick={() => setFolderPicker(null)}
                style={{
                  background: "none",
                  border: "none",
                  color: "#888",
                  fontSize: 20,
                  cursor: "pointer",
                }}
              >
                ×
              </button>
            </div>
            <div
              style={{
                padding: "8px 12px",
                backgroundColor: "#f6f1e6",
                borderRadius: 6,
                marginBottom: 12,
                color: "#444",
                fontSize: 13,
              }}
            >
              {folderPicker.currentPath || "选择可访问的根目录"}
            </div>
            <div
              style={{
                overflowY: "auto",
                flex: 1,
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              {folderPicker.drives.map((drive) => (
                <button
                  key={drive.path}
                  onClick={() => void onNavigateFolder(drive.path)}
                  style={{
                    padding: "10px 16px",
                    backgroundColor: "#fff",
                    border: "1px solid #ddd",
                    borderRadius: 6,
                    color: "#111",
                    cursor: "pointer",
                    textAlign: "left",
                    fontSize: 14,
                  }}
                >
                  目录 {drive.name}
                </button>
              ))}
              {folderPicker.folders.map((folder) => (
                <div key={folder.path} style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={() => void onNavigateFolder(folder.path)}
                    style={{
                      flex: 1,
                      padding: "10px 16px",
                      backgroundColor: "#fff",
                      border: "1px solid #ddd",
                      borderRadius: 6,
                      color: "#111",
                      cursor: "pointer",
                      textAlign: "left",
                      fontSize: 14,
                    }}
                  >
                    文件夹 {folder.name}
                  </button>
                  <button
                    onClick={() => onSelectFolder(folder.path)}
                    style={{
                      padding: "10px 16px",
                      backgroundColor: "#b64b32",
                      border: "none",
                      borderRadius: 6,
                      color: "#fff",
                      cursor: "pointer",
                      fontSize: 13,
                    }}
                  >
                    选择
                  </button>
                </div>
              ))}
              {folderPicker.drives.length === 0 && folderPicker.folders.length === 0 ? (
                <p style={{ color: "#666", textAlign: "center", padding: 20 }}>空文件夹</p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
