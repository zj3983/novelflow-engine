"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Search, Settings, X } from "lucide-react";
import type { Book, Command, PageName, StoryTab, WorkspaceAdapter, ProductAction, Volume } from "./product";
import { EquipmentCatalog } from "../ws/EquipmentCatalog";
import { MonsterBestiary } from "../ws/MonsterBestiary";
import { BookDetailsEditor, CharacterProfileEditor, DissectionPanel, DynamicWorldPanel, ForeshadowingEditor, RelationshipsEditor, WritingAbilitiesEditor, WritingTemplatesEditor, WorldSectionsEditor } from "./AuthorTools";
import s from "./workspace.module.css";

function Landscape() { return <img className={s.landscape} src="/longform/river-landscape.png" alt="" />; }
function Empty({ text }: { text: string }) { return <p className={s.empty}>{text}</p>; }

export function LongformWorkspace({ adapter }: { adapter: WorkspaceAdapter }) {
  const state = useSyncExternalStore(adapter.subscribe, adapter.snapshot, adapter.snapshot);
  const b = state.books.find(book => book.id === state.bookId) || { id: "", title: "小说工作台", genre: "", idea: "", requirements: "", future: "", plan: "", planAdopted: false, planningVolume: 1, chapters: [], notice: "", busy: false, canRetry: false, nextVolume: false } as Book;
  const live = state.mode === "live";
  const allowed = (name: string, book = b) => !live || !!book.actions?.[name]?.enabled;
  const volumes = b.volumes || [];
  const structuredVolumes = b.planning?.volumes || [];
  const upcoming: {number:number;title:string;goal?:string;summary?:string;conflict?:string;progression?:string;foreshadowing?:string[]}[] = b.planning?.upcomingChapters || b.upcoming || [];
  const people = b.people || [];
  const person = people.find(p => p.name === state.person) || people[0];
  const volumeFor = (number: number) => volumes.find(v => typeof v.start === "number" && number >= v.start && (typeof v.end !== "number" || number <= v.end));
  const act = (command: Command) => adapter.execute(command);
  const [editing, setEditing] = useState(false);
  const [dialog, setDialog] = useState<"ai" | "plan" | "future" | "requirements" | "history" | "contradiction" | "reset" | null>(null);
  const [dialogText, setDialogText] = useState("");
  const [dialogToken, setDialogToken] = useState("");
  const [draftNotice, setDraftNotice] = useState("");
  const completedDialog = useRef<typeof state.lastCompleted>();
  const dialogDrafts = useRef<Record<string,{text:string;token:string}>>({});
  const [search, setSearch] = useState("");
  const [showArchive, setShowArchive] = useState(false);
  const [showDemo, setShowDemo] = useState(false);
  const [openVolumes, setOpenVolumes] = useState<number[]>([]);
  const [detailsBookId, setDetailsBookId] = useState("");
  const detailsBook = state.books.find(book => book.id === detailsBookId) || b;
  const directory = useRef<HTMLDivElement>(null);
  const prose = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const c = b.candidate;
  const current = state.selectedChapter ? b.chapters.find(ch => ch.number === state.selectedChapter) : c || b.chapters.at(-1);
  const isCandidate = current === c && !!c;
  const count = Math.max(0, ...b.chapters.map(ch => ch.number));
  const activeVolume = volumeFor(current?.number || count + 1)?.number || b.planningVolume;
  const crossTab = state.storageWarning.startsWith("演示已在另一");
  const busy = b.busy || crossTab || !!state.sending || !!state.loading;

  useEffect(() => { setOpenVolumes(v => [...new Set([...v, activeVolume])]); }, [b.id, activeVolume]);
  useEffect(() => { setEditing(!!c?.editorDraft); }, [b.id, c?.number]);
  useEffect(() => {
    // Scroll only the directory, and only when the active item is outside its viewport.
    const container = directory.current, item = container?.querySelector<HTMLElement>('[aria-current="page"]');
    if (container && item) {
      const outer = container.getBoundingClientRect(), inner = item.getBoundingClientRect();
      if (inner.top < outer.top) container.scrollTop -= outer.top - inner.top;
      else if (inner.bottom > outer.bottom) container.scrollTop += inner.bottom - outer.bottom;
    }
  }, [state.selectedChapter, c?.number, openVolumes]);
  useEffect(() => { if (prose.current) prose.current.scrollTop = 0; }, [current?.number, b.id]);
  function navigate(page: PageName) { setEditing(false); setDialog(null); act({ type: "navigate", page }); }
  useEffect(() => {
    const completed = state.lastCompleted;
    if (!completed || completed === completedDialog.current) return;
    completedDialog.current = completed;
    if (completed.bookId !== b.id) return;
    if (completed.type === "save-draft") setEditing(false);
    const kind = completed.type === "ai-edit" ? "ai" : completed.type;
    if (kind === dialog && completed.token === dialogToken) { delete dialogDrafts.current[`${b.id}:${kind}`]; setDialog(null); }
  }, [state.lastCompleted, b.id, dialog, dialogToken]);
  function openDialog(kind: typeof dialog, text = "") {
    let token = b.actions?.[kind === "ai" ? "ai-edit" : kind || ""]?.token || "";
    if (live) {
      try {
        const raw = localStorage.getItem(`novelflow.author.dialog:${b.id}:${kind}`);
        if (raw) {
          let saved: { text: string; token?: string };
          try { saved = JSON.parse(raw); } catch { saved = { text: raw }; }
          if (typeof saved?.text === "string") { text = saved.text; token = saved.token || ""; }
        }
      } catch { setDraftNotice("无法读取浏览器中的旧草稿。请保留当前文字，离开前先保存修改。"); }
    }
    const memory = dialogDrafts.current[`${b.id}:${kind}`];
    setDialogText(memory?.text ?? text); setDialogToken(memory?.token ?? token); setDialog(kind);
  }
  function updateDialog(text: string) {
    setDialogText(text); dialogDrafts.current[`${b.id}:${dialog}`] = { text, token: dialogToken };
    if (live) { try { localStorage.setItem(`novelflow.author.dialog:${b.id}:${dialog}`, JSON.stringify({ text, token: dialogToken })); } catch { setDraftNotice("编辑内容暂时无法保存到浏览器，请勿刷新或关闭页面。"); } }
  }
  function showChapter(number: number) { setEditing(false); setOpenVolumes(v => [...new Set([...v, volumeFor(number)?.number || b.planningVolume])]); act({ type: "navigate", page: "writing", chapter: number }); }
  function title(text: string) { return <h2 ref={heading}>{text}</h2>; }

  return <div className={s.app}>
    {!live && <div className={s.demoBar}><span>体验原型 · 模拟数据 · 不连接真实作品或模型</span><button onClick={() => setShowDemo(v => !v)}>演示场景</button><button onClick={() => openDialog("reset")}>重置演示</button></div>}
    {showDemo && <section className={s.demoControls} aria-label="模拟场景选择"><p>这些开关只用于体验异常流程；演示章节预置，不代表长程生成验收。</p>{([['generation-failure', '下次生成失败'], ['review-failure', '下次检查失败'], ['next-failure', '确认后续写失败'], ['volume-end', '体验卷末'], ['soft-suggestion', '体验可选建议']] as const).map(([scenario, label]) => <button disabled={busy} key={scenario} onClick={() => { act({ type: "scenario", scenario }); setShowDemo(false); }}>{label}</button>)}</section>}
    <header className={s.header}>
      <button className={s.brand} onClick={() => navigate("books")}>{state.page === "books" || state.page === "settings" ? "小说工作台" : b.title}</button>
      <nav aria-label="主要导航">{([["books", "作品"], ["planning", "全书规划"], ["writing", "写作"], ["story", "故事设定"]]).map(([page, label]) => <button key={page} disabled={page !== "books" && !b.id} className={state.page === page ? s.navActive : ""} onClick={() => navigate(page as PageName)}>{label}</button>)}</nav>
      <span className={s.saved}><CheckCircle2 size={17} />{count ? `已确认至第${count}章` : "还没有正式章节"}</span>
      <button className={s.iconButton} aria-label="打开设置" onClick={() => navigate("settings")}><Settings size={20} /></button>
    </header>
    {draftNotice && <div className={s.notice} role="alert">{draftNotice}</div>}
    {state.loading && <div className={s.notice}>正在同步最新的作品状态…</div>}{state.error && <div className={s.notice} role="alert">{state.error}<button onClick={() => act({ type: "refresh" })}>重新连接</button></div>}
    {state.recoveredDraft !== undefined && <section className={s.notice}><h3>保留的编辑草稿</h3><p>对应的候选已不在当前待确认列表。文字仍保留在此，供你复制。</p><textarea aria-label="保留的编辑草稿" readOnly value={state.recoveredDraft} /><button onClick={() => act({ type: "discard-local-draft" })}>清除本地草稿</button></section>}
    {state.storageWarning && <div className={s.notice} role="alert">{state.storageWarning}</div>}
    {state.page !== "books" && b.notice && <div className={s.notice} role="status">{b.busy && <span className={s.loading} />}{b.notice}</div>}

    {state.page === "books" && <div className={s.booksLayout}>
      <main className={s.booksList}>
        <div className={s.sectionHeading}>{title("我的作品")}<button disabled={live && !state.actions?.create?.enabled} onClick={() => act({ type: "new-form", open: true })}>新建小说</button></div>
        <p className={s.subtitle}>在这里管理你的小说，继续写作，或开启一个新故事。</p>
        {state.books.filter(book => !!book.archived === showArchive).map(book => <article className={s.bookRow} key={book.id}>
          <div><h3>{book.title}</h3><p>{book.genre} · {book.targetWords ? `目标${book.targetWords / 10000}万字` : "目标篇幅未设置"}</p><small>已确认{book.chapters.length}章{book.candidate ? ` · 第${book.candidate.number}章待处理` : ""}</small></div>
          <div className={s.bookProgress}><h4>{book.candidate ? `第${book.planningVolume}卷　${book.volumes?.find(v => v.number === book.planningVolume)?.title || ""}` : !book.planAdopted ? "准备故事" : "暂停写作"}</h4><p>{book.candidate ? "上次停在候选稿审阅" : !book.planAdopted ? "先把核心设定理清" : "回到最近确认的章节"}</p></div>
          <div className={s.bookActions}><button className={book.id === "demo-river" ? s.primary : ""} onClick={() => act({ type: "resume", id: book.id })}>继续写作</button><button className={s.textButton} onClick={() => {setDetailsBookId(book.id);act({type:"navigate",page:"books",bookId:book.id})}}>作品资料</button><button className={s.textButton} disabled={book.busy || !!state.sending || !allowed("archive", book)} onClick={() => act({ type: "archive", id: book.id, archived: !book.archived })}>{book.archived ? "恢复作品" : "归档"}</button>{live&&!book.archived&&<button className={s.textButton} disabled={book.busy||!!state.sending||!allowed("trash",book)} onClick={()=>{if(window.confirm(`将“${book.title}”移入回收站？`))act({type:"trash",confirm:true})}}>移入回收站</button>}</div>
        </article>)}
        {state.books.every(book => !!book.archived !== showArchive) && <Empty text="这里还没有作品。" />}
        {!!state.recycleBin?.length&&<section className={s.recycleBin}><h2>回收站</h2><p>彻底删除后无法恢复。删除时需要再次输入完整书名。</p>{state.recycleBin.map(item=><article key={item.id}><strong>{item.title}</strong><div className={s.pair}><button disabled={!!state.sending||!item.actions["restore-trashed"]?.enabled} onClick={()=>act({type:"restore-trashed",id:item.id})}>恢复作品</button><button disabled={!!state.sending||!item.actions["delete-trashed"]?.enabled} onClick={()=>{const entered=window.prompt(`彻底删除“${item.title}”？请输入完整书名确认。`);if(entered===item.title)act({type:"delete-trashed",id:item.id,confirmTitle:entered});else if(entered!==null)window.alert("书名不完全一致，作品没有删除。")}}>彻底删除</button></div></article>)}</section>}
        <button className={s.textButton} onClick={() => setShowArchive(v => !v)}>{showArchive ? "返回我的作品" : "查看已归档作品"}</button>
        <Landscape /><p className={s.caption}>{live ? "每一章由你确认。未完成的工作可以回来继续。" : "演示作品仅保存在当前浏览器。刷新后可以继续。"}</p>{live && state.links?.import && <a href={state.links.import}>导入已有作品</a>}
      </main>
      {state.showNew ? <aside className={s.newBook}><NewBook demo={!live} genres={state.genres} busy={!!state.sending} onCreate={act} onCancel={() => act({ type: "new-form", open: false })} /></aside> : detailsBook && <aside className={s.newBook} key={detailsBook.id}><BookDetailsEditor book={detailsBook} busy={busy} act={act} /><a href="/novel-types">管理全局作品类型</a></aside>}
    </div>}

    {state.page === "writing" && <div className={s.workLayout}>
      <aside className={s.sidebar}>
        <h3>章节目录</h3><div className={s.directory} ref={directory} aria-label="章节目录">
          {(volumes.length ? volumes : [{ number: 1, title: "章节", start: 1 } as Volume]).map(vol => <section key={vol.number}>
            <button className={s.volume} onClick={() => setOpenVolumes(v => v.includes(vol.number) ? v.filter(x => x !== vol.number) : [...v, vol.number])}>{openVolumes.includes(vol.number) ? <ChevronDown size={17} /> : <ChevronRight size={17} />}第{vol.number}卷　{vol.title}</button>
            <p className={s.volumeHint}>{vol.start ? `第${vol.start}章起` : ""}{vol.end ? ` — 第${vol.end}章` : ""}　{vol.label}</p>
            {(openVolumes.includes(vol.number) || volumes.length <= 1) && <>{b.chapters.filter(ch => (volumeFor(ch.number)?.number || 1) === vol.number).map(ch => <button key={ch.number} className={s.chapter} aria-current={current?.number === ch.number ? "page" : undefined} onClick={() => showChapter(ch.number)}><span>第{ch.number}章　{ch.title}</span><small>已确认</small></button>)}
              {c && (volumeFor(c.number)?.number || 1) === vol.number && <button className={s.chapter} aria-current={isCandidate ? "page" : undefined} onClick={() => act({ type: "navigate", page: "writing" })}><span>第{c.number}章　{c.title}</span><small>待确认</small></button>}
              {(b.upcoming || []).filter(ch => (volumeFor(ch.number)?.number || 1) === vol.number && ch.number !== c?.number).map(ch => <div className={s.futureChapter} key={ch.number}>第{ch.number}章　{ch.title}<small>未开始</small></div>)}</>}
          </section>)}
        </div>
        <div className={s.volumeGoal}><h4>这一卷要完成什么</h4><p>{volumes.find(v => v.number === b.planningVolume)?.goal || "本卷目标尚未准备。"}</p></div><Landscape />
      </aside>
      <main className={s.manuscript} ref={prose} aria-label="正文阅读区">
        {current ? <><div className={s.breadcrumb}><span>第{activeVolume}卷 {volumes.find(v => v.number === activeVolume)?.title || ""}　 ›　 第{current.number}章</span><span className={isCandidate ? s.accent : ""}>{isCandidate ? "候选稿 · 尚未加入正式章节" : "正式章节 · 只读回看"}</span></div>
          <h1>第{current.number}章　{current.title}</h1>
          {isCandidate && editing ? <div className={s.editor}><label htmlFor="candidate-editor">修改候选正文</label><textarea id="candidate-editor" value={c.editorDraft ?? c.body} onChange={e => act({ type: "draft", text: e.target.value })} disabled={busy} /><p>编辑草稿会保留。保存后需要重新检查，才能确认本章。</p><button className={s.primary} disabled={busy || !allowed("save-draft") || !(c.editorDraft ?? c.body).trim()} onClick={() => { act({ type: "save-draft", text: c.editorDraft ?? c.body }); }}>保存改稿</button><button onClick={() => setEditing(false)}>稍后继续编辑</button>{live && <button onClick={() => { act({ type: "discard-local-draft" }); setEditing(false); }}>结束编辑，使用已保存正文</button>}</div>
          : <div className={s.prose}>{current.body.split("\n\n").map((paragraph, i) => <p key={i}>{isCandidate && c.concern?.quote && paragraph.includes(c.concern.quote) ? <>{paragraph.split(c.concern.quote)[0]}<mark>{c.concern.quote}</mark>{paragraph.split(c.concern.quote).slice(1).join(c.concern.quote)}</> : paragraph}</p>)}</div>}
        </> : <><h1>开始你的第一章</h1><Empty text={b.busy ? "正在准备候选稿，请稍候。" : "先采纳故事规划，再开始正文。每一章都由你亲自确认。"} /></>}
      </main>
      <aside className={s.concerns}>
        <h3>{isCandidate ? "本章需要你决定" : "接下来写什么"}</h3>
        {isCandidate ? <>
          {c.concern ? <div className={s.issue}><CircleAlert size={21} /><div><p>{c.concern.message}</p><p>{c.concern.suggestion}</p>{c.concern.chapter && <button onClick={() => showChapter(c.concern!.chapter!)}>查看第{c.concern.chapter}章依据</button>}</div></div> : <p className={s.reviewLabel}><CheckCircle2 size={19} />{c.label}</p>}
          {c.concerns?.slice(1).map((item, i) => <section className={s.issue} key={i}><div><p>{item.message}</p><p>{item.suggestion}</p>{item.chapter && <button onClick={() => showChapter(item.chapter!)}>查看第{item.chapter}章依据</button>}</div></section>)}
          <div className={s.pair}><button className={s.primary} disabled={busy || !allowed("ai-edit") || c.editorDraft !== undefined} onClick={() => openDialog("ai")}>让 AI 修改</button><button disabled={busy || !allowed("save-draft")} onClick={() => setEditing(true)}>我来改写</button></div>
          {c.editorDraft !== undefined && <p className={s.muted}>有尚未保存的编辑草稿。确认前请先保存并检查。</p>}
          {(live || c.needsCheck || c.checking || !c.concern) && <button className={s.wide} disabled={busy || c.editorDraft !== undefined || !allowed("review")} onClick={() => act({ type: "review" })}>{c.checking ? "正在检查…" : "重新检查"}</button>}
          {c.concern && (live ? c.canAcceptSuggestion : !c.concern.quote) && <button className={s.wide} disabled={busy || c.editorDraft !== undefined || !allowed("accept-suggestion")} onClick={() => act({ type: "accept-suggestion" })}>{live ? "保留原文并确认本章（接受提醒）" : "保留原文，不采用此建议"}</button>}
          {!!c.pastDrafts.length && <button className={s.textButton} onClick={() => openDialog("history")}>查看保留的旧稿（{c.pastDrafts.length}）</button>}
          <p className={s.smallNote}>修改后重新检查，确认后才加入正式章节。</p>
        </> : <><p>已确认的正文保持原样。可以回看前文，或继续准备新的章节。</p>{c && <button className={s.primary} onClick={() => act({ type: "navigate", page: "writing" })}>回到待确认候选</button>}{b.nextVolume ? <button className={s.primary} disabled={busy || !allowed("next-volume")} onClick={() => act({ type: "next-volume" })}>准备下一卷</button> : !c && <button className={s.primary} disabled={busy || (b.planAdopted && !allowed("generate"))} onClick={() => b.planAdopted ? act({ type: "generate" }) : navigate("planning")}>{b.planAdopted ? "准备下一章" : "查看并采纳规划"}</button>}</>}
        {live && ["retry-next", "complete-volume", "discard"].map(name => b.actions?.[name] && <ActionButton key={name} action={b.actions[name]} busy={busy} act={act} />)}
        {b.canRetry && <button className={s.wide} disabled={busy || !allowed(c ? "review" : "generate")} onClick={() => act({ type: c ? "review" : "generate" })}>{c ? "重试检查" : "重试生成"}</button>}
      </aside>
      <footer className={s.writeFooter}>
        {isCandidate ? <><button className={s.primary} disabled={!c.canConfirm || busy || !b.planAdopted || c.editorDraft !== undefined || !allowed("confirm")} onClick={() => act({ type: "confirm", continue: true })}>确认并继续下一章</button><span>{!c.canConfirm ? "先处理这处问题，再确认本章。" : "下一章也会等待你确认。"}</span><button disabled={!c.canConfirm || busy || !b.planAdopted || c.editorDraft !== undefined || !allowed("confirm")} onClick={() => act({ type: "confirm", continue: false })}>只确认本章</button><button onClick={() => navigate("books")}>保留候选，稍后处理</button></> : <span>已确认正文仅供回看。本轮支持修改尚未确认的候选稿。</span>}
        <small>字数 {current?.body.replace(/\s/g, "").length || 0}</small>
      </footer>
    </div>}

    {state.page === "planning" && <div className={s.workLayout}>
      <aside className={s.sidebar}><h3>全书目录</h3>{volumes.map(v => {const detail=structuredVolumes.find(item=>item.number===v.number);return <section className={s.planVolume} key={v.number}><h4>第{v.number}卷　{v.title}</h4><p>{v.goal || detail?.goal}</p>{detail?.mainConflict&&<p>主要冲突：{detail.mainConflict}</p>}{detail&&detail.characterChanges.length>0&&<p>人物变化：{detail.characterChanges.join("、")}</p>}{detail?.endingTurn&&<p>卷末转折：{detail.endingTurn}</p>}<small>{v.label || detail?.statusLabel}</small></section>})}<Landscape /></aside>
      <main className={s.planning}>
        {live && <div className={s.pair}>{["prepare-plan", "sync-plan", "refresh-plan", "continue-plan", "complete-volume", "next-volume"].map(name => b.actions?.[name] && <ActionButton key={name} action={b.actions[name]} busy={busy} act={act} />)}</div>}
        {!b.direction ? <><h1>先选一个故事方向</h1><p>{b.idea}</p>{!b.directions?.length && <button className={s.primary} disabled={busy || !allowed("prepare-directions")} onClick={() => act({ type: "prepare-directions" })}>准备故事方向</button>}{b.directions?.map(d => <button className={s.direction} disabled={busy || !allowed("direction")} key={d.id || d.text} onClick={() => act({ type: "direction", text: d.text, id: d.id })}><span>{d.label && <strong>{d.label}<br /></strong>}{d.text}</span><ChevronRight size={20} /></button>)}</> : <>
          <div className={s.sectionHeading}><h1>全书规划</h1><span>{b.targetWords ? `目标 ${b.targetWords / 10000}万字` : "篇幅未设置"}</span></div>
          <dl className={s.facts}><dt>故事主线</dt><dd>{b.direction}</dd>{b.ending && <><dt>最终走向</dt><dd>{b.ending}</dd></>}</dl>
          <div className={s.sectionHeading}><h1>第{b.planningVolume}卷 · {volumes.find(v => v.number === b.planningVolume)?.title || "当前规划"}</h1><span className={s.badge}>{b.planAdopted ? "你已采纳" : "等待你查看并采纳"}</span></div>
          <p className={s.bio}>{b.plan || "规划尚未准备完整。"}</p>{b.planning?.overall?.previousConnection&&<section><h3>与前文衔接</h3><p>{b.planning.overall.previousConnection}</p></section>}<h3>近期章节安排</h3>{upcoming.length ? <div className={s.chapterPlanList}>{upcoming.map(ch => <article key={ch.number}><h4>第{ch.number}章　{ch.title}</h4><p>{ch.goal || ch.summary || ""}</p>{ch.conflict&&<p><strong>冲突：</strong>{ch.conflict}</p>}{ch.progression&&<p><strong>推进：</strong>{ch.progression}</p>}{ch.foreshadowing?.length ? <p><strong>关联伏笔：</strong>{ch.foreshadowing.join("、")}</p> : null}</article>)}</div> : <Empty text="近期章节尚未准备。" />}{b.planning?.authorReminders?.map((item,i)=><p className={s.smallNote} key={i}>{item}</p>)}
        </>}
        {b.actions?.plan?.reason && <p>{b.actions.plan.reason}</p>}
        {b.actions?.adopt?.reason && <p>{b.actions.adopt.reason}</p>}
      </main>
      <aside className={s.concerns}><h3>前文衔接</h3>{b.connections?.length ? b.connections.map((item, i) => <section key={i}><p>{item.text}</p>{item.chapter && <button onClick={() => showChapter(item.chapter!)}>回看第{item.chapter}章</button>}</section>) : <p>目前没有可引用的前文章节。</p>}<h4>作者要求</h4><p>{b.requirements || "尚未填写"}</p></aside>
      {b.direction && <footer className={s.writeFooter}><button className={s.primary} disabled={busy || !allowed("adopt")} onClick={() => act({ type: "adopt" })}>采纳当前规划</button><button disabled={busy || !allowed("plan")} onClick={() => openDialog("plan", b.plan)}>调整规划</button>{b.planAdopted && <button disabled={busy || (!c && !allowed("generate"))} onClick={() => c ? navigate("writing") : act({ type: "generate" })}>{c ? "查看候选稿" : "开始正文"}</button>}<span>采纳规划后，每一章仍由你确认。</span></footer>}
    </div>}
    {state.page === "story" && <div className={s.workLayout}>
      <aside className={s.sidebar}><h3>找人物</h3><label className={s.search}><Search size={19} /><input aria-label="搜索人物" placeholder="输入人物名字" value={search} onChange={e => setSearch(e.target.value)} /></label>{people.filter(p => p.name.includes(search)).map(p => <button key={p.name} className={`${s.person} ${person?.name === p.name ? s.selected : ""}`} onClick={() => act({ type: "person", name: p.name })}><span><strong>{p.name}</strong><small>{p.role}</small></span><ChevronRight size={18} /></button>)}{!people.some(p => p.name.includes(search)) && <Empty text="目前没有符合条件的人物。" />}<Landscape /></aside>
      <main className={s.storyContent}><nav className={s.tabs} aria-label="故事设定分类">{(["人物", "世界规则", "伏笔线索", "创作要求"] as StoryTab[]).map(tab => <button className={state.storyTab === tab ? s.navActive : ""} key={tab} onClick={() => act({ type: "story-tab", tab })}>{tab}</button>)}</nav>
        {state.storyTab === "人物" && <>{person ? <><h1 className={s.characterName}>{person.name}</h1><p className={s.characterRole}>{person.role}</p>{b.characterCardsView ? <CharacterProfileEditor card={b.characterCardsView.items.find(item=>item.name===person.name)} busy={busy} act={act} /> : <><p className={s.bio}>{person.description}</p><section><h3>已在正文中发生</h3>{person.facts.map((f,i)=><p key={i}>{f.text}{f.chapter&&<button onClick={()=>showChapter(f.chapter!)}>查看第{f.chapter}章</button>}</p>)}</section><section><h3>人物表现</h3>{person.performance.map((text,i)=><p key={i}>{text}</p>)}</section><section><h3>后续打算</h3><p>{b.future||"尚未填写"}</p></section></>}</> : <Empty text="人物设定将在规划和写作过程中逐步形成。" />}{b.relationshipView&&<RelationshipsEditor items={b.relationshipView.items} people={people} save={b.relationshipView.save} busy={busy} act={act} />}</>}
        {state.storyTab === "世界规则" && <><h1>世界规则</h1>{b.worldSections ? <WorldSectionsEditor sections={b.worldSections.filter(section=>section.id!=="equipment"&&section.id!=="monsters")} busy={busy} act={act} /> : b.world?.map((entry,i)=><section key={i}><h3>{entry.title}</h3><p>{entry.text}</p></section>)}{b.worldCatalogs&&<><EquipmentCatalog projectId={b.id} blueprint={b.worldCatalogs} onSaved={()=>act({type:"refresh"})} /><MonsterBestiary projectId={b.id} blueprint={b.worldCatalogs} onSaved={()=>act({type:"refresh"})} /></>}{b.worldEnrichment&&<section className={s.productEditor}><h3>AI 补全世界观</h3><p>{b.worldEnrichment.statusLabel} · {b.worldEnrichment.message}</p><ActionButton action={b.worldEnrichment.action} busy={busy} act={act} /></section>}{b.confirmedWorldFacts&&b.confirmedWorldFacts.length>0&&<section><h3>正文中已确认的世界事实</h3>{b.confirmedWorldFacts.map((fact,i)=><p className={s.evidence} key={`${i}:${fact.text}`}>{fact.text}{fact.chapter&&<button onClick={()=>showChapter(fact.chapter!)}>查看第{fact.chapter}章</button>}</p>)}</section>}<DynamicWorldPanel value={b.dynamicWorld} chapters={b.chapters} onSelect={number=>act({type:"navigate",page:"story",chapter:number})} /></>}
        {state.storyTab === "伏笔线索" && <><h1>伏笔线索</h1>{b.foreshadowingView ? <ForeshadowingEditor items={b.foreshadowingView.items} save={b.foreshadowingView.save} busy={busy} act={act} onChapter={number=>showChapter(number)} /> : b.foreshadow?.map((entry,i)=><section key={i}><h3>{entry.title}</h3><p>{entry.text}</p></section>)}</>}
        {state.storyTab === "创作要求" && <><h1>创作要求</h1><section><h3>必须遵守</h3><p>{b.requirements || "尚未填写"}</p></section><section><h3>篇幅目标</h3><p>{b.targetWords ? `全书约${b.targetWords / 10000}万字` : "全书篇幅未设置"} · {b.chapterWords ? `每章约${b.chapterWords}字` : "每章字数未设置"}</p><p>这是创作目标，每章可以根据情节适当调整。</p></section><button disabled={busy || !allowed("requirements")} onClick={() => openDialog("requirements", b.requirements)}>修改作者要求</button>{b.writingTemplatesView&&<WritingTemplatesEditor templates={b.writingTemplatesView.templates} busy={busy} act={act} />}{b.writingAbilitiesView&&<WritingAbilitiesEditor value={b.writingAbilitiesView} bookId={b.id} busy={busy} act={act} />}</>}
      </main>
      <aside className={s.concerns}><h3>写作提醒</h3>{b.reminders?.map((text, i) => <p className={s.reminder} key={i}><CircleAlert size={23} />{text}</p>)}<button className={`${s.primary} ${s.wide}`} disabled={busy || !allowed("future")} onClick={() => openDialog("future", b.future)}>修改后续设定</button><button className={s.wide} onClick={() => openDialog("contradiction")}>我发现前文有矛盾</button><p>已确认正文只供回看，不能在这里改写历史。</p></aside>
    </div>}

    {state.page === "writing" && live && b.dissectionView && <main className={s.authorTools}><DissectionPanel value={b.dissectionView} book={b} busy={busy} act={act} onChapter={number=>act({type:"navigate",page:"writing",chapter:number})} /></main>}

    {state.page === "settings" && <main className={s.settings}><h1>写作设置</h1><section><h3>正文模型：演示可用</h3><p>这里使用模拟结果，不连接模型，不产生费用。</p><p>真实工作区提供独立设置入口。当前演示不会读取或修改任何模型配置。</p></section><button onClick={() => navigate("books")}>返回作品</button></main>}

    {dialog && <dialog ref={node => { if (node && !node.open) node.showModal(); }} className={s.dialog} aria-label={{ ai: "让 AI 修改", plan: "调整规划", future: "修改后续设定", requirements: "修改作者要求", history: "保留的旧稿", contradiction: "核对前文", reset: "重置演示" }[dialog]} onCancel={() => setDialog(null)}>
      <button className={s.close} aria-label="关闭对话框" onClick={() => setDialog(null)}><X size={21} /></button>
      {state.error && <p role="alert">{state.error}</p>}
      <h2>{{ ai: "希望怎样修改？", plan: "调整后续规划", future: "修改后续打算", requirements: "修改作者要求", history: "保留的旧稿", contradiction: "先找到相关章节", reset: "重新开始演示？" }[dialog]}</h2>
      {dialog === "reset" ? <><p>仅清除这个原型的模拟进度。真实作品和其他工作区不会改变。</p><button className={s.primary} onClick={() => { act({ type: "reset" }); setDialog(null); }}>确认重置演示</button></> : dialog === "history" ? <div className={s.history}>{c?.pastDrafts.map((draft, i) => <section key={i}><h3>{draft.label}</h3><p>{draft.body}</p></section>)}</div> : dialog === "contradiction" ? <><p>本轮只能回看和定位历史正文，不能直接改写已确认内容。可以先记录后续安排。</p>{count > 0 ? <button className={s.primary} onClick={() => { setDialog(null); showChapter(count); }}>回看第{count}章</button> : <p>当前还没有已确认的正文。</p>}</> : <>
        <label htmlFor="dialog-text">{dialog === "ai" ? "修改要求" : "修改内容"}</label><textarea id="dialog-text" autoFocus value={dialogText} onChange={e => updateDialog(e.target.value)} />
        {live && !dialogToken && <p>这份旧草稿无法直接提交。请复制文字后重新打开当前内容，再粘贴需要保留的修改。</p>}
        {live && <button onClick={() => { try { localStorage.removeItem(`novelflow.author.dialog:${b.id}:${dialog}`); } catch { /* text remains visible */ } delete dialogDrafts.current[`${b.id}:${dialog}`]; setDialogToken(b.actions?.[dialog === "ai" ? "ai-edit" : dialog]?.token || ""); setDialogText(dialog === "plan" ? b.plan : dialog === "future" ? b.future : dialog === "requirements" ? b.requirements : ""); }}>重新载入当前内容（请先复制要保留的文字）</button>}
        <p className={s.smallNote}>{dialog === "ai" ? "仅修改当前候选，完成后重新检查；不会覆盖已确认正文。" : "已确认正文与已写事实保持原样。"}</p>
        <button className={s.primary} disabled={!dialogText.trim() || busy || (live && !dialogToken) || !allowed(dialog === "ai" ? "ai-edit" : dialog)} onClick={() => { if (dialog === "ai") act({ type: "ai-edit", instruction: dialogText, ...(live ? { token: dialogToken } : {}) }); else act({ type: dialog, text: dialogText, ...(live ? { token: dialogToken } : {}) }); if (!live) setDialog(null); }}>{dialog === "ai" ? "修改并重新检查" : "保存修改"}</button>
      </>}
    </dialog>}
  </div>;
}
function NewBook({ onCreate, onCancel, genres, busy, demo }: { demo?: boolean; genres?: { value: string; label: string }[]; busy?: boolean; onCreate: (command: Command) => void; onCancel: () => void }) {
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => { if (demo) return; try { const fields = JSON.parse(localStorage.getItem("novelflow.author.new-book") || "null"); if (fields && formRef.current) for (const [name, value] of Object.entries(fields)) { const el = formRef.current.elements.namedItem(name); if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) el.value = String(value); } } catch { /* optional recovery */ } }, []);
  return <form ref={formRef} onChange={() => { if (!demo && formRef.current) { try { localStorage.setItem("novelflow.author.new-book", JSON.stringify(Object.fromEntries(new FormData(formRef.current)))); } catch { /* retain fields in memory */ } } }} onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); onCreate({ type: "create", title: String(data.get("title")), genre: String(data.get("genre")), idea: String(data.get("idea")), targetWords: Number(data.get("target")) * 10000, chapterWords: Number(data.get("chapter")), requirements: String(data.get("requirements")) }); }}>
    <h2>新建小说</h2><p className={s.subtitle}>先说清你想写的故事，其余可以边写边完善。</p>
    <label>暂定书名<input name="title" required maxLength={80} placeholder="给新故事起个名字" /></label>
    <label>小说类型<select name="genre" required>{(genres || [{ value: "东方玄幻", label: "东方玄幻" }, { value: "都市", label: "都市" }]).map(g => <option key={g.value} value={g.value}>{g.label}</option>)}</select></label>
    <label>故事想法<textarea name="idea" required maxLength={1000} placeholder="一个怎样的人，会经历怎样的故事？" /></label>
    <div className={s.pair}><label>目标篇幅（万字）<input name="target" type="number" defaultValue={90} min={1} max={1000} required /></label><label>每章目标字数<input name="chapter" type="number" defaultValue={3000} min={500} max={20000} step={100} required /></label></div>
    <p className={s.smallNote}>篇幅是创作目标，每章可以根据情节适当浮动。</p>
    <label>必须遵守的写作要求<textarea name="requirements" placeholder="如：单主角，成长循序渐进，不提前揭晓身世。" /></label>
    <button type="submit" disabled={busy} className={`${s.primary} ${s.wide}`}>开始准备故事</button><button type="button" className={s.wide} onClick={onCancel}>取消</button><p className={s.smallNote}>先完善故事方向和分卷规划，采纳后才开始正文。</p>
  </form>;
}

function ActionButton({ action, busy, act }: { action: ProductAction; busy: boolean; act: (c: Command) => void }) {
  return <div><button disabled={busy || !action.enabled} onClick={() => act({ type: action.command, token: action.token } as Command)}>{action.label}</button>{action.reason && <p className={s.smallNote}>{action.reason}</p>}</div>;
}
