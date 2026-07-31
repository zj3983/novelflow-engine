"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import {
  coverImageUrl,
  generateCover,
  generateSynopsis,
  renderCoverTitle,
  updateCoverPrompt,
  updateSynopsis,
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

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function assetSignature(assets: PublishingAssets) {
  return JSON.stringify(assets);
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
  const initialSignature = assetSignature(assets);
  const serverSignature = useRef(initialSignature);
  const mounted = useRef(true);
  const synopsisToken = useRef(0);
  const coverToken = useRef(0);
  const synopsisRetry = useRef<(() => void) | null>(null);
  const coverRetry = useRef<(() => void) | null>(null);
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
  const [promptReady, setPromptReady] = useState(Boolean(assets.cover?.prompt && !assets.cover.image_version));

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    const nextSignature = assetSignature(assets);
    if (nextSignature === serverSignature.current) return;
    serverSignature.current = nextSignature;
    setSynopsis(assets.synopsis);
    setCover(assets.cover);
    setPromptReady(Boolean(assets.cover?.prompt && !assets.cover.image_version));
  }, [assets]);

  const changed = async () => {
    await onChanged();
  };

  const generateNewSynopsis = async () => {
    if (synopsisGuidance.length > 1000) {
      setSynopsisError("生成要求不能超过 1000 个字符");
      setSynopsisState("error");
      synopsisGuidanceInput.current?.focus();
      return;
    }
    const token = ++synopsisToken.current;
    synopsisRetry.current = () => void generateNewSynopsis();
    setSynopsisState("generating");
    setSynopsisError("");
    setSynopsisFeedback("");
    try {
      const next = await generateSynopsis(projectId, synopsisGuidance);
      if (!mounted.current || token !== synopsisToken.current) return;
      setSynopsis(next);
      setEditingSynopsis(false);
      await changed();
      if (mounted.current && token === synopsisToken.current) setSynopsisState("idle");
    } catch (error) {
      if (mounted.current && token === synopsisToken.current) {
        setSynopsisError(message(error));
        setSynopsisState("error");
      }
    }
  };

  const beginSynopsisEdit = () => {
    setTagsDraft((synopsis?.tags ?? []).join("，"));
    setBodyDraft(synopsis?.body ?? "");
    setSynopsisError("");
    setEditingSynopsis(true);
  };

  const saveSynopsis = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const validation = synopsisValidation(tagsDraft, bodyDraft);
    if ("error" in validation) {
      setSynopsisError(validation.error);
      setSynopsisState("error");
      (validation.field === "tags" ? tagsInput.current : bodyInput.current)?.focus();
      return;
    }
    const submitted = { tags: validation.tags, body: bodyDraft.trim() };
    const token = ++synopsisToken.current;
    synopsisRetry.current = () => void saveSynopsis({ preventDefault() {} } as React.FormEvent<HTMLFormElement>);
    setSynopsisState("saving");
    setSynopsisError("");
    try {
      const next = await updateSynopsis(projectId, submitted);
      if (!mounted.current || token !== synopsisToken.current) return;
      setSynopsis(next);
      setEditingSynopsis(false);
      await changed();
      if (mounted.current && token === synopsisToken.current) setSynopsisState("idle");
    } catch (error) {
      if (mounted.current && token === synopsisToken.current) {
        setSynopsisError(message(error));
        setSynopsisState("error");
      }
    }
  };

  const generateNewCover = async () => {
    if (coverGuidance.length > 1000) {
      setCoverError("生成要求不能超过 1000 个字符");
      setCoverState("error");
      coverGuidanceInput.current?.focus();
      return;
    }
    const token = ++coverToken.current;
    coverRetry.current = () => void generateNewCover();
    setCoverState("generating");
    setCoverError("");
    setCoverFeedback("");
    try {
      const result = await generateCover(projectId, coverGuidance);
      if (!mounted.current || token !== coverToken.current) return;
      if (result.cover) setCover(result.cover);
      setPromptReady(result.status === "prompt_ready");
      setEditingPrompt(false);
      await changed();
      if (mounted.current && token === coverToken.current) setCoverState("idle");
    } catch (error) {
      if (mounted.current && token === coverToken.current) {
        setCoverError(message(error));
        setCoverState("error");
      }
    }
  };

  const savePrompt = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const prompt = promptDraft.trim();
    if (!prompt) {
      setCoverError("封面提示词不能为空");
      setCoverState("error");
      return;
    }
    if (prompt.length > 4000) {
      setCoverError("封面提示词不能超过 4000 个字符");
      setCoverState("error");
      return;
    }
    const token = ++coverToken.current;
    coverRetry.current = () => void savePrompt({ preventDefault() {} } as React.FormEvent<HTMLFormElement>);
    setCoverState("saving");
    setCoverError("");
    try {
      const next = await updateCoverPrompt(projectId, prompt);
      if (!mounted.current || token !== coverToken.current) return;
      setCover(next);
      setPromptReady(!next.image_version);
      setEditingPrompt(false);
      await changed();
      if (mounted.current && token === coverToken.current) setCoverState("idle");
    } catch (error) {
      if (mounted.current && token === coverToken.current) {
        setCoverError(message(error));
        setCoverState("error");
      }
    }
  };

  const rerenderTitle = async () => {
    const token = ++coverToken.current;
    coverRetry.current = () => void rerenderTitle();
    setCoverState("saving");
    setCoverError("");
    try {
      const next = await renderCoverTitle(projectId);
      if (!mounted.current || token !== coverToken.current) return;
      setCover(next);
      setPromptReady(false);
      await changed();
      if (mounted.current && token === coverToken.current) setCoverState("idle");
    } catch (error) {
      if (mounted.current && token === coverToken.current) {
        const detail = message(error);
        setCoverError(detail.includes("publishing_asset_stale_base") ? "底图已更新，请刷新后重试排版。" : detail);
        setCoverState("error");
      }
    }
  };

  const hasImage = Boolean(cover?.image_version);
  const titleStale = Boolean(cover?.base_image_version && cover.rendered_title !== title);
  const baseStale = Boolean(cover?.base_image_version && cover.base_image_version !== cover.rendered_from_base_version);
  const needsRendering = Boolean(cover?.base_image_version && (!hasImage || titleStale || baseStale));
  const synopsisBusy = synopsisState === "generating" || synopsisState === "saving";
  const coverBusy = coverState === "generating" || coverState === "saving";

  return (
    <section className={styles.grid} aria-label="作品包装">
      <article className={`${styles.card} ${styles.synopsisCard}`} aria-labelledby="synopsis-title">
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
                <button type="button" className={styles.textButton} onClick={() => void copyText(synopsis.body).then(() => setSynopsisFeedback("简介已复制")).catch(() => setSynopsisFeedback("复制简介失败"))}>复制简介</button>
              </div>
            </>
          ) : editingSynopsis ? (
            <form onSubmit={saveSynopsis} className={styles.editForm}>
              <label>标签<input ref={tagsInput} aria-label="标签" value={tagsDraft} onChange={(event) => setTagsDraft(event.target.value)} disabled={synopsisBusy} /></label>
              <small>用逗号或顿号分隔，保留 4–8 个标签。</small>
              <label>简介正文<textarea ref={bodyInput} aria-label="简介正文" rows={7} value={bodyDraft} onChange={(event) => setBodyDraft(event.target.value)} disabled={synopsisBusy} /></label>
              <div className={styles.actions}><button className="ws-button ws-button--primary" type="submit" disabled={synopsisBusy}>{synopsisState === "saving" ? "保存中…" : "保存简介"}</button><button className="ws-button" type="button" onClick={() => { setEditingSynopsis(false); setSynopsisError(""); setSynopsisState("idle"); }} disabled={synopsisBusy}>取消</button></div>
            </form>
          ) : <p className={styles.empty}>还没有简介。生成后可在这里人工修订。</p>}
        </div>
        {!editingSynopsis ? <label className={styles.guidance}>简介生成要求（可选）<textarea ref={synopsisGuidanceInput} rows={2} value={synopsisGuidance} onChange={(event) => setSynopsisGuidance(event.target.value)} disabled={synopsisBusy} maxLength={1001} /></label> : null}
        {!editingSynopsis ? <button type="button" className="ws-button ws-button--primary" onClick={() => void generateNewSynopsis()} disabled={synopsisBusy}>{synopsisState === "generating" ? "生成中…" : synopsis ? "重新生成" : "生成简介"}</button> : null}
        <div className={styles.feedback} aria-live="polite">{synopsisError ? <><span className={styles.error}>{synopsisError}</span>{synopsisRetry.current ? <button type="button" className={styles.textButton} onClick={synopsisRetry.current}>重试</button> : null}</> : synopsisFeedback}</div>
      </article>

      <article className={`${styles.card} ${styles.coverCard}`} aria-labelledby="cover-title">
        <header className={styles.header}>
          <div><p className={styles.kicker}>封面校样</p><h2 id="cover-title">封面</h2></div>
          {cover?.prompt && !editingPrompt ? <button type="button" className="ws-button" onClick={() => { setPromptDraft(cover.prompt ?? ""); setEditingPrompt(true); setCoverError(""); }} disabled={coverBusy}>编辑提示词</button> : null}
        </header>
        <div className={styles.coverDesk}>
          <div className={styles.coverFrame}>
            {hasImage ? <img src={coverImageUrl(projectId, cover?.image_version ?? "")} alt={`${title}封面`} /> : <span>封面校样</span>}
          </div>
          <div className={styles.coverNotes}>
            {cover?.prompt && !editingPrompt ? <><p className={styles.prompt}>{cover.prompt}</p><button type="button" className={styles.textButton} onClick={() => void copyText(cover.prompt ?? "").then(() => setCoverFeedback("提示词已复制")).catch(() => setCoverFeedback("复制提示词失败"))}>复制提示词</button></> : null}
            {editingPrompt ? <form onSubmit={savePrompt} className={styles.editForm}><label>封面提示词<textarea aria-label="封面提示词" rows={6} value={promptDraft} onChange={(event) => setPromptDraft(event.target.value)} disabled={coverBusy} /></label><div className={styles.actions}><button type="submit" className="ws-button ws-button--primary" disabled={coverBusy}>{coverState === "saving" ? "保存中…" : "保存提示词"}</button><button type="button" className="ws-button" disabled={coverBusy} onClick={() => { setEditingPrompt(false); setCoverError(""); setCoverState("idle"); }}>取消</button></div></form> : null}
            {(promptReady || (cover?.prompt && !hasImage)) ? <p className={styles.notice}>图像模型尚未配置。<Link href="/config">前往配置</Link></p> : null}
            {needsRendering ? <div className={styles.renderNotice}><strong>{titleStale ? "书名已变化，重新排版" : "底图已变化，重新排版"}</strong><button type="button" className="ws-button" onClick={() => void rerenderTitle()} disabled={coverBusy}>{coverState === "saving" ? "排版中…" : "重新排版"}</button></div> : null}
            {hasImage ? <a className="ws-button" href={coverImageUrl(projectId, cover?.image_version ?? "", true)} download>下载封面</a> : null}
          </div>
        </div>
        {!editingPrompt ? <><label className={styles.guidance}>封面生成要求（可选）<textarea ref={coverGuidanceInput} rows={2} value={coverGuidance} onChange={(event) => setCoverGuidance(event.target.value)} disabled={coverBusy} maxLength={1001} /></label><button type="button" className="ws-button ws-button--primary" onClick={() => void generateNewCover()} disabled={coverBusy}>{coverState === "generating" ? "生成中…" : hasImage || cover?.prompt ? "重新生成" : "生成封面"}</button></> : null}
        <div className={styles.feedback} aria-live="polite">{coverError ? <><span className={styles.error}>{coverError}</span>{coverRetry.current ? <button type="button" className={styles.textButton} onClick={coverRetry.current}>重试</button> : null}</> : coverFeedback}</div>
      </article>
    </section>
  );
}
