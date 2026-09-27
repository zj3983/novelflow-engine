/** Author-facing data only. Real adapters must obtain these decisions from the server. */
export type PageName = "books" | "planning" | "writing" | "story" | "settings";
export type StoryTab = "人物" | "世界规则" | "伏笔线索" | "创作要求";
export interface ProductAction { command?: string; token: string; label: string; enabled: boolean; reason?: string }
export interface Evidence { text: string; chapter?: number }
export interface Volume { number: number; title: string; start?: number; end?: number; goal?: string; label?: string }
export interface StoryEntry { title: string; text: string; chapter?: number }
export interface Person { name: string; role: string; description: string; facts: Evidence[]; performance: string[] }
export interface Chapter { number: number; title: string; body: string }
export interface Concern { message: string; suggestion: string; quote?: string; chapter?: number }
export interface Candidate extends Chapter {
  key?: string; concerns?: Concern[]; canAcceptSuggestion?: boolean;
  label: string; canConfirm: boolean; needsCheck: boolean; checking: boolean;
  concern?: Concern; pastDrafts: { body: string; label: string }[]; editorDraft?: string;
}
export interface PlanningPart { title: string; description?: string; paragraphs: string[]; issues: Concern[]; actions: ProductAction[]; form?: { title: string; description?: string; fields: {key:string;value:string;label:string;type:string;required?:boolean}[]; actions: ProductAction[] } }
export interface Book {
  planningParts?: PlanningPart[];
  actions?: Record<string, ProductAction>; volumes?: Volume[]; upcoming?: { number: number; title: string; summary: string }[];
  directions?: { id?: string; text: string; label?: string }[]; ending?: string; connections?: Evidence[];
  people?: Person[]; world?: StoryEntry[]; foreshadow?: StoryEntry[]; reminders?: string[];
  id: string; title: string; genre: string; idea: string; targetWords?: number; chapterWords?: number;
  requirements: string; future: string; direction?: string; plan: string; planAdopted: boolean;
  planningVolume: number; chapters: Chapter[]; candidate?: Candidate; archived?: boolean;
  notice: string; busy: boolean; canRetry: boolean; nextVolume: boolean;
}
export interface Workspace {
  recoveredDraft?: string; mode?: "demo" | "live"; loading?: boolean; sending?: boolean; error?: string;
  actions?: Record<string, ProductAction>; genres?: { value: string; label: string }[]; links?: { settings?: string; import?: string };
  books: Book[]; bookId: string; page: PageName; selectedChapter?: number;
  showNew: boolean; storyTab: StoryTab; person: string; storageWarning: string;
}
export type Command =
  | { type: "navigate"; page: PageName; bookId?: string; chapter?: number }
  | { type: "new-form"; open: boolean }
  | { type: "create"; title: string; genre: string; idea: string; targetWords: number; chapterWords: number; requirements: string }
  | { type: "resume"; id: string }
  | { type: "direction"; text: string; id?: string }
  | { type: `planning-action:${string}`; values?: Record<string,string>; token: string }
  | { type: "prepare-plan" | "sync-plan" | "refresh-plan" | "continue-plan" | "complete-volume" | "retry-next" | "discard" }
  | { type: "prepare-directions" } | { type: "refresh" }
  | { type: "plan"; text: string }
  | { type: "adopt" } | { type: "generate" } | { type: "next-volume" }
  | { type: "discard-local-draft" }
  | { type: "draft"; text: string } | { type: "save-draft"; text: string }
  | { type: "review" } | { type: "ai-edit"; instruction: string }
  | { type: "confirm"; continue: boolean } | { type: "accept-suggestion" }
  | { type: "story-tab"; tab: StoryTab } | { type: "person"; name: string }
  | { type: "future"; text: string } | { type: "requirements"; text: string }
  | { type: "archive"; id: string; archived: boolean }
  | { type: "reset" } | { type: "scenario"; scenario: "generation-failure" | "review-failure" | "next-failure" | "volume-end" | "soft-suggestion" };
export interface WorkspaceAdapter {
  subscribe(listener: () => void): () => void;
  snapshot(): Workspace;
  execute(command: Command): void;
  dispose(): void;
}
