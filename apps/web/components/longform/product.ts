/** Author-facing data only. Real adapters must obtain these decisions from the server. */
import type { ImportedWorldBlueprint } from "../../lib/api";

export type PageName = "books" | "planning" | "writing" | "story" | "settings";
export type StoryTab = "人物" | "世界规则" | "伏笔线索" | "创作要求";
export interface ProductAction { command?: string; token: string; label: string; enabled: boolean; reason?: string; requiresConfirmation?: boolean }
export interface Evidence { text: string; chapter?: number }
export interface Volume { number: number; title: string; start?: number; end?: number; goal?: string; mainConflict?:string; characterChanges?:string[]; endingTurn?:string; label?: string }
export interface StoryEntry { title: string; text: string; chapter?: number }
export interface ForeshadowItem extends StoryEntry { key: string; statusLabel?: string; firstChapter?: number; lastTouchedChapter?: number; resolvedChapter?: number; payoffPlan?: string; editable?: boolean }
export interface Person { name: string; role: string; description: string; facts: Evidence[]; performance: string[]; stableProfile?: Record<string, string>; currentState?: Record<string, string>; futurePlans?: string[] }
export interface CharacterCardView extends Person { editableProfile: Record<string, any>; actions: { save: ProductAction; completePortrait: ProductAction } }
export interface WorldEntry { id: string; title: string; text: string; editable: boolean }
export interface WorldSection { id: string; title: string; entries: WorldEntry[]; save: ProductAction }
export interface Relationship { source: string; target: string; relationship: string; history: string; historyEditable?: boolean; currentState: string; sharedInterestOrConflict: string; trust?: number | null; tension?: number | null; basisLabel?: string; evidenceChapter?: number | null }
export interface BookDetails {
  title: string; synopsis: string; synopsisTags: string[]; coverAvailable: boolean; targetWords?: number; targetChapterWords?: number;
  confirmedChapterCount?: number; confirmedWordCount?: number | null; chapterCountComplete?: boolean; currentChapter?: number;
  synopsisStatusLabel?: string; coverStatusLabel?: string; novelTypeId?: string; novelTypeOptions?: {id:string;label:string}[];
  writingStyle?: string; writingStyleOptions?: string[];
  actions?: { saveType: ProductAction; saveStyle: ProductAction; saveSynopsis: ProductAction; generateSynopsis: ProductAction; generateCover: ProductAction };
}
export interface DynamicWorld { currentSnapshot?: {chapter?:number|null;entries:{label:string;value:string}[]}; availableChapters?:{number:number;title:string}[]; selectedChapter?:number; chapterRecord?: Record<string, any> | null; preparationInformation?:{sourceChapter:number;entries:{text:string;whoCanKnow?:string}[]} | null; emptyMessage?:string }
export interface WritingTemplate { id: string; title: string; purpose: string; applicabilityLabel: string; activeForBook: boolean; content: string; placeholders: {syntax:string;label:string}[]; sourceLabel:string; usesBookOverride:boolean; lastCheck?:Record<string, any>; actions:{saveProject:ProductAction;saveGlobal:ProductAction;restoreGlobal?:ProductAction|null;check:ProductAction;deepCheck:ProductAction} }
export interface WritingAbilities { packs:{id:string;name:string;description:string;available:boolean;selected:boolean;modules:{id:string;title:string;purpose:string;selected:boolean}[]}[]; selectionModeLabel:string; save:ProductAction; managementLabel:string }
export interface DissectionReport { statusLabel:string; chapterNumber?:number; chapterTitle?:string; sections:{title:string;items:string[]}[] }
export interface DissectionView { modeLabel:string; selectedChapter?:number|null; candidateSourceToken?:string|null; statusLabel:string; report?:DissectionReport|null; candidateReport?:DissectionReport|null; reportIsReadOnly:boolean; actions:{inspectChapter:ProductAction;inspectReference:ProductAction;inspectCandidate:ProductAction} }
export interface Chapter { number: number; title: string; body: string }
export interface Concern { message: string; suggestion: string; quote?: string; chapter?: number }
export interface Candidate extends Chapter {
  key?: string; concerns?: Concern[]; canAcceptSuggestion?: boolean;
  label: string; canConfirm: boolean; needsCheck: boolean; checking: boolean;
  concern?: Concern; pastDrafts: { body: string; label: string }[]; editorDraft?: string;
}
export interface PlanningProjection { editable:boolean; graphManaged?:boolean; overall:{direction:string;endingGoal:string;previousConnection:string;editable?:boolean}; currentVolume:number; volumes:{number:number;title:string;startChapter?:number;endChapter?:number;goal:string;mainConflict:string;characterChanges:string[];endingTurn:string;statusLabel:string;editable?:boolean}[]; upcomingChapters:{number:number;title:string;goal:string;conflict:string;progression:string;foreshadowing:string[];editable?:boolean}[]; authorReminders:string[] }
export interface PlanningEditPatch {
  overall?: { direction:string; endingGoal:string };
  volumes?: { number:number; title:string; goal:string; mainConflict:string; characterChanges:string[]; endingTurn:string }[];
  upcomingChapters?: { number:number; title:string; goal:string; conflict:string; progression:string }[];
}
export type PlanningEditScope = "overall" | `volume:${number}` | `chapter:${number}`;
export interface RecycleBinBook { id:string; title:string; actions:Record<string,ProductAction> }
export interface Book {
  actions?: Record<string, ProductAction>; volumes?: Volume[]; upcoming?: { number: number; title: string; summary?: string; goal?:string; conflict?:string; progression?:string; foreshadowing?:string[] }[];
  directions?: { id?: string; text: string; label?: string }[]; ending?: string; connections?: Evidence[];
  people?: Person[]; world?: StoryEntry[]; foreshadow?: StoryEntry[]; reminders?: string[];
  worldCatalogs?: Pick<ImportedWorldBlueprint, "equipment_cards" | "monster_profiles">;
  id: string; title: string; genre: string; idea: string; targetWords?: number; chapterWords?: number;
  bookDetails?: BookDetails; characterCardsView?: {items:CharacterCardView[]}; relationshipView?:{items:Relationship[];save:ProductAction};
  worldSections?:WorldSection[]; dynamicWorld?:DynamicWorld; foreshadowingView?:{items:ForeshadowItem[];save:ProductAction};
  writingTemplatesView?:{templates:WritingTemplate[]}; writingAbilitiesView?:WritingAbilities; dissectionView?:DissectionView;
  planning?:PlanningProjection; confirmedWorldFacts?:Evidence[];
  worldEnrichment?:{statusLabel:string;message:string;canStart:boolean;action:ProductAction;manualEditsRemainAuthoritative:boolean};
  requirements: string; future: string; direction?: string; plan: string; planAdopted: boolean;
  planningVolume: number; chapters: Chapter[]; candidate?: Candidate; archived?: boolean;
  notice: string; busy: boolean; canRetry: boolean; nextVolume: boolean;
}
export interface Workspace {
  lastCompleted?: { bookId: string; type: string; token?: string };
  recoveredDraft?: string; mode?: "demo" | "live"; loading?: boolean; sending?: boolean; error?: string;
  actions?: Record<string, ProductAction>; genres?: { value: string; label: string }[]; links?: { settings?: string; import?: string };
  books: Book[]; recycleBin?:RecycleBinBook[]; bookId: string; page: PageName; selectedChapter?: number;
  showNew: boolean; storyTab: StoryTab; person: string; storageWarning: string;
}
export type Command =
  | { type: "navigate"; page: PageName; bookId?: string; chapter?: number; storyTab?: StoryTab }
  | { type: "new-form"; open: boolean }
  | { type: "create"; title: string; genre: string; idea: string; targetWords: number; chapterWords: number; requirements: string }
  | { type: "resume"; id: string }
  | { type: "direction"; text: string; id?: string }
  | { type: `planning-action:${string}`; values?: Record<string,string>; token: string }
  | { type: "prepare-plan" | "sync-plan" | "refresh-plan" | "continue-plan" | "complete-volume" | "retry-next" | "discard" }
  | { type: "prepare-directions" } | { type: "refresh" }
  | { type: "plan"; text?: string; scope?:PlanningEditScope; patch?: PlanningEditPatch; token?: string }
  | { type: "adopt" } | { type: "generate" } | { type: "next-volume" }
  | { type: "discard-local-draft" }
  | { type: "draft"; text: string } | { type: "save-draft"; text: string }
  | { type: "review" } | { type: "ai-edit"; instruction: string; token?: string; dissectionSourceToken?: string }
  | { type: "confirm"; continue: boolean } | { type: "accept-suggestion" }
  | { type: "story-tab"; tab: StoryTab } | { type: "person"; name: string }
  | { type: "future"; text: string; token?: string } | { type: "requirements"; text: string; token?: string }
  | { type: "archive"; id: string; archived: boolean }
  | { type: "trash"; confirm: true }
  | { type: "restore-trashed"; id: string }
  | { type: "delete-trashed"; id: string; confirmTitle: string }
  | { type: "reset" } | { type: "scenario"; scenario: "generation-failure" | "review-failure" | "next-failure" | "volume-end" | "soft-suggestion" };
export interface WorkspaceAdapter {
  subscribe(listener: () => void): () => void;
  snapshot(): Workspace;
  execute(command: Command): void;
  dispose(): void;
}
