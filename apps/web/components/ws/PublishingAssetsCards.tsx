"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import {
  coverImageUrl,
  generateCover,
  generateCoverFromPrompt,
  generateSynopsis,
  renderCoverTitle,
  updateCoverPrompt,
  updateSynopsis,
  PublishingApiError,
  type CoverAsset,
  type PublishingAssets,
  type SynopsisAsset,
} from "../../lib/api";
import styles from "./PublishingAssetsCards.module.css";

export type PublishingAssetsCardsProps = {
  projectId: string;
  title: string;
  assets: PublishingAssets;
  onChanged: () => void | Promise<void>;
};

export type CardRequestState = "idle" | "generating" | "saving" | "error";
type SynopsisRetryOperation = "generate" | "save" | null;
type CoverRetryOperation = "generate" | "image" | "save" | "render" | null;

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function assetSignature(value: unknown) {
  return JSON.stringify(value);
}

function parseTags(value: string) {
  const seen = new Set<string>();
  return value.split(/[,，、;；\n]/).map((tag) => tag.trim()).filter((tag) => {
    const key = tag.toLocaleLowerCase();
    if (!tag || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

type SynopsisValidation = { tags: string[] } | { error: string; field: "tags" | "body" };

function synopsisValidation(tagsText: string, body: string): SynopsisValidation {
  const tags = parseTags(tagsText);
  if (tags.length < 4 || tags.length > 8) return { error: "标签需保留 4 至 8 个", field: "tags" as const };
  if (tags.some((tag) => tag.length > 32)) return { error: "每个标签不能超过 32 个字符", field: "tags" as const };
  if (!body.trim()) return { error: "简介正文不能为空", field: "body" as const };
  if (body.length > 2000) return { error: "简介正文不能超过 2000 个字符", field: "body" as const };
  return { tags };
}

async function copyText(value: string) {
  if (!navigator.clipboard?.writeText) throw new Error("当前浏览器不支持复制");
  await navigator.clipboard.writeText(value);
}

export function PublishingAssetsCards({ projectId, title, assets, onChanged }: PublishingAssetsCardsProps) {
  const synopsisServerSignature = useRef(assetSignature(assets.synopsis));
  const coverServerSignature = useRef(assetSignature(assets.cover));
  const mounted = useRef(true);
  const currentProjectId = useRef(projectId);
  const previousProjectId = useRef(projectId);
  const synopsisToken = useRef(0);
  const coverToken = useRef(0);
  currentProjectId.current = projectId;
  const tagsInput = useRef<HTMLInputElement>(null);
  const bodyInput = useRef<HTMLTextAreaElement>(null);
  const synopsisGuidanceInput = useRef<HTMLTextAreaElement>(null);
  const coverGuidanceInput = useRef<HTMLTextAreaElement>(null);
  const [synopsis, setSynopsis] = useState<SynopsisAsset | null>(assets.synopsis);
  const [cover, setCover] = useState<CoverAsset | null>(assets.cover);
  const [synopsisState, setSynopsisState] = useState<CardRequestState>("idle");
  const [coverState, setCoverState] = useState<CardRequestState>("idle");
  const [synopsisError, setSynopsisError] = useState("");
  const [coverError, setCoverError] = useState("");
  const [synopsisGuidance, setSynopsisGuidance] = useState("");
  const [coverGuidance, setCoverGuidance] = useState("");
  const [editingSynopsis, setEditingSynopsis] = useState(false);
  const [tagsDraft, setTagsDraft] = useState("");
  const [bodyDraft, setBodyDraft] = useState("");
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [promptDraft, setPromptDraft] = useState("");
  const [synopsisFeedback, setSynopsisFeedback] = useState("");
  const [coverFeedback, setCoverFeedback] = useState("");
  const [refreshWarning, setRefreshWarning] = useState("");
  const [imageFailedUrl, setImageFailedUrl] = useState("");
  const synopsisInFlight = useRef(false);
  const coverInFlight = useRef(false);
  const [synopsisRetry, setSynopsisRetry] = useState<SynopsisRetryOperation>(null);
  const [coverRetry, setCoverRetry] = useState<CoverRetryOperation>(null);
  const [promptReady, setPromptReady] = useState(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (previousProjectId.current === projectId) return;
    previousProjectId.current = projectId;
    synopsisToken.current += 1;
    coverToken.current += 1;
    synopsisServerSignature.current = assetSignature(assets.synopsis);
    coverServerSignature.current = assetSignature(assets.cover);
    setSynopsis(assets.synopsis);
    setCover(assets.cover);
    setPromptReady(false);
    setSynopsisState("idle");
    setCoverState("idle");
    setSynopsisError("");
    setCoverError("");
    setSynopsisGuidance("");
    setCoverGuidance("");
    setEditingSynopsis(false);
    setEditingPrompt(false);
    setTagsDraft("");
    setBodyDraft("");
    setPromptDraft("");
    setSynopsisFeedback("");
    setCoverFeedback("");
    setSynopsisRetry(null);
    setCoverRetry(null);
  }, [assets, projectId]);

  useEffect(() => {
    const nextSynopsisSignature = assetSignature(assets.synopsis);
    if (nextSynopsisSignature !== synopsisServerSignature.current) {
      synopsisServerSignature.current = nextSynopsisSignature;
      synopsisToken.current += 1;
      setSynopsis(assets.synopsis);
      setSynopsisState("idle");
      setSynopsisError("");
      setSynopsisRetry(null);
    }
    const nextCoverSignature = assetSignature(assets.cover);
    if (nextCoverSignature !== coverServerSignature.current) {
      coverServerSignature.current = nextCoverSignature;
      coverToken.current += 1;
      setCover(assets.cover);
      setPromptReady(false);
      setCoverState("idle");
      setCoverError("");
      setCoverRetry(null);
    }
  }, [assets]);

  const changed = async () => {
    try {
      await onChanged();
      return "";
    } catch (error) {
      return message(error);
    }
  };

  const generateNewSynopsis = async () => {
    if (synopsisInFlight.current) return;
    if (synopsisGuidance.length > 1000) {
      setSynopsisRetry(null);
      setSynopsisError("生成要求不能超过 1000 个字符");
      setSynopsisState("error");
      synopsisGuidanceInput.current?.focus();
      return;
    }
    const token = ++synopsisToken.current;
    synopsisInFlight.current = true;
    const requestProjectId = projectId;
    setSynopsisRetry("generate");
    setSynopsisState("generating");
    setSynopsisError("");
    setSynopsisFeedback("");
    try {
      const next = await generateSynopsis(projectId, synopsisGuidance);
      if (!mounted.current || currentProjectId.current !== requestProjectId || token !== synopsisToken.current) return;
      setSynopsis(next);
      setEditingSynopsis(false);
      setRefreshWarning(await changed());
      if (mounted.current && currentProjectId.current === requestProjectId && token === synopsisToken.current) {
        setSynopsisState("idle");
        setSynopsisRetry(null);
      }
    } catch (error) {
      if (mounted.current && currentProjectId.current === requestProjectId && token === synopsisToken.current) {
        setSynopsisError(message(error));
        setSynopsisState("error");
      }
    } finally {
      synopsisInFlight.current = false;
    }
  };

  const beginSynopsisEdit = () => {
    setTagsDraft((synopsis?.tags ?? []).join("，"));
    setBodyDraft(synopsis?.body ?? "");
    setSynopsisError("");
    setSynopsisRetry(null);
    setEditingSynopsis(true);
  };

  const saveSynopsis = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (synopsisInFlight.current) return;
    const validation = synopsisValidation(tagsDraft, bodyDraft);
    if ("error" in validation) {
      setSynopsisRetry(null);
      setSynopsisError(validation.error);
      setSynopsisState("error");
      (validation.field === "tags" ? tagsInput.current : bodyInput.current)?.focus();
      return;
    }
    const submitted = { tags: validation.tags, body: bodyDraft.trim() };
    const token = ++synopsisToken.current;
    synopsisInFlight.current = true;
    const requestProjectId = projectId;
    setSynopsisRetry("save");
    setSynopsisState("saving");
    setSynopsisError("");
    try {
      const next = await updateSynopsis(projectId, submitted);
      if (!mounted.current || currentProjectId.current !== requestProjectId || token !== synopsisToken.current) return;
      setSynopsis(next);
      setEditingSynopsis(false);
      setRefreshWarning(await changed());
      if (mounted.current && currentProjectId.current === requestProjectId && token === synopsisToken.current) {
        setSynopsisState("idle");
        setSynopsisRetry(null);
      }
    } catch (error) {
      if (mounted.current && currentProjectId.current === requestProjectId && token === synopsisToken.current) {
        setSynopsisError(message(error));
        setSynopsisState("error");
      }
    } finally {
      synopsisInFlight.current = false;
    }
  };

  const generateNewCover = async () => {
    if (coverInFlight.current) return;
    if (coverGuidance.length > 1000) {
      setCoverRetry(null);
      setCoverError("生成要求不能超过 1000 个字符");
      setCoverState("error");
      coverGuidanceInput.current?.focus();
      return;
    }
    const token = ++coverToken.current;
    coverInFlight.current = true;
    const requestProjectId = projectId;
    setCoverRetry("generate");
    setCoverState("generating");
    setCoverError("");
    setCoverFeedback("");
    try {
      const result = await generateCover(projectId, coverGuidance);
      if (!mounted.current || currentProjectId.current !== requestProjectId || token !== coverToken.current) return;
      if (result.cover) setCover(result.cover);
      setPromptReady(result.status === "prompt_ready");
      setEditingPrompt(false);
      const refreshError = await changed();
      if (mounted.current && currentProjectId.current === requestProjectId && token === coverToken.current) {
        setCoverState("idle");
        setCoverRetry(null);
        setRefreshWarning(refreshError);
      }
    } catch (error) {
      if (mounted.current && currentProjectId.current === requestProjectId && token === coverToken.current) {
        if (error instanceof PublishingApiError && error.promptSaved && error.cover) {
          setCover(error.cover);
        }
        setCoverError(message(error));
        setCoverState("error");
        setCoverRetry(error instanceof PublishingApiError && error.phase === "image" && error.promptSaved ? "image" : "generate");
        void changed().then((refreshError) => { if (mounted.current) setRefreshWarning(refreshError); });
      }
    } finally {
      coverInFlight.current = false;
    }
  };

  const generateCurrentPromptImage = async () => {
    if (coverInFlight.current) return;
    const token = ++coverToken.current;
    const requestProjectId = projectId;
    coverInFlight.current = true;
    setCoverRetry("image");
    setCoverState("generating");
    setCoverError("");
    try {
      const result = await generateCoverFromPrompt(projectId);
      if (!mounted.current || currentProjectId.current !== requestProjectId || token !== coverToken.current) return;
      if (result.cover) setCover(result.cover);
      setPromptReady(result.status === "prompt_ready");
      const refreshError = await changed();
      if (mounted.current && currentProjectId.current === requestProjectId && token === coverToken.current) {
        setCoverState("idle");
        setCoverRetry(null);
        setRefreshWarning(refreshError);
      }
    } catch (error) {
      if (mounted.current && currentProjectId.current === requestProjectId && token === coverToken.current) {
        setCoverError(message(error));
        setCoverState("error");
        setCoverRetry("image");
        void changed().then((refreshError) => { if (mounted.current) setRefreshWarning(refreshError); });
      }
    } finally {
      coverInFlight.current = false;
    }
  };

  const savePrompt = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const prompt = promptDraft.trim();
    if (!prompt) {
      setCoverRetry(null);
      setCoverError("封面提示词不能为空");
      setCoverState("error");
      return;
    }
    if (prompt.length > 2000) {
      setCoverRetry(null);
      setCoverError("封面提示词不能超过 2000 个字符");
      setCoverState("error");
      return;
    }
    const token = ++coverToken.current;
    const requestProjectId = projectId;
    setCoverRetry("save");
    setCoverState("saving");
    setCoverError("");
    try {
      const next = await updateCoverPrompt(projectId, prompt);
      if (!mounted.current || currentProjectId.current !== requestProjectId || token !== coverToken.current) return;
      setCover(next);
      setPromptReady(false);
      setEditingPrompt(false);
      setRefreshWarning(await changed());
      if (mounted.current && currentProjectId.current === requestProjectId && token === coverToken.current) {
        setCoverState("idle");
        setCoverRetry(null);
      }
    } catch (error) {
      if (mounted.current && currentProjectId.current === requestProjectId && token === coverToken.current) {
        setCoverError(message(error));
        setCoverState("error");
      }
    }
  };

  const rerenderTitle = async () => {
    const token = ++coverToken.current;
    const requestProjectId = projectId;
    setCoverRetry("render");
    setCoverState("saving");
    setCoverError("");
    try {
      const next = await renderCoverTitle(projectId);
      if (!mounted.current || currentProjectId.current !== requestProjectId || token !== coverToken.current) return;
      setCover(next);
      setPromptReady(false);
      setRefreshWarning(await changed());
      if (mounted.current && currentProjectId.current === requestProjectId && token === coverToken.current) {
        setCoverState("idle");
        setCoverRetry(null);
      }
    } catch (error) {
      if (mounted.current && currentProjectId.current === requestProjectId && token === coverToken.current) {
        const detail = message(error);
        setCoverError(detail.includes("publishing_asset_stale_base") ? "底图已更新，请刷新后重试排版。" : detail);
        setCoverState("error");
      }
    }
  };

  const retrySynopsis = () => {
    if (synopsisRetry === "generate") void generateNewSynopsis();
    if (synopsisRetry === "save") void saveSynopsis({ preventDefault() {} } as React.FormEvent<HTMLFormElement>);
  };

  const retryCover = () => {
    if (coverRetry === "generate") void generateNewCover();
    if (coverRetry === "image") void generateCurrentPromptImage();
    if (coverRetry === "save") void savePrompt({ preventDefault() {} } as React.FormEvent<HTMLFormElement>);
    if (coverRetry === "render") void rerenderTitle();
  };

  const coverUrl = cover?.image_version ? coverImageUrl(projectId, cover.image_version) : "";
  const hasBase = Boolean(cover?.base_image_version);
  const hasRendered = Boolean(cover?.image_version) && imageFailedUrl !== coverUrl;
  const knownTitleMismatch = Boolean(cover?.rendered_title?.trim() && cover.rendered_title !== title);
  const provenanceMismatch = Boolean(cover?.base_image_version && cover?.rendered_from_base_version && cover.base_image_version !== cover.rendered_from_base_version);
  const needsRendering = Boolean(hasBase && (!hasRendered || knownTitleMismatch || provenanceMismatch));
  const synopsisBusy = synopsisState === "generating" || synopsisState === "saving";
  const coverBusy = coverState === "generating" || coverState === "saving";

  return (
    <section className={styles.grid} aria-label="作品包装">
      <article className={`${styles.card} ${styles.synopsisCard}`} aria-labelledby="synopsis-title" aria-busy={synopsisBusy}>
        <header className={styles.header}>
          <div>
            <p className={styles.kicker}>书稿简介</p>
            <h2 id="synopsis-title">简介</h2>
          </div>
          {synopsis && !editingSynopsis ? <button type="button" className="ws-button" onClick={beginSynopsisEdit} disabled={synopsisBusy}>编辑简介</button> : null}
        </header>
        <div className={styles.manuscript}>
          {synopsis && !editingSynopsis ? (
            <>
              <div className={styles.chips}>{synopsis.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
              <p className={styles.body}>{synopsis.body}</p>
              <div className={styles.meta}>
                <span>{synopsis.updated_at ? `更新于 ${synopsis.updated_at}` : "已保存"}</span>
                <button type="button" className={styles.textButton} onClick={() => void copyText(`${synopsis.tags.join("，")}\n${synopsis.body}`).then(() => setSynopsisFeedback("简介已复制")).catch(() => setSynopsisFeedback("复制简介失败"))}>复制简介</button>
              </div>
            </>
          ) : editingSynopsis ? (
            <form onSubmit={saveSynopsis} className={styles.editForm}>
              <label>标签<input ref={tagsInput} aria-label="标签" value={tagsDraft} onChange={(event) => setTagsDraft(event.target.value)} disabled={synopsisBusy} /></label>
              <small>用逗号或顿号分隔，保留 4–8 个标签。</small>
              <label>简介正文<textarea ref={bodyInput} aria-label="简介正文" rows={7} value={bodyDraft} onChange={(event) => setBodyDraft(event.target.value)} disabled={synopsisBusy} /></label>
              <div className={styles.actions}><button className="ws-button ws-button--primary" type="submit" disabled={synopsisBusy}>{synopsisState === "saving" ? "保存中…" : "保存简介"}</button><button className="ws-button" type="button" onClick={() => { setEditingSynopsis(false); setSynopsisError(""); setSynopsisState("idle"); setSynopsisRetry(null); }} disabled={synopsisBusy}>取消</button></div>
            </form>
          ) : <p className={styles.empty}>还没有简介。生成后可在这里人工修订。</p>}
        </div>
        {!editingSynopsis ? <label className={styles.guidance}>简介生成要求（可选）<textarea ref={synopsisGuidanceInput} rows={2} value={synopsisGuidance} onChange={(event) => setSynopsisGuidance(event.target.value)} disabled={synopsisBusy} maxLength={1001} /></label> : null}
        {!editingSynopsis ? <button type="button" className="ws-button ws-button--primary" onClick={() => void generateNewSynopsis()} disabled={synopsisBusy}>{synopsisState === "generating" ? "生成中…" : synopsis ? "重新生成" : "生成简介"}</button> : null}
        <div className={styles.feedback} aria-live="polite">{synopsisError ? <><span className={styles.error}>{synopsisError}</span>{synopsisRetry ? <button type="button" className={styles.textButton} onClick={retrySynopsis}>重试</button> : null}</> : synopsisFeedback}</div>
      </article>

      <article className={`${styles.card} ${styles.coverCard}`} aria-labelledby="cover-title" aria-busy={coverBusy}>
        <header className={styles.header}>
          <div><p className={styles.kicker}>封面校样</p><h2 id="cover-title">封面</h2></div>
          {cover?.prompt && !editingPrompt ? <button type="button" className="ws-button" onClick={() => { setPromptDraft(cover.prompt ?? ""); setEditingPrompt(true); setCoverError(""); setCoverRetry(null); }} disabled={coverBusy}>编辑提示词</button> : null}
        </header>
        <div className={styles.coverDesk}>
          <div className={styles.coverFrame}>
            {hasRendered ? <img src={coverUrl} alt={`${title}封面`} onError={() => setImageFailedUrl(coverUrl)} /> : <span>{imageFailedUrl ? "封面图片无法加载" : "封面校样"}</span>}
          </div>
          <div className={styles.coverNotes}>
            {cover?.prompt && !editingPrompt ? <><p className={styles.prompt}>{cover.prompt}</p><button type="button" className={styles.textButton} onClick={() => void copyText(cover.prompt ?? "").then(() => setCoverFeedback("提示词已复制")).catch(() => setCoverFeedback("复制提示词失败"))}>复制提示词</button></> : null}
            {editingPrompt ? <form onSubmit={savePrompt} className={styles.editForm}><label>封面提示词<textarea aria-label="封面提示词" aria-invalid={Boolean(coverError)} aria-describedby="cover-prompt-error" maxLength={2000} rows={6} value={promptDraft} onChange={(event) => setPromptDraft(event.target.value)} disabled={coverBusy} /></label><div className={styles.actions}><button type="submit" className="ws-button ws-button--primary" disabled={coverBusy}>{coverState === "saving" ? "保存中…" : "保存提示词"}</button><button type="button" className="ws-button" disabled={coverBusy} onClick={() => { setEditingPrompt(false); setCoverError(""); setCoverState("idle"); setCoverRetry(null); }}>取消</button></div></form> : null}
            {promptReady ? <><p className={styles.notice}>图像模型尚未配置。<Link href="/config">前往配置</Link></p><button type="button" className="ws-button ws-button--primary" onClick={() => void generateCurrentPromptImage()} disabled={coverBusy}>使用当前提示词生成图片</button></> : null}
            {!promptReady && cover?.prompt && !hasBase && !hasRendered ? <><p className={styles.notice}>提示词已就绪，等待生成图片。</p><button type="button" className="ws-button" onClick={() => void generateCurrentPromptImage()} disabled={coverBusy}>使用当前提示词生成图片</button></> : null}
            {needsRendering ? <div className={styles.renderNotice}><strong>{knownTitleMismatch ? "书名已变化，重新排版" : provenanceMismatch ? "底图已变化，重新排版" : "底图已生成，待排版书名"}</strong><button type="button" className="ws-button" onClick={() => void rerenderTitle()} disabled={coverBusy}>{coverState === "saving" ? "排版中…" : "重新排版"}</button></div> : null}
            {hasRendered ? <a className="ws-button" href={coverImageUrl(projectId, cover?.image_version ?? "", true)} download>下载封面</a> : null}
          </div>
        </div>
        {!editingPrompt ? <><label className={styles.guidance}>封面生成要求（可选）<textarea ref={coverGuidanceInput} rows={2} value={coverGuidance} onChange={(event) => setCoverGuidance(event.target.value)} disabled={coverBusy} maxLength={1001} /></label><button type="button" className="ws-button ws-button--primary" onClick={() => void generateNewCover()} disabled={coverBusy}>{coverState === "generating" ? "生成中…" : hasRendered || cover?.prompt ? "重新生成提示词与封面" : "生成封面"}</button></> : null}
        <div id="cover-prompt-error" className={styles.feedback} aria-live="polite">{coverError ? <><span className={styles.error}>{coverError}</span>{coverRetry ? <button type="button" className={styles.textButton} onClick={retryCover}>重试</button> : null}</> : coverFeedback}</div>
        {refreshWarning ? <div className={styles.feedback} aria-live="polite">项目刷新失败：{refreshWarning}<button type="button" className={styles.textButton} onClick={() => void changed().then(setRefreshWarning)}>刷新项目</button></div> : null}
      </article>
    </section>
  );
}
