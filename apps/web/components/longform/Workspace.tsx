"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ArrowLeft, CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Search, Settings, X } from "lucide-react";
import type { Book, Command, PageName, StoryTab, WorkspaceAdapter } from "./product";
import s from "./workspace.module.css";

const volumeNames = ["渡口", "暗潮", "远山", "归舟", "旧岸", "归途"];
const people = [{ name: "沈砚", role: "主角" }, { name: "沈渡", role: "失踪的兄长" }, { name: "叶青岚", role: "同行者" }, { name: "林婆婆", role: "渡口旧识" }];
const portrait = "沈砚自小在渡口长大，水声、橹声与江风是他熟悉的一切。性子沉静，习惯在观察中揣摩人心。兄长沈渡多年前离开后杳无音讯，他始终相信兄长还在这条江的某处，于是撑起渡船，来往在人群与江流之间，一点点寻找线索。";
function Landscape() { return <img className={s.landscape} src="/longform/river-landscape.png" alt="" />; }
function Empty({ text }: { text: string }) { return <p className={s.empty}>{text}</p>; }

export function LongformWorkspace({ adapter }: { adapter: WorkspaceAdapter }) {
  const state = useSyncExternalStore(adapter.subscribe, adapter.snapshot, adapter.snapshot);
  const b = state.books.find(book => book.id === state.bookId)!;
  const act = (command: Command) => adapter.execute(command);
  const [editing, setEditing] = useState(false);
  const [dialog, setDialog] = useState<"ai" | "plan" | "future" | "requirements" | "history" | "contradiction" | "reset" | null>(null);
  const [dialogText, setDialogText] = useState("");
  const [search, setSearch] = useState("");
  const [showArchive, setShowArchive] = useState(false);
  const [showDemo, setShowDemo] = useState(false);
  const [openVolumes, setOpenVolumes] = useState<number[]>([2]);
  const directory = useRef<HTMLDivElement>(null);
  const prose = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const c = b.candidate;
  const current = state.selectedChapter ? b.chapters.find(ch => ch.number === state.selectedChapter) : c || b.chapters.at(-1);
  const isCandidate = current === c && !!c;
  const count = b.chapters.length;
  const activeVolume = Math.ceil((current?.number || count + 1) / 50);
  const crossTab = state.storageWarning.startsWith("演示已在另一");
  const busy = b.busy || crossTab;

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
  function openDialog(kind: typeof dialog, text = "") { setDialogText(text); setDialog(kind); }
  function showChapter(number: number) { setEditing(false); setOpenVolumes(v => [...new Set([...v, Math.ceil(number / 50)])]); act({ type: "navigate", page: "writing", chapter: number }); }
  function title(text: string) { return <h2 ref={heading}>{text}</h2>; }

  return <div className={s.app}>
    <div className={s.demoBar}><span>体验原型 · 模拟数据 · 不连接真实作品或模型</span><button onClick={() => setShowDemo(v => !v)}>演示场景</button><button onClick={() => openDialog("reset")}>重置演示</button></div>
    {showDemo && <section className={s.demoControls} aria-label="模拟场景选择"><p>这些开关只用于体验异常流程；演示章节预置，不代表长程生成验收。</p>{([['generation-failure', '下次生成失败'], ['review-failure', '下次检查失败'], ['next-failure', '确认后续写失败'], ['volume-end', '体验卷末'], ['soft-suggestion', '体验可选建议']] as const).map(([scenario, label]) => <button disabled={busy} key={scenario} onClick={() => { act({ type: "scenario", scenario }); setShowDemo(false); }}>{label}</button>)}</section>}
    <header className={s.header}>
      <button className={s.brand} onClick={() => navigate("books")}>{state.page === "books" || state.page === "settings" ? "小说工作台" : b.title}</button>
      <nav aria-label="主要导航">{(state.page === "books" || state.page === "settings" ? [["books", "作品"], ["settings", "设置"]] : [["writing", "写作"], ["planning", "全书规划"], ["story", "故事设定"]]).map(([page, label]) => <button key={page} className={state.page === page ? s.navActive : ""} onClick={() => navigate(page as PageName)}>{label}</button>)}</nav>
      <span className={s.saved}><CheckCircle2 size={17} />{count ? `已确认至第${count}章` : "还没有正式章节"}</span>
      <button className={s.iconButton} aria-label="打开设置" onClick={() => navigate("settings")}><Settings size={20} /></button>
    </header>
    {state.storageWarning && <div className={s.notice} role="alert">{state.storageWarning}</div>}
    {state.page !== "books" && b.notice && <div className={s.notice} role="status">{b.busy && <span className={s.loading} />}{b.notice}</div>}

    {state.page === "books" && <div className={s.booksLayout}>
      <main className={s.booksList}>
        <div className={s.sectionHeading}>{title("我的作品")}<button onClick={() => act({ type: "new-form", open: true })}>新建小说</button></div>
        <p className={s.subtitle}>在这里管理你的小说，继续写作，或开启一个新故事。</p>
        {state.books.filter(book => !!book.archived === showArchive).map(book => <article className={s.bookRow} key={book.id}>
          <div><h3>{book.title}</h3><p>{book.genre} · {book.targetWords ? `目标${book.targetWords / 10000}万字` : "目标篇幅未设置"}</p><small>已确认{book.chapters.length}章{book.candidate ? ` · 第${book.candidate.number}章待处理` : ""}</small></div>
          <div className={s.bookProgress}><h4>{book.candidate ? `第${book.planningVolume}卷　${volumeNames[book.planningVolume - 1] || "新旅程"}` : !book.planAdopted ? "准备故事" : "暂停写作"}</h4><p>{book.candidate ? "上次停在候选稿审阅" : !book.planAdopted ? "先把核心设定理清" : "回到最近确认的章节"}</p></div>
          <div className={s.bookActions}><button className={book.id === "demo-river" ? s.primary : ""} onClick={() => act({ type: "resume", id: book.id })}>继续写作</button><button className={s.textButton} disabled={book.busy} onClick={() => act({ type: "archive", id: book.id, archived: !book.archived })}>{book.archived ? "恢复作品" : "归档"}</button></div>
        </article>)}
        {state.books.every(book => !!book.archived !== showArchive) && <Empty text="这里还没有作品。" />}
        <button className={s.textButton} onClick={() => setShowArchive(v => !v)}>{showArchive ? "返回我的作品" : "查看已归档作品"}</button>
        <Landscape /><p className={s.caption}>演示作品仅保存在当前浏览器。刷新后可以继续。</p>
      </main>
      {state.showNew && <aside className={s.newBook}><NewBook onCreate={act} onCancel={() => act({ type: "new-form", open: false })} /></aside>}
    </div>}

    {state.page === "writing" && <div className={s.workLayout}>
      <aside className={s.sidebar}>
        <h3>章节目录</h3><div className={s.directory} ref={directory} aria-label="章节目录">
          {Array.from({ length: Math.max(1, activeVolume, b.planningVolume) }, (_, i) => i + 1).map(vol => <section key={vol}>
            <button className={s.volume} onClick={() => setOpenVolumes(v => v.includes(vol) ? v.filter(x => x !== vol) : [...v, vol])}>{openVolumes.includes(vol) ? <ChevronDown size={17} /> : <ChevronRight size={17} />}第{vol}卷　{volumeNames[vol - 1] || "新旅程"}</button>
            <p className={s.volumeHint}>{(vol - 1) * 50 + 1} – {vol * 50}章　{count >= vol * 50 ? "已完成" : "正在写作"}</p>
            {openVolumes.includes(vol) && <>{b.chapters.filter(ch => Math.ceil(ch.number / 50) === vol).map(ch => <button key={ch.number} className={s.chapter} aria-current={current?.number === ch.number ? "page" : undefined} onClick={() => showChapter(ch.number)}><span>第{ch.number}章　{ch.title}</span><small>已确认</small></button>)}
              {c && Math.ceil(c.number / 50) === vol && <button className={s.chapter} aria-current={isCandidate ? "page" : undefined} onClick={() => act({ type: "navigate", page: "writing" })}><span>第{c.number}章　{c.title}</span><small>待确认</small></button>}
              {vol === b.planningVolume && [1, 2].map(n => <div className={s.futureChapter} key={n}>第{(c?.number || count) + n}章　{n === 1 ? "线索交换" : "旧信现身"}<small>未开始</small></div>)}</>}
          </section>)}
        </div>
        <div className={s.volumeGoal}><h4>这一卷要完成什么</h4><p>沿着一封失落的信，找出暗潮背后的真相。</p></div><Landscape />
      </aside>
      <main className={s.manuscript} ref={prose} aria-label="正文阅读区">
        {current ? <><div className={s.breadcrumb}><span>第{activeVolume}卷 {volumeNames[activeVolume - 1] || "新旅程"}　 ›　 第{current.number}章</span><span className={isCandidate ? s.accent : ""}>{isCandidate ? "候选稿 · 尚未加入正式章节" : "正式章节 · 只读回看"}</span></div>
          <h1>第{current.number}章　{current.title}</h1>
          {isCandidate && editing ? <div className={s.editor}><label htmlFor="candidate-editor">修改候选正文</label><textarea id="candidate-editor" value={c.editorDraft ?? c.body} onChange={e => act({ type: "draft", text: e.target.value })} disabled={busy} /><p>编辑草稿会保留。保存后需要重新检查，才能确认本章。</p><button className={s.primary} disabled={busy || !(c.editorDraft ?? c.body).trim()} onClick={() => { act({ type: "save-draft", text: c.editorDraft ?? c.body }); setEditing(false); }}>保存改稿</button><button onClick={() => setEditing(false)}>稍后继续编辑</button></div>
          : <div className={s.prose}>{current.body.split("\n\n").map((paragraph, i) => <p key={i}>{isCandidate && c.concern?.quote && paragraph.includes(c.concern.quote) ? <>{paragraph.split(c.concern.quote)[0]}<mark>{c.concern.quote}</mark>{paragraph.split(c.concern.quote).slice(1).join(c.concern.quote)}</> : paragraph}</p>)}</div>}
        </> : <><h1>开始你的第一章</h1><Empty text={b.busy ? "正在准备候选稿，请稍候。" : "先采纳故事规划，再开始正文。每一章都由你亲自确认。"} /></>}
      </main>
      <aside className={s.concerns}>
        <h3>{isCandidate ? "本章需要你决定" : "接下来写什么"}</h3>
        {isCandidate ? <>
          {c.concern ? <div className={s.issue}><CircleAlert size={21} /><div><p>{c.concern.message}</p><p>{c.concern.suggestion}</p>{c.concern.chapter && <button onClick={() => showChapter(c.concern!.chapter!)}>查看第{c.concern.chapter}章依据</button>}</div></div> : <p className={s.reviewLabel}><CheckCircle2 size={19} />{c.label}</p>}
          <div className={s.pair}><button className={s.primary} disabled={busy} onClick={() => openDialog("ai", "保留兄长的线索，不让他在本章正式登场。")}>让 AI 修改</button><button disabled={busy} onClick={() => setEditing(true)}>我来改写</button></div>
          {c.editorDraft !== undefined && <p className={s.muted}>有尚未保存的编辑草稿。确认前请先保存并检查。</p>}
          {(c.needsCheck || c.checking || !c.concern) && <button className={s.wide} disabled={busy || !!c.editorDraft} onClick={() => act({ type: "review" })}>{c.checking ? "正在检查…" : "重新检查"}</button>}
          {c.concern && !c.concern.quote && <button className={s.wide} disabled={busy} onClick={() => act({ type: "accept-suggestion" })}>保留原文，不采用此建议</button>}
          {!!c.pastDrafts.length && <button className={s.textButton} onClick={() => openDialog("history")}>查看保留的旧稿（{c.pastDrafts.length}）</button>}
          <p className={s.smallNote}>修改后重新检查，确认后才加入正式章节。</p>
        </> : <><p>已确认的正文保持原样。可以回看前文，或继续准备新的章节。</p>{c && <button className={s.primary} onClick={() => act({ type: "navigate", page: "writing" })}>回到待确认候选</button>}{b.nextVolume ? <button className={s.primary} disabled={busy} onClick={() => act({ type: "next-volume" })}>准备下一卷</button> : !c && <button className={s.primary} disabled={busy} onClick={() => b.planAdopted ? act({ type: "generate" }) : navigate("planning")}>{b.planAdopted ? "准备下一章" : "查看并采纳规划"}</button>}</>}
        {b.canRetry && <button className={s.wide} disabled={busy} onClick={() => act({ type: c ? "review" : "generate" })}>{c ? "重试检查" : "重试生成"}</button>}
      </aside>
      <footer className={s.writeFooter}>
        {isCandidate ? <><button className={s.primary} disabled={!c.canConfirm || busy || !b.planAdopted || c.editorDraft !== undefined} onClick={() => act({ type: "confirm", continue: true })}>确认并继续下一章</button><span>{!c.canConfirm ? "先处理这处问题，再确认本章。" : "下一章也会等待你确认。"}</span><button disabled={!c.canConfirm || busy || !b.planAdopted || c.editorDraft !== undefined} onClick={() => act({ type: "confirm", continue: false })}>只确认本章</button><button onClick={() => navigate("books")}>保留候选，稍后处理</button></> : <span>已确认正文仅供回看。本轮支持修改尚未确认的候选稿。</span>}
        <small>字数 {current?.body.replace(/\s/g, "").length || 0}</small>
      </footer>
    </div>}

    {state.page === "planning" && <div className={s.workLayout}>
      <aside className={s.sidebar}><h3>全书目录</h3><button className={s.volume}><ChevronDown size={17} />全书方向</button><p className={s.volumeHint}>故事主线 · 人物弧光 · 卷与卷衔接</p>{volumeNames.map((name, i) => <div className={`${s.planVolume} ${i + 1 === b.planningVolume ? s.selected : ""}`} key={name}><h4>第{i + 1}卷　{name}</h4><p>{i * 50 + 1} – {(i + 1) * 50}章　{count >= (i + 1) * 50 ? "已完成" : i + 1 === b.planningVolume ? "当前准备" : "后续方向"}</p></div>)}<Landscape /></aside>
      <main className={s.planning}>
        {!b.direction ? <><h1>先选一个故事方向</h1><p className={s.subtitle}>{b.idea}</p><p>下面是模拟故事方向。选中后，查看全书与首卷规划。</p>{["沿河追寻：从寻找家人，到守护沿河的人。", "旧信悬疑：循着一封信，揭开渡口埋藏的秘密。", "同行成长：在旅途中结识伙伴，一起面对旧日风波。"].map(text => <button className={s.direction} key={text} onClick={() => act({ type: "direction", text })}><span>{text}</span><ChevronRight size={20} /></button>)}</> : <>
          <div className={s.sectionHeading}><h1>全书规划</h1><span>{b.targetWords ? `目标 ${b.targetWords / 10000}万字` : "篇幅未设置"} · {b.targetWords && b.chapterWords ? `约${Math.ceil(b.targetWords / b.chapterWords)}章` : "章数未设置"}</span></div>
          <dl className={s.facts}><dt>故事主线</dt><dd>{b.direction}</dd><dt>最终走向</dt><dd>揭开河运旧案，主角作出自己的选择。</dd></dl>
          <div className={s.sectionHeading}><h1>第{b.planningVolume}卷 · {volumeNames[b.planningVolume - 1] || "新旅程"}</h1><span className={s.badge}>{b.planAdopted ? "你已采纳" : "规划已准备好，待你采纳"}</span></div>
          <dl className={s.facts}>{["本卷目标", "人物变化", "卷末转折"].map((name, i) => <div className={s.factRow} key={name}><dt>{name}</dt><dd>{b.plan.split("；")[i] || "可以在调整规划中补充。"}</dd></div>)}</dl>
          <h3>近期章节安排</h3><table className={s.table}><thead><tr><th>章数</th><th>章节名</th><th>主要内容（简要）</th></tr></thead><tbody>{["雨夜来客", "线索交换", "旧信现身"].map((t, i) => <tr key={t}><td>第{count + i + 1}章</td><td>{t}</td><td>{["渡口收到另一半船印。", "旧物换来新去向。", "与前卷来信形成呼应。"][i]}</td></tr>)}</tbody></table><p>先细化近期章节，后续随故事推进展开。</p>
        </>}
      </main>
      <aside className={s.concerns}><h3>{count ? "从上一卷接着写" : "开始之前"}</h3><section><h4 className={s.accent}>已确认的关键衔接点</h4>{count >= 50 ? <ul><li>主角仍不知道兄长下落（第50章）</li><li>船印尚未解释（第47章）</li></ul> : <p>正文尚未形成这些事实，规划只代表后续打算。</p>}</section><section><h4 className={s.accent}>作者提醒</h4><p>{b.requirements}</p></section>{count > 0 && <button className={s.textButton} onClick={() => showChapter(count)}><ArrowLeft size={17} />回看第{count}章结尾</button>}</aside>
      {b.direction && <footer className={s.writeFooter}><button className={s.primary} disabled={busy} onClick={() => act({ type: "adopt" })}>{b.candidate ? "采纳规划，回到候选稿" : `采纳本卷规划，开始第${count + 1}章`}</button><button disabled={busy || count >= b.planningVolume * 50 - 49} onClick={() => openDialog("plan", b.plan)}>调整规划</button><span>已确认正文不会因调整后续规划而被覆盖。</span></footer>}
    </div>}

    {state.page === "story" && <div className={s.workLayout}>
      <aside className={s.sidebar}><h3>找人物</h3><label className={s.search}><Search size={19} /><input aria-label="搜索人物" placeholder="输入人物名字" value={search} onChange={e => setSearch(e.target.value)} /></label>{people.filter(p => p.name.includes(search)).map(p => <button key={p.name} className={`${s.person} ${state.person === p.name ? s.selected : ""}`} onClick={() => act({ type: "person", name: p.name })}><span><strong>{p.name}</strong><small>{p.role}</small></span><ChevronRight size={18} /></button>)}{!people.some(p => p.name.includes(search)) && <Empty text="没有找到这个人物。" />}<Landscape /></aside>
      <main className={s.storyContent}><nav className={s.tabs} aria-label="故事设定分类">{(["人物", "世界规则", "伏笔线索", "创作要求"] as StoryTab[]).map(tab => <button className={state.storyTab === tab ? s.navActive : ""} key={tab} onClick={() => act({ type: "story-tab", tab })}>{tab}</button>)}</nav>
        {state.storyTab === "人物" && <><h1 className={s.characterName}>{state.person}</h1><p className={s.characterRole}>{state.person === "沈砚" ? "摆渡少年 · 正在追查兄长下落" : people.find(p => p.name === state.person)?.role}</p><p className={s.bio}>{state.person === "沈砚" ? portrait : `${state.person}是这个故事中的${people.find(p => p.name === state.person)?.role}。后续打算可以修改；尚未写进正文的安排不作为已发生事实。`}</p><section><h3>已在正文中发生：</h3>{state.person === "沈砚" && count > 0 ? [{ n: 1, text: "在渡口长大，与林婆婆相依为命" }, { n: 47, text: "得到半枚船印，尚不知用途" }, { n: 50, text: "决定沿河追查兄长留下的线索" }].filter(f => f.n <= count).map(f => <div className={s.evidence} key={f.n}><p>{f.text}（第{f.n}章）</p><button className={s.textButton} onClick={() => showChapter(f.n)}>查看相关章节 <ChevronRight size={17} /></button></div>) : <p>目前没有可引用的正文依据。</p>}</section><section><h3>人物表现：</h3><ul><li>说话克制，不轻易向陌生人透露来意。</li><li>遇事先观察，信任建立得慢。</li></ul></section><section><h3>后续打算 <small className={s.accent}>（尚未写入正文）</small>：</h3><p>{b.future}</p></section></>}
        {state.storyTab === "世界规则" && <><h1>世界规则</h1><section><h3>渡口与河道</h3><p>故事发生在沿河相连的渡口。消息随着船只流动，雨季改变来往的路径。</p><p className={s.muted}>模拟设定 · 尚无可靠章节定位</p></section><section><h3>后续打算</h3><p>{b.future}</p></section></>}
        {state.storyTab === "伏笔线索" && <><h1>伏笔线索</h1><section><h3>半枚船印</h3><p>{count >= 47 ? "已经出现，用途尚未揭晓。" : "计划在后文出现，尚未写入正文。"}</p>{count >= 47 && <button onClick={() => showChapter(47)}>回看第47章</button>}</section><section><h3>失踪兄长的来信</h3><p>沿河追寻的起点，后续将与旧日河运案连接。</p><p className={s.muted}>后续计划，不作为已写事实。</p></section></>}
        {state.storyTab === "创作要求" && <><h1>创作要求</h1><section><h3>必须遵守</h3><p>{b.requirements}</p></section><section><h3>篇幅目标</h3><p>{b.targetWords ? `全书约${b.targetWords / 10000}万字` : "全书篇幅未设置"} · {b.chapterWords ? `每章约${b.chapterWords}字` : "每章字数未设置"}</p><p className={s.muted}>这是创作目标，每章可以根据情节适当调整。</p></section><button onClick={() => openDialog("requirements", b.requirements)}>修改作者要求</button></>}
      </main>
      <aside className={s.concerns}><h3>本卷写作提醒</h3>{["主角还不知道兄长的去向。", "暂不揭晓船印的用途。", "避免突然掌握新能力。"].map(text => <p className={s.reminder} key={text}><CircleAlert size={23} />{text}</p>)}<section><button className={`${s.primary} ${s.wide}`} disabled={busy} onClick={() => openDialog("future", b.future)}>修改后续设定</button><button className={s.wide} onClick={() => openDialog("contradiction")}>我发现前文有矛盾</button><p className={s.smallNote}>已写出的事实若要调整，先核对涉及章节，原稿保留。</p></section></aside>
    </div>}

    {state.page === "settings" && <main className={s.settings}><h1>写作设置</h1><section><h3>正文模型：演示可用</h3><p>这里使用模拟结果，不连接模型，不产生费用。</p><p>真实设置入口在阶段 B 接入。当前演示不会读取或修改任何模型配置。</p></section><button onClick={() => navigate("books")}>返回作品</button></main>}

    {dialog && <dialog ref={node => { if (node && !node.open) node.showModal(); }} className={s.dialog} aria-label={{ ai: "让 AI 修改", plan: "调整规划", future: "修改后续设定", requirements: "修改作者要求", history: "保留的旧稿", contradiction: "核对前文", reset: "重置演示" }[dialog]} onCancel={() => setDialog(null)}>
      <button className={s.close} aria-label="关闭对话框" onClick={() => setDialog(null)}><X size={21} /></button>
      <h2>{{ ai: "希望怎样修改？", plan: "调整后续规划", future: "修改后续打算", requirements: "修改作者要求", history: "保留的旧稿", contradiction: "先找到相关章节", reset: "重新开始演示？" }[dialog]}</h2>
      {dialog === "reset" ? <><p>仅清除这个原型的模拟进度。真实作品和其他工作区不会改变。</p><button className={s.primary} onClick={() => { act({ type: "reset" }); setDialog(null); }}>确认重置演示</button></> : dialog === "history" ? <div className={s.history}>{c?.pastDrafts.map((draft, i) => <section key={i}><h3>{draft.label}</h3><p>{draft.body}</p></section>)}</div> : dialog === "contradiction" ? <><p>本轮只能回看和定位历史正文，不能直接改写已确认内容。可以先记录后续安排。</p>{count > 0 ? <button className={s.primary} onClick={() => { setDialog(null); showChapter(count); }}>回看第{count}章</button> : <p>当前还没有已确认的正文。</p>}</> : <>
        <label htmlFor="dialog-text">{dialog === "ai" ? "修改要求（演示会将兄长登场改为留下线索）" : "修改内容"}</label><textarea id="dialog-text" autoFocus value={dialogText} onChange={e => setDialogText(e.target.value)} />
        <p className={s.smallNote}>{dialog === "ai" ? "仅修改当前候选，完成后重新检查。演示结果固定，不代表真实模型效果。" : "已确认正文与已写事实保持原样。"}</p>
        <button className={s.primary} disabled={!dialogText.trim() || busy} onClick={() => { if (dialog === "ai") act({ type: "ai-edit", instruction: dialogText }); else act({ type: dialog, text: dialogText }); setDialog(null); }}>{dialog === "ai" ? "修改并重新检查" : "保存修改"}</button>
      </>}
    </dialog>}
  </div>;
}

function NewBook({ onCreate, onCancel }: { onCreate: (command: Command) => void; onCancel: () => void }) {
  return <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); onCreate({ type: "create", title: String(data.get("title")), genre: String(data.get("genre")), idea: String(data.get("idea")), targetWords: Number(data.get("target")) * 10000, chapterWords: Number(data.get("chapter")), requirements: String(data.get("requirements")) }); }}>
    <h2>新建小说</h2><p className={s.subtitle}>先说清你想写的故事，其余可以边写边完善。</p>
    <label>暂定书名<input name="title" required maxLength={80} placeholder="给新故事起个名字" /></label>
    <label>小说类型<select name="genre"><option>东方玄幻</option><option>都市</option><option>历史</option><option>悬疑</option><option>其他</option></select></label>
    <label>故事想法<textarea name="idea" required placeholder="一个怎样的人，会经历怎样的故事？" /></label>
    <div className={s.pair}><label>目标篇幅（万字）<input name="target" type="number" defaultValue={90} min={1} max={1000} required /></label><label>每章目标字数<input name="chapter" type="number" defaultValue={3000} min={100} max={20000} step={100} required /></label></div>
    <p className={s.smallNote}>篇幅是创作目标，可随故事发展调整。</p>
    <label>必须遵守的写作要求<textarea name="requirements" placeholder="如：单主角，成长循序渐进，不提前揭晓身世。" /></label>
    <button type="submit" className={`${s.primary} ${s.wide}`}>开始准备故事</button><button type="button" className={s.wide} onClick={onCancel}>取消</button><p className={s.smallNote}>先完善故事方向和分卷规划，采纳后才开始正文。</p>
  </form>;
}
