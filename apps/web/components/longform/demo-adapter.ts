import type { Book, Candidate, Command, Workspace, WorkspaceAdapter } from "./product";

// This adapter never imports application API clients or accesses project files.
const STORAGE_KEY = "novelflow.longform.demo.v1";
const conflict = "沈砚推开门，看见了十年前离开的兄长。";
const repaired = "沈砚推开门，只见桌上留着另一半船印，来客早已离去。";
const opening = [
  "夜色如墨，江面被连绵的雨打得一片迷蒙，水声与橹声混在一起，像是天地间始终不肯停歇的低语。",
  "沈砚裹着湿透的斗笠，推开江边客栈的木门。屋内烛火摇曳，几位行人围坐在火炉旁，衣襟上都带着水汽。掌柜见他进来，连忙递过一条干布，低声道：“外头风急，今晚怕是不太平。”",
  "沈砚找了个角落坐下，点了一壶热酒。窗外的雨丝斜斜地打在江面上，远处的渡口只剩下模糊的影子。他望着杯中微微晃动的酒面，心绪却不由得飘回了多年前。那时兄长也是在这样的雨夜，留下一句“我去寻一条更大的河”，便再未归来。",
  conflict,
  "门前的灯影摇晃了一下。他在门口站了片刻，目光落在旧日的渡口，像是要确认自己是否还记得当年的约定。",
  "雨声依旧，客栈里一时无言。炉火噼啪作响，映着两人之间隔了十年的沉默，也映着江面上不断流去的黑暗。",
].join("\n\n");
const goodBody = opening.replace(conflict, repaired).replace("映着两人之间隔了十年的沉默", "映着隔了十年的牵挂");
const titles = ["雨夜来客", "线索交换", "旧信现身"];
function newCandidate(number: number, hard = false): Candidate {
  return { number, title: titles[(number - 1) % 50 % 3], body: hard ? opening : goodBody,
    label: hard ? "有一处故事冲突" : "已检查，等待你确认", canConfirm: !hard, needsCheck: false,
    checking: false, pastDrafts: [], ...(hard ? { concern: {
      message: "兄长原定在第三卷出现。", suggestion: "是否让本章只留下他的线索？", quote: conflict,
    } } : {}) };
}
function baseBook(id: string, title: string): Book {
  return { id, title, genre: "东方玄幻", idea: "一个摆渡少年收到十年前失踪兄长的来信，沿河追查被隐瞒的旧事。",
    targetWords: 900000, chapterWords: 3000, requirements: "单主角，成长循序渐进，不提前揭晓身世。兄长在第三卷正式登场。",
    future: "逐渐学会依靠同行者。兄长在第三卷正式登场。", direction: "沿河追寻：从寻找家人，到守护沿河的人。",
    plan: "找到兄长留下的渡船账册；从独自追索到学会相信同行者；卷末发现账册是有人故意留下的。",
    planAdopted: true, planningVolume: 2, chapters: [], notice: "", busy: false, canRetry: false, nextVolume: false };
}
function decorate(book: Book) {
  const savedVolumes = book.volumes || [];
  book.volumes = ["渡口", "暗潮", "远山", "归舟", "旧岸", "归途"].map((title, i) => {
    const saved = savedVolumes.find(item => item.number === i + 1);
    return { ...saved, number: i + 1, title: saved?.title || title, start: i * 50 + 1, end: (i + 1) * 50,
      goal: saved?.goal || "沿着一封失落的信，找出暗潮背后的真相。",
      mainConflict: saved?.mainConflict || "线索与证词彼此矛盾。",
      characterChanges: saved?.characterChanges || [], endingTurn: saved?.endingTurn || "",
      label: book.chapters.length >= (i + 1) * 50 ? "已完成" : i + 1 === book.planningVolume ? "当前准备" : "后续方向" };
  });
  book.directions = ["沿河追寻：从寻找家人，到守护沿河的人。", "旧信悬疑：循着一封信，揭开渡口埋藏的秘密。", "同行成长：在旅途中结识伙伴，一起面对旧日风波。"].map(text => ({ text }));
  book.ending = "揭开河运旧案，主角作出自己的选择。";
  const savedUpcoming = book.upcoming || [];
  book.upcoming = titles.map((title, i) => {
    const number = book.chapters.length + i + 1;
    const saved = savedUpcoming.find(item => item.number === number);
    return { number, title: saved?.title || title,
      summary: saved?.summary || "与前文线索形成呼应。",
      goal: saved?.goal || ["渡口收到另一半船印。", "旧物换来新去向。", "与前卷来信形成呼应。"][i],
      conflict: saved?.conflict || "新旧证词存在出入。",
      progression: saved?.progression || "沿着新线索前往下一处地点。",
      foreshadowing: saved?.foreshadowing || ["半枚船印"] };
  });
  book.connections = book.chapters.length >= 50 ? [{text:"主角仍不知道兄长下落。",chapter:50},{text:"船印尚未解释。",chapter:47}] : [];
  book.people = [{ name: "沈砚", role: "主角" }, { name: "沈渡", role: "失踪的兄长" }, { name: "叶青岚", role: "同行者" }, { name: "林婆婆", role: "渡口旧识" }].map(p => ({ ...p, description: p.name === "沈砚" ? "沈砚自小在渡口长大。兄长离开后杳无音讯，他撑起渡船，来往在人群与江流之间，寻找线索。" : `${p.name}是故事中的${p.role}。`, facts: p.name === "沈砚" ? [{chapter:1,text:"在渡口长大，与林婆婆相依为命"},{chapter:47,text:"得到半枚船印，尚不知用途"},{chapter:50,text:"决定沿河追查兄长留下的线索"}].filter(f => f.chapter <= book.chapters.length) : [], performance: p.name === "沈砚" ? ["说话克制，不轻易透露来意。", "遇事先观察，信任建立得慢。"] : [] }));
  book.world = [{ title: "渡口与河道", text: "故事发生在沿河相连的渡口。消息随着船只流动，雨季改变来往的路径。" }];
  book.foreshadow = [{ title: "半枚船印", text: book.chapters.length >= 47 ? "已经出现，用途尚未揭晓。" : "计划在后文出现。", ...(book.chapters.length >= 47 ? {chapter:47} : {}) }];
  book.reminders = ["主角还不知道兄长的去向。", "暂不揭晓船印的用途。", "避免突然掌握新能力。"];
  book.planning = {
    editable: true,
    overall: { direction: book.direction || "", endingGoal: book.ending || "", previousConnection: book.chapters.at(-1)?.title || "暂无已确认章节。" },
    currentVolume: book.planningVolume,
    volumes: book.volumes.map(volume => ({
      number: volume.number, title: volume.title, startChapter: volume.start, endChapter: volume.end,
      goal: volume.goal || "", mainConflict: volume.mainConflict || "",
      characterChanges: volume.characterChanges || [], endingTurn: volume.endingTurn || "",
      statusLabel: volume.label || "", editable: (volume.start || 1) > book.chapters.length,
    })),
    upcomingChapters: book.upcoming.map(chapter => ({
      number: chapter.number, title: chapter.title, goal: chapter.goal || chapter.summary || "",
      conflict: chapter.conflict || "", progression: chapter.progression || "",
      foreshadowing: chapter.foreshadowing || [], editable: chapter.number > book.chapters.length,
    })),
    authorReminders: [...book.reminders],
  };
}
function seeded(): Workspace {
  const river = baseBook("demo-river", "渡河人");
  river.chapters = Array.from({ length: 50 }, (_, i) => ({ number: i + 1,
    title: i === 49 ? "渡口别离" : i === 46 ? "半枚船印" : i === 0 ? "江河初起" : `江上旧事·${i + 1}`,
    body: i === 49 ? "沈砚收起旧信，决定沿河追查兄长留下的线索。\n\n他还不知道兄长的去向。半枚船印静静地躺在掌心，江风送来远处的橹声。" : i === 46 ? "沈砚从信封里得到半枚船印，尚不知用途。\n\n他把它贴身收好，继续向渡口走去。" : "沈砚在渡口长大，与林婆婆相依为命。\n\n清晨的江水漫过石阶，他解开缆绳，撑船迎向第一位客人。" }));
  river.candidate = newCandidate(51, true);
  const city = { ...baseBook("demo-city", "南城来信"), genre: "都市", targetWords: 600000, direction: undefined, planAdopted: false, planningVolume: 1 };
  const history = { ...baseBook("demo-history", "山海旧事"), genre: "历史", targetWords: undefined, chapterWords: undefined, chapters: river.chapters.slice(0, 12), planningVolume: 1 };
  [river, city, history].forEach(decorate);
  return { mode: "demo", books: [river, city, history], bookId: river.id, page: "books", showNew: true, storyTab: "人物", person: "沈砚", storageWarning: "" };
}
type Saved = { format: 1; state: Workspace };
export function createDemoAdapter(): WorkspaceAdapter {
  let state = seeded();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const saved: Saved = JSON.parse(raw);
      if (saved.format !== 1 || !Array.isArray(saved.state?.books) || !saved.state.books.length) throw new Error("invalid demo");
      state = saved.state;
      for (const b of state.books) {
        if (b.busy) {
          b.busy = false; b.canRetry = true; b.notice = "上次操作已中断，已保存的正文和改稿仍在。请主动重试。";
          if (b.candidate?.checking) { b.candidate.checking = false; b.candidate.needsCheck = true; b.candidate.canConfirm = false; b.candidate.label = "检查已中断"; }
        }
      }
    }
  } catch { state.storageWarning = "演示记录无法读取，已打开新的模拟作品。真实作品未被读取。"; }
  state.books.forEach(decorate);
  const listeners = new Set<() => void>();
  const timers = new Set<ReturnType<typeof setTimeout>>();
  const cancelTimers = () => { timers.forEach(clearTimeout); timers.clear(); };
  let failNext = "";
  function publish() {
    state.books.forEach(decorate);
    state = structuredClone(state);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ format: 1, state })); }
    catch { state.storageWarning = "浏览器无法保存演示进度，请勿刷新；当前内容仍可操作。"; }
    listeners.forEach(l => l());
  }
  function book() { return state.books.find(b => b.id === state.bookId)!; }
  function later(b: Book, label: string, action: (current: Book) => void, failure: string) {
    const id = b.id;
    b.busy = true; b.notice = label; b.canRetry = false;
    publish();
    const timer = setTimeout(() => {
      timers.delete(timer);
      // publish replaces objects. Async operations always resolve the current book.
      const current = state.books.find(x => x.id === id)!;
      current.busy = false;
      if (failNext === failure) {
        failNext = ""; current.canRetry = true;
        current.notice = failure === "next-failure" ? "本章已保存，下一章尚未开始。可以稍后重试。" : failure === "review-failure" ? "这次检查没有完成，改稿已保留。请重新检查后再确认。" : "这次生成没有完成，已确认正文未改变。可以重试。";
        if (current.candidate?.checking) { current.candidate.checking = false; current.candidate.needsCheck = true; current.candidate.label = "检查未完成"; }
      } else { current.notice = ""; action(current); }
      publish();
    }, 900);
    timers.add(timer);
  }
  function generate(failure = "generation-failure") {
    const b = book();
    if (b.busy || b.candidate || !b.planAdopted || b.nextVolume) return;
    later(b, "正在准备新的章节候选…", current => { current.candidate = newCandidate(current.chapters.length + 1); if (state.bookId === current.id) state.selectedChapter = undefined; }, failure);
  }
  function review() {
    const b = book(), c = b.candidate;
    if (!c || b.busy) return;
    c.checking = true; c.canConfirm = false; c.label = "正在检查";
    later(b, "正在核对故事衔接与作者要求…", current => {
      const now = current.candidate!;
      now.checking = false; now.needsCheck = false;
      if (now.body.includes(conflict)) {
        now.concern = { message: "兄长原定在第三卷出现。", suggestion: "是否让本章只留下他的线索？", quote: conflict };
        now.label = "有一处故事冲突"; now.canConfirm = false;
      } else { now.concern = undefined; now.label = "已检查，等待你确认"; now.canConfirm = true; }
    }, "review-failure");
  }
  function save(text: string) {
    const c = book().candidate;
    if (!c || book().busy || !text.trim()) return;
    if (c.body === text) { c.editorDraft = undefined; return; }
    c.pastDrafts.unshift({ body: c.body, label: `保留稿 ${c.pastDrafts.length + 1}` });
    c.body = text; c.editorDraft = undefined; c.canConfirm = false; c.needsCheck = true;
    c.concern = undefined; c.label = "改稿已保存，等待重新检查";
  }
  function execute(cmd: Command) {
    const b = book();
    if (cmd.type === "reset") {
      cancelTimers(); failNext = ""; state = seeded(); publish(); return;
    }
    // A second tab becomes read-only until reload, avoiding silent mock overwrites.
    if (state.storageWarning.startsWith("演示已在另一")) return;
    if (cmd.type === "navigate") { state.page = cmd.page; state.bookId = cmd.bookId || state.bookId; state.selectedChapter = cmd.chapter; if (cmd.storyTab) state.storyTab = cmd.storyTab; }
    else if (cmd.type === "new-form") state.showNew = cmd.open;
    else if (cmd.type === "resume") {
      state.bookId = cmd.id; const target = book(); state.selectedChapter = undefined;
      state.page = target.candidate ? "writing" : !target.planAdopted ? "planning" : "writing";
      if (!target.candidate) state.selectedChapter = target.chapters.at(-1)?.number;
    }
    else if (cmd.type === "story-tab") state.storyTab = cmd.tab;
    else if (cmd.type === "person") state.person = cmd.name;
    else if (cmd.type === "archive") { const target = state.books.find(x => x.id === cmd.id)!; if (!target.busy) target.archived = cmd.archived; }
    else if (cmd.type === "create") {
      const created = { ...baseBook(crypto.randomUUID(), cmd.title.trim()), ...cmd, id: crypto.randomUUID(), direction: undefined, planAdopted: false, planningVolume: 1 };
      state.books.push(created); state.bookId = created.id; state.page = "planning"; state.showNew = false;
    }
    else if (b.busy) return;
    else if (cmd.type === "direction") { b.direction = cmd.text; b.planAdopted = false; }
    else if (cmd.type === "plan") {
      if (b.chapters.length >= b.planningVolume * 50 - 49) { b.notice = "这卷已有正式正文，请到下一卷调整后续规划。"; }
      else {
        if (cmd.patch) {
          b.direction = cmd.patch.overall.direction;
          b.ending = cmd.patch.overall.endingGoal;
          b.volumes = (b.volumes || []).map(volume => {
            const update = cmd.patch!.volumes.find(item => item.number === volume.number);
            return update ? { ...volume, title: update.title, goal: update.goal, mainConflict: update.mainConflict,
              characterChanges: update.characterChanges, endingTurn: update.endingTurn } : volume;
          });
          b.upcoming = (b.upcoming || []).map(chapter => {
            const update = cmd.patch!.upcomingChapters.find(item => item.number === chapter.number);
            return update ? { ...chapter, title: update.title, goal: update.goal, conflict: update.conflict,
              progression: update.progression } : chapter;
          });
          b.plan = `${cmd.patch.overall.direction}\n\n${cmd.patch.volumes.find(item => item.number === b.planningVolume)?.goal || "规划已调整。"}`;
        } else b.plan = cmd.text ?? b.plan;
        b.planAdopted = false; b.notice = "规划已调整，请重新采纳后再写作。";
        if (b.candidate) { b.candidate.canConfirm = false; b.candidate.needsCheck = true; }
      }
    }
    else if (cmd.type === "adopt") { b.planAdopted = true; b.nextVolume = false; b.notice = "已采纳当前规划。"; state.page = "writing"; state.selectedChapter = undefined; if (!b.candidate) generate(); }
    else if (cmd.type === "generate") generate();
    else if (cmd.type === "next-volume") { b.planningVolume = Math.floor(b.chapters.length / 50) + 1; b.planAdopted = false; state.page = "planning"; }
    else if (cmd.type === "draft" && b.candidate) b.candidate.editorDraft = cmd.text;
    else if (cmd.type === "save-draft") save(cmd.text);
    else if (cmd.type === "review") review();
    else if (cmd.type === "ai-edit" && b.candidate && cmd.instruction.trim()) {
      save(b.candidate.body.replace(conflict, repaired));
      // Simulation preserves author intent visibly, without pretending a model interpreted it.
      b.notice = `模拟修改要求：${cmd.instruction}`; review();
    }
    else if (cmd.type === "accept-suggestion" && b.candidate?.concern && !b.candidate.concern.quote) { b.candidate.concern = undefined; b.candidate.canConfirm = true; b.candidate.label = "已保留原文，等待你确认"; }
    else if (cmd.type === "confirm" && b.candidate?.canConfirm && b.planAdopted && b.candidate.editorDraft === undefined) {
      const c = b.candidate;
      if (c.number !== b.chapters.length + 1) return;
      b.chapters.push({ number: c.number, title: c.title, body: c.body }); b.candidate = undefined;
      state.selectedChapter = c.number; b.notice = `第${c.number}章已保存。`;
      if (c.number % 50 === 0) { b.nextVolume = true; b.notice += "本卷已完成，可以准备下一卷。"; }
      else if (cmd.continue) generate("next-failure");
    }
    else if (cmd.type === "future") { b.future = cmd.text; if (b.candidate) { b.candidate.canConfirm = false; b.candidate.needsCheck = true; b.candidate.label = "后续设定已变更，请重新检查"; } }
    else if (cmd.type === "requirements") { b.requirements = cmd.text; if (b.candidate) { b.candidate.canConfirm = false; b.candidate.needsCheck = true; b.candidate.label = "作者要求已变更，请重新检查"; } }
    else if (cmd.type === "scenario") {
      if (cmd.scenario === "volume-end") { b.candidate = undefined; b.nextVolume = true; b.planAdopted = true; state.page = "writing"; state.selectedChapter = b.chapters.at(-1)?.number; b.notice = "本卷已完成，可以准备下一卷。"; }
      else if (cmd.scenario === "soft-suggestion" && b.candidate) { b.candidate.concern = { message: "这一段的节奏可以更紧凑。", suggestion: "这是可选建议，你也可以保留原文。" }; b.candidate.canConfirm = false; b.candidate.needsCheck = false; }
      else { failNext = cmd.scenario; b.notice = "已安排一次模拟失败；下一次对应操作会中断，之后可正常重试。"; }
    }
    publish();
  }
  function otherTab(event: StorageEvent) { if (event.key === STORAGE_KEY) { cancelTimers(); state = { ...state, storageWarning: "演示已在另一标签页更新。请刷新此页后继续，避免覆盖较新的进度。" }; listeners.forEach(l => l()); } }
  window.addEventListener("storage", otherTab);
  return { snapshot: () => state, subscribe: l => { listeners.add(l); return () => listeners.delete(l); }, execute,
    dispose: () => { cancelTimers(); window.removeEventListener("storage", otherTab); listeners.clear(); } };
}
