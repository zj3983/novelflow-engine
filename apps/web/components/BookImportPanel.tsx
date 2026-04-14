"use client";

import { useId, useState } from "react";

import {
  bootstrapBookImport,
  fetchBookLibraryCatalog,
  scanBookImport,
  type BookImportBootstrapResponse,
  type BookImportScanReport,
  type BookLibraryCatalogResponse,
} from "../lib/api";

type BookImportPanelProps = {
  onBootstrapDraft: (draft: BookImportBootstrapResponse["draft"]) => void;
  onCatalogLoaded: (catalog: BookLibraryCatalogResponse | null) => void;
  onStartGeneration: (draft?: BookImportBootstrapResponse["draft"]) => Promise<void>;
};

type RequestState = "idle" | "loading" | "success" | "error";

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

  if (
    (next.startsWith('"') && next.endsWith('"')) ||
    (next.startsWith("'") && next.endsWith("'"))
  ) {
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
  onStartGeneration,
}: BookImportPanelProps) {
  const inputId = useId();
  const [sourcePath, setSourcePath] = useState("");
  const [report, setReport] = useState<BookImportScanReport | null>(null);
  const [scanState, setScanState] = useState<RequestState>("idle");
  const [bootstrapState, setBootstrapState] = useState<RequestState>("idle");
  const [directorBrief, setDirectorBrief] = useState("");
  const [error, setError] = useState<string | null>(null);
  const isBusy = scanState === "loading" || bootstrapState === "loading";

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
    } catch (e) {
      setScanState("error");
      onCatalogLoaded(null);
      setError(e instanceof Error ? e.message : "目录校验失败");
    }
  }

  async function onBootstrap() {
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
      setBootstrapState("success");
    } catch (e) {
      setBootstrapState("error");
      setError(e instanceof Error ? e.message : "载入失败");
    }
  }

  async function onBootstrapAndStart() {
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
      await onStartGeneration(response.draft);
      setBootstrapState("success");
    } catch (e) {
      setBootstrapState("error");
      setError(e instanceof Error ? e.message : "载入并开始失败");
    }
  }

  const exists = report ? report.exists : null;
  const canBootstrap = report ? report.can_bootstrap : null;

  return (
    <section className="book-import">
      <p className="book-import__title">导入书籍目录</p>

      <div className="field">
        <label htmlFor={inputId}>本地目录路径</label>
        <input
          id={inputId}
          className="text-input"
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
      </div>

      <div className="book-import__actions">
        <button className="btn btn--ghost" type="button" onClick={() => void onScan()} disabled={isBusy}>
          校验目录
        </button>
        <button
          className="btn btn--ghost"
          type="button"
          onClick={() => void onBootstrap()}
          disabled={isBusy || !sourcePath.trim() || (report ? !report.can_bootstrap : false)}
        >
          载入到工作台
        </button>
        <button
          className="btn"
          type="button"
          onClick={() => void onBootstrapAndStart()}
          disabled={isBusy || !sourcePath.trim() || (report ? !report.can_bootstrap : false)}
        >
          载入并开始
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
              必需文件覆盖：已存在 {report.present_files.length}，缺少 {report.missing_required_files.length}
            </p>

            {report.missing_required_files.length ? (
              <>
                <p className="hint">缺少必需文件：</p>
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
                <p className="hint">已发现文件：</p>
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
        {bootstrapState === "loading" ? <p className="hint">正在载入到工作台...</p> : null}
        {report && !report.can_bootstrap ? (
          <p className="hint">当前目录还不能直接用于继续写作，请先补全缺失的必需文件。</p>
        ) : null}
        {error ? <p className="hint">错误：{error}</p> : null}
      </div>
    </section>
  );
}
