import { apiBase } from "../../lib/api-client";
import type { Command, Workspace, WorkspaceAdapter } from "./product";

const KEY = "novelflow.author.workspace.v1";
type Draft = { text: string; token: string; candidate?: string };
type Local = { bookId: string; page: Workspace["page"]; selectedChapter?: number; storyTab: Workspace["storyTab"]; person: string; drafts: Record<string, Draft> };
/** Only navigation and unsaved text live in the browser. All writing decisions come from the server. */
export function createLiveAdapter(): WorkspaceAdapter {
  let local: Local = { bookId: "", page: "books", storyTab: "人物", person: "", drafts: {} };
  try { const saved = JSON.parse(localStorage.getItem(KEY) || "null"); if (saved?.drafts) local = { ...local, ...saved }; } catch { /* usable without storage */ }
  const query = new URLSearchParams(location.search);
  if (query.has("book")) { local.bookId = query.get("book") || ""; local.selectedChapter = undefined; }
  if (query.has("chapter")) { const chapter = Number(query.get("chapter")); local.selectedChapter = Number.isInteger(chapter) && chapter > 0 ? chapter : undefined; }
  if (["books", "planning", "writing", "story"].includes(query.get("page") || "")) local.page = query.get("page") as Local["page"];
  let state: Workspace = { ...local, books: [], showNew: false, storageWarning: "", mode: "live", loading: true };
  let disposed = false, requestNumber = 0, sending = false;
  const listeners = new Set<() => void>();
  const controllers = new Set<AbortController>();
  const publish = () => { state = { ...state }; listeners.forEach(fn => fn()); };
  function persist() {
    try { localStorage.setItem(KEY, JSON.stringify(local)); }
    catch { state.storageWarning = "浏览器未能保存编辑草稿，请先保存改稿再离开页面。"; }
  }
  function apply(next: Workspace, preservePage = true) {
    const chosen = next.books.find(b => b.id === (preservePage ? local.bookId : next.bookId)) || next.books.find(b => !b.archived);
    local.bookId = chosen?.id || "";
    if (!preservePage && next.page) local.page = next.page;
    if (!chosen && local.page !== "books") local.page = "books";
    state = { ...next, ...local, mode: "live", loading: false, sending, lastCompleted: state.lastCompleted, error: state.error, storageWarning: next.storageWarning || state.storageWarning, showNew: state.showNew };
    state.books = next.books.map(book => {
      const draft = local.drafts[book.id];
      if (draft && draft.candidate && draft.candidate !== book.candidate?.key) state.storageWarning = "你保留了较早候选的编辑草稿。较新的候选已在服务器保存；请复制需要保留的文字，再结束旧草稿编辑，重新修改当前候选。";
      return draft && book.candidate ? { ...book, candidate: { ...book.candidate, editorDraft: draft.text } } : book;
    });
    state.recoveredDraft = !chosen?.candidate ? local.drafts[local.bookId]?.text : undefined;
    persist(); publish();
  }
  async function request<T = Workspace>(url: string, init?: RequestInit): Promise<T> {
    const controller = new AbortController(); controllers.add(controller);
    const timeout = setTimeout(() => controller.abort(), 60000);
    try {
      let response: Response;
      try { response = await fetch(`${apiBase()}${url}`, { ...init, signal: controller.signal, cache: "no-store" }); }
      catch { throw new Error("暂时无法连接工作区，请重新连接。编辑草稿已保留；请勿反复提交，先查看上次操作结果。"); }
      const value = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof value?.detail?.message === "string" ? value.detail.message : "暂时无法完成操作。已保存的内容仍在，请刷新后重试。");
      return value as T;
    } finally { clearTimeout(timeout); controllers.delete(controller); }
  }
  async function refresh() {
    if (sending || disposed) return;
    const n = ++requestNumber;
    const params = new URLSearchParams();
    if (local.bookId) params.set("book_id", local.bookId);
    if (local.selectedChapter) params.set("chapter", String(local.selectedChapter));
    try { const next = await request(`/author-workspace?${params}`); if (!disposed && n === requestNumber) apply(next); }
    catch (error) { if (!disposed && n === requestNumber) { state = { ...state, loading: false, error: error instanceof Error ? error.message : "暂时无法连接工作区。" }; publish(); } }
  }
  function navigate() {
    state = { ...state, ...local, error: "" }; persist(); publish();
    const params = new URLSearchParams({ page: local.page }); if (local.bookId) params.set("book", local.bookId); if (local.selectedChapter) params.set("chapter", String(local.selectedChapter));
    history.replaceState(null, "", `/workspace?${params}`); void refresh();
  }
  async function executeRemote(command: Command) {
    if (sending) return;
    const bookId = command.type === "archive" ? command.id : local.bookId;
    const book = state.books.find(b => b.id === bookId);
    const name = command.type;
    const action = command.type === "create" ? state.actions?.create : book?.actions?.[name];
    if (!command.type.startsWith("planning-action:") && !action?.enabled) { state.error = action?.reason || "当前还不能执行这个操作，请刷新查看。"; publish(); return; }
    const draft = local.drafts[bookId];
    const token = "token" in command ? command.token : command.type === "save-draft" && draft ? draft.token : action!.token;
    sending = true; ++requestNumber; state = { ...state, sending: true, error: "" }; publish();
    try {
      const next = await request<{bookId?: string; message?: string}>("/author-workspace/commands", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bookId, command, token }) });
      if (disposed) return;
      if (command.type === "save-draft") delete local.drafts[bookId];
      if (["plan", "future", "requirements", "ai-edit"].includes(command.type)) { try { localStorage.removeItem(`novelflow.author.dialog:${bookId}:${command.type === "ai-edit" ? "ai" : command.type}`); } catch { /* server saved; browser copy may remain */ } }
      if (command.type === "create") { state.showNew = false; try { localStorage.removeItem("novelflow.author.new-book"); } catch { /* optional cached form */ } }
      if (command.type === "create") { local.bookId = next.bookId || local.bookId; local.page = "planning"; }
      if (["next-volume", "direction", "prepare-plan"].includes(command.type)) local.page = "planning";
      if (["adopt", "generate", "confirm", "retry-next"].includes(command.type)) local.page = "writing";
      local.selectedChapter = undefined;
      state = { ...state, ...local, lastCompleted: { bookId, type: command.type, token }, storageWarning: next.message || "" };
      const params = new URLSearchParams({ page: local.page }); if (local.bookId) params.set("book", local.bookId); if (local.selectedChapter) params.set("chapter", String(local.selectedChapter));
      history.replaceState(null, "", `/workspace?${params}`); persist(); publish();
    } catch (error) { if (!disposed) { state.error = error instanceof Error ? error.message : "操作未完成，编辑内容已保留。"; publish(); } }
    finally { sending = false; if (!disposed) { state.sending = false; publish(); void refresh(); } }
  }
  // A slow read must finish before polling again, otherwise requestNumber
  // invalidates every response and the author sees a permanently busy book.
  const timer = setInterval(() => { if (!controllers.size && state.books.some(b => b.busy)) void refresh(); }, 2200);
  void refresh();
  return {
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }, snapshot: () => state,
    execute(command) {
      if (command.type === "refresh") { state.error = ""; void refresh(); return; }
      if (command.type === "navigate") {
        if (command.page === "settings") { location.assign(state.links?.settings || "/config"); return; }
        local.page = command.page; local.bookId = command.bookId || local.bookId; local.selectedChapter = command.chapter; navigate(); return;
      }
      if (command.type === "resume") { const b = state.books.find(b => b.id === command.id); local.bookId = command.id; local.page = b?.candidate ? "writing" : !b?.planAdopted ? "planning" : "writing"; local.selectedChapter = undefined; navigate(); return; }
      if (command.type === "new-form") { state.showNew = command.open; publish(); return; }
      if (command.type === "story-tab") { local.storyTab = command.tab; navigate(); return; }
      if (command.type === "person") { local.person = command.name; navigate(); return; }
      if (command.type === "draft") {
        const book = state.books.find(b => b.id === local.bookId); if (!book?.candidate) return;
        const prior = local.drafts[local.bookId];
        local.drafts[local.bookId] = { text: command.text, token: prior?.token || book.actions?.["save-draft"]?.token || "", candidate: prior?.candidate || book.candidate.key };
        state.books = state.books.map(b => b.id === book.id ? { ...b, candidate: { ...book.candidate!, editorDraft: command.text } } : b);
        persist(); publish(); return;
      }
      if (command.type === "discard-local-draft") { delete local.drafts[local.bookId]; persist(); void refresh(); return; }
      if (command.type === "reset" || command.type === "scenario") return;
      void executeRemote(command);
    },
    dispose() { disposed = true; clearInterval(timer); controllers.forEach(c => c.abort()); listeners.clear(); },
  };
}
