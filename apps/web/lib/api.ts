export type CreateStoryRequest = {
  story_id: string;
  outline: string;
  genre: string;
  style: string;
  agent_settings?: {
    mode: "LLM-assisted";
    global_model: string;
    character_model: string;
    director_model: string;
    writer_model: string;
    memory_model: string;
    temperature: string | number;
    new_character_policy: "Director review" | "Auto-approve named candidates" | "Manual review";
  };
  characters?: Array<{
    name: string;
    role: string;
    game_id?: string;
    goals: string[];
    frozen: boolean;
    lifecycle_state?: "proposed" | "active" | "rejected" | "frozen";
    last_proposed_chapter?: number;
    last_approved_chapter?: number;
    introduced_by?: string;
    relationships?: Record<
      string,
      {
        target: string;
        trust: number;
        tension: number;
        bond: string;
      }
    >;
  }>;
};

export type GamePanel = {
  game_id?: string;
  level?: number | string | null;
  class_path?: string;
  exp?: string;
  hp?: string;
  mp?: string;
  attributes?: Record<string, unknown>;
  skills?: string[];
  equipment?: Record<string, unknown>;
  inventory?: Record<string, unknown>;
  currency?: string;
  quests?: Record<string, unknown>;
  risk?: Record<string, unknown>;
  updated_chapter?: number;
};

export type CharacterPortrait = {
  temperament?: { outward_impression?: string; core_traits?: string[]; inner_contradiction?: string; values?: string[]; bottom_line?: string };
  psychology?: { desire?: string; fear?: string; blind_spot?: string; defense?: string; shame_point?: string };
  behavior?: { normal_mode?: string; pressure_mode?: string; conflict_response?: string; failure_response?: string; decision_tendency?: string };
  emotion?: { triggers?: string[]; restraint_style?: string; loss_of_control?: string; mannerisms?: string[] };
  social?: { strangers?: string; friends?: string; authority?: string; enemies?: string };
  voice?: { common_words?: string[]; sentence_habit?: string; avoided_topics?: string[]; lying_style?: string; anger_style?: string; relaxed_style?: string };
  growth?: { initial_flaw?: string; invariants?: string[]; change_conditions?: string[]; stage_direction?: string };
  writing_limits?: string[];
};

export type AgentSettings = NonNullable<CreateStoryRequest["agent_settings"]>;
export type RuntimeStrategySettings = AgentSettings;

export type RuntimeProvider = string;
export type RuntimeStageName = "planner" | "writer";

export type RuntimeProviderAccount = {
  api_key: string;
  base_url: string;
  custom_models: string[];
  codex_command: string;
};

export type RuntimeStageBinding = { provider_id: string; model: string };

export type RuntimeProviderDefinition = {
  provider_id: string;
  name: string;
  protocol: "openai_compatible" | "anthropic" | "gemini" | "codex_cli" | "antigravity_cli";
  default_base_url: string;
  planner_models: string[];
  writer_models: string[];
  requires_api_key: boolean;
  base_url_editable: boolean;
  help_text: string;
};

export type RuntimeProviderCatalog = {
  schema_version: "provider-catalog/v1";
  providers: RuntimeProviderDefinition[];
};

export type RuntimeImageSettings = {
  enabled: boolean;
  api_key: string;
  base_url: string;
  model: string;
};

export type RuntimeSettings = {
  schema_version: "runtime-config/v2";
  accounts: Record<string, RuntimeProviderAccount>;
  stages: Record<RuntimeStageName, RuntimeStageBinding>;
  image: RuntimeImageSettings;
  temperature: number;
  new_character_policy: AgentSettings["new_character_policy"];
};

export type SynopsisAsset = {
  tags: string[];
  body: string;
  format: string;
  updated_at: string;
};

export type CoverAsset = {
  prompt?: string;
  image_version?: string;
  base_image_version?: string;
  rendered_from_base_version?: string;
  width?: number;
  height?: number;
  mime_type?: string;
  model?: string;
  rendered_title?: string;
  updated_at?: string;
  schema_version?: "cover/v1";
  base_path?: "assets/cover-base.png";
  rendered_path?: "assets/cover.png";
};

export type PublishingAssets = {
  schema_version: "publishing-assets/v1";
  synopsis: SynopsisAsset | null;
  cover: CoverAsset | null;
};

export type CoverGenerationResponse =
  | { status: "prompt_ready"; reason: "image_provider_not_configured"; cover: CoverAsset | null }
  | { status: "ready"; cover: CoverAsset | null };

export class PublishingApiError extends Error {
  readonly phase?: "prompt" | "image";
  readonly promptSaved: boolean;
  readonly cover?: CoverAsset | null;

  constructor(code: string, detail: { phase?: "prompt" | "image"; prompt_saved?: boolean; cover?: CoverAsset | null }) {
    super(code);
    this.name = "PublishingApiError";
    this.phase = detail.phase;
    this.promptSaved = detail.prompt_saved === true;
    this.cover = detail.cover;
  }
}

export type RuntimeConnectionResult = {
  ok: boolean;
  provider: string;
  stage: RuntimeStageName;
  model: string;
  protocol: RuntimeProviderDefinition["protocol"];
  diagnosis: string;
  message: string;
};

export type RuntimeDiscoveredModel = {
  model_id: string;
  compatibility: "supported" | "unsupported" | "unknown";
  endpoint: string;
  reason: string;
};

export type RuntimeModelDiscoveryResult = {
  provider: string;
  protocol: RuntimeProviderDefinition["protocol"];
  models: RuntimeDiscoveredModel[];
};

export type CodexCLIInfo = {
  available: boolean;
  command: string;
  version: string;
  models: string[];
  latest_version: string;
  update_status: "current" | "available" | "unknown";
};

export type NovelTypeRulebook = {
  progression_rules: string[];
  economy_rules: string[];
  quest_rules: string[];
  faction_rules: string[];
  panel_rules: string[];
  chapter_formula: string[];
  forbidden_breaks: string[];
};

export type NovelOutlineTemplate = {
  schema_version: "novel-outline-template/v1";
  overall: {
    required_fields: string[];
    long_term_lines: string[];
    instructions: string[];
  };
  arc: {
    required_fields: string[];
    minimum_arc_count: number;
    maximum_chapter_span: number;
    instructions: string[];
  };
  chapter: {
    required_fields: string[];
    opening_window_size: number;
    instructions: string[];
  };
};

export type NovelType = {
  id: string;
  name: string;
  description: string;
  keywords: string[];
  core_promises: string[];
  ledger_fields: string[];
  rulebook: NovelTypeRulebook;
  quality_checks: string[];
  trope_templates: Array<Record<string, unknown>>;
  power_system_template?: Record<string, unknown>;
  outline_template?: NovelOutlineTemplate;
  builtin: boolean;
};

export type NovelTypeWriteRequest = Omit<NovelType, "builtin">;
export type NovelTypeRecord = NovelType;
export type NovelTypeWritePayload = NovelTypeWriteRequest;

export type GenerationJobStatus = "queued" | "running" | "completed" | "failed";

export type GenerationJobStep = {
  at?: string;
  message: string;
  status?: "running" | "done" | "error" | "queued" | string;
  stage?: string;
  source?: string;
  artifact?: Record<string, unknown> | string | number | boolean | null | (string | number | boolean | Record<string, unknown>)[];
};

export type GenerationJobResponse = {
  job_id: string;
  story_id: string;
  status: GenerationJobStatus;
  progress: string;
  steps: GenerationJobStep[];
  chapter_number: number | null;
  error: string;
  created_at: string;
  updated_at: string;
};

export type GenerationJobSummary = Omit<GenerationJobResponse, "steps">;

export type GenerationJobHistoryResponse = {
  schema_version: "file-generation-job-history/v1" | string;
  items: GenerationJobSummary[];
};

export type CandidateDraft = {
  schema_version?: string;
  candidate_id: string;
  project_id: string;
  chapter_number: number;
  chapter_title: string;
  body: string;
  context_snapshot_id: string;
  quality_report: Record<string, unknown>;
  revision_history: Record<string, unknown>[];
  submission_payload?: Record<string, unknown>;
  status: "pending" | "confirmed" | "discarded" | string;
  created_at: string;
  confirmed_at: string;
};

export type CandidateListResponse = {
  schema_version: string;
  items: CandidateDraft[];
};

export type ProjectAutomationJobStatus = "queued" | "running" | "completed" | "paused" | "failed";

export type ProjectAutomationJobPhase =
  | "queued"
  | "environment"
  | "generating"
  | "reviewing"
  | "revising"
  | "completed"
  | "paused"
  | "failed";

export type ProjectAutomationJobResponse = {
  job_id: string;
  project_id: string;
  story_id: string;
  status: ProjectAutomationJobStatus;
  phase: ProjectAutomationJobPhase;
  progress: string;
  chapter_number: number | null;
  revision_attempts: number;
  max_revisions: number;
  final_action: string;
  review_provider: "local" | "openclaw" | string;
  error: string;
  created_at: string;
  updated_at: string;
};

export type ProjectAutomationJobRequest = {
  max_revisions?: number;
  review_provider?: "local" | "self" | "codex";
  include_body?: boolean;
  openclaw_agent?: string;
  openclaw_timeout?: number;
};

export const CONFIG_AGENT_SETTINGS_STORAGE_KEY = "novel-autogrowth-engine.agent-settings";

export const AGENT_RUNTIME_TARGETS = ["global", "character", "director", "writer", "memory"] as const;

export type AgentRuntimeEntry = {
  source: "idle" | "llm" | "fallback";
  provider: string;
  model: string;
  fallback_reason: string;
  last_run_chapter: number;
};

export type AgentRuntimeState = {
  planner: AgentRuntimeEntry;
  writer: AgentRuntimeEntry;
  memory: AgentRuntimeEntry;
  recent_events: string[];
};

export type SimulationStatus = {
  ok?: boolean;
  mode?: "full" | "degraded";
  fallback_agents?: Array<"planner" | "writer" | "memory">;
  recent_events?: string[];
  agents?: Partial<Record<"planner" | "writer" | "memory", AgentRuntimeEntry>>;
  world_pulse?: {
    latest?: Record<string, unknown>;
    history?: Array<Record<string, unknown>>;
  };
  visibility_inbox?: Array<Record<string, unknown>>;
};

// ── Outline types ────────────────────────────────────────────────

export type ChapterOutline = {
  chapter_number: number;
  chapter_title: string;
  summary: string;
  key_characters: string[];
  primary_conflict: string;
  cadence: "urgent" | "measured" | "breathing";
  word_count_estimate: number;
  arc_phase: string;
};

export type NovelOutlineResponse = {
  story_id: string;
  genre: string;
  style: string;
  total_chapters: number;
  chapters: ChapterOutline[];
  overall_arc: string;
  act_breaks: Array<{ act: number; start: number; end: number; theme: string }>;
  notes: string;
  created_at: string;
  updated_at: string;
  saved: boolean;
};

// ── World Bible types ─────────────────────────────────────────────

export type PowerSystem = {
  name: string;
  description: string;
  levels: string[];
  rules: string[];
  limitations: string[];
};

export type WorldLocation = {
  name: string;
  description: string;
  type: string;
  importance: number;
  connections: string[];
};

export type Faction = {
  name: string;
  description: string;
  type: string;
  goals: string[];
  allies: string[];
  enemies: string[];
  notable_members: string[];
};

export type WorldBibleResponse = {
  story_id: string;
  world_name: string;
  overview: string;
  power_system: PowerSystem;
  locations: WorldLocation[];
  factions: Faction[];
  world_facts: string[];
  timeline_events: Array<{ chapter: number; event: string }>;
  cultural_notes: string[];
  glossary: Record<string, string>;
  updated_at: string;
};

export type WorldBibleRequest = {
  world_name?: string;
  overview?: string;
  power_system?: Partial<PowerSystem>;
  locations?: Partial<WorldLocation>[];
  factions?: Partial<Faction>[];
  world_facts?: string[];
  timeline_events?: Array<{ chapter: number; event: string }>;
  cultural_notes?: string[];
  glossary?: Record<string, string>;
};

// ── Novel Status types ────────────────────────────────────────────

export type NovelStatusType = "draft" | "outlining" | "writing" | "reviewing" | "completed" | "paused";

export type NovelStatusResponse = {
  story_id: string;
  status: NovelStatusType;
  total_chapters_planned: number;
  total_chapters_written: number;
  total_word_count: number;
  last_written_chapter: number;
  last_written_at: string;
  created_at: string;
  updated_at: string;
};

export type ReviewSection = {
  reviewer?: string;
  role?: string;
  pass?: boolean;
  verdict?: string;
  scores?: Record<string, number>;
  metrics?: Record<string, number>;
  issues?: Array<string | { type?: string; reason?: string; suggestion?: string }>;
  revision_plan?: string[];
  ai_flavor_review?: ReviewSection;
  cold_reader_review?: ReviewSection;
  reader_agent_review?: ReviewSection;
  editor_agent_review?: ReviewSection;
  reviewer_agent_review?: ReviewSection;
  length_review?: LengthReview;
  cuts?: Array<{
    type?: string;
    target_text?: string;
    reason?: string;
    suggestion?: string;
  }>;
  hits?: Record<string, unknown>;
};

export type LengthReview = {
  pass?: boolean;
  body_chars?: number;
  min_chars?: number;
  max_chars?: number;
  issues?: string[];
};

export type ReviewStatus = "passed" | "warning" | "blocked" | string;

export type ReviewFinding = {
  code: string;
  category: "hard" | "dialogue" | "ai_flavor" | "prose" | string;
  blocking: boolean;
  severity: "blocking" | "advisory" | string;
  message: string;
  suggestion: string;
  source: string;
  evidence?: string;
};

export type SimplifiedReview = {
  schema_version: "review-result/v2" | "simplified-review/v1" | string;
  agent_label?: string;
  status?: ReviewStatus;
  pass: boolean;
  has_hard_errors: boolean;
  needs_revision?: boolean;
  summary?: string;
  categories: {
    hard: { label: string; count: number };
    dialogue: { label: string; count: number };
    prose: { label: string; count: number };
    ai_flavor: { label: string; count: number };
  };
  issues: Array<{
    code?: string;
    category: "hard" | "dialogue" | "prose" | "ai_flavor" | string;
    severity: "blocking" | "advisory" | string;
    blocking?: boolean;
    message: string;
    suggestion: string;
    source?: string;
    evidence?: string;
  }>;
  revision_plan?: string[];
  total_issues: number;
  diagnostics?: Record<string, unknown>;
};

export type ShuangwenReviewChecks = {
  goal: string[];
  pressure: string[];
  information_gap: string[];
  counterattack: string[];
  payoff: string[];
  reaction: string[];
  ending_hook: string[];
  cliches: string[];
};

export type ShuangwenSkillReview = {
  schema_version: "skill-review/v1";
  skill_id: "commercial-shuangwen";
  executed: true;
  status: "passed" | "warning";
  summary: string;
  checks: ShuangwenReviewChecks;
  issues: string[];
  runtime?: string;
  model?: string;
  trace_id?: string;
};

export type ChapterBundle = {
  chapter_number: number;
  body: string;
  chapter_title?: string;
  cadence?: string;
  chapter_intent?: {
    chapter_title?: string;
    cadence?: string;
    next_focus?: string;
    primary_conflict?: Record<string, unknown>;
    secondary_conflict?: Record<string, unknown>;
    approved_new_characters?: string[];
    deferred_characters?: string[];
    rejected_characters?: string[];
  };
  character_moves?: Array<{
    name?: string;
    goal?: string;
    action?: string;
    priority?: number;
    emotion?: string;
  }>;
  memory_constraints?: {
    must_keep_facts?: string[];
    unresolved_threads?: string[];
    protected_characters?: string[];
    protected_foreshadowing?: Array<{ text?: string; status?: string; first_chapter?: number }>;
    author_constraints?: string[];
    current_focus?: string;
    conflict_anchor?: string;
    event_guardrail?: string;
  };
  event_plan?: {
    chapter_number?: number;
    chapter_title?: string;
    turn?: string;
    pivot?: string;
    collision?: string;
    ordered_actions?: Array<{ name?: string; goal?: string; action?: string; priority?: number }>;
    exposition_beats?: string[];
    npc_beats?: string[];
    quest_beats?: string[];
    location_beats?: string[];
    world_reactions?: string[];
    stakes?: string;
    next_focus?: string;
    author_constraints?: string[];
  };
  chapter_seed?: Record<string, unknown>;
  simulation_plan?: Record<string, unknown>;
    world_events?: Array<{
      event_id?: string;
      template_id?: string;
      actor?: string;
      action?: string;
      target?: string;
    location?: string;
    cause?: string;
    visible_to?: string[];
    consequences?: string[];
    state_delta?: Record<string, unknown>;
    prose_priority?: number;
    }>;
    scene_cards?: Array<{
      scene_id?: string;
      template_id?: string;
      location?: string;
      pov?: string;
    purpose?: string;
    conflict?: string;
    source_events?: string[];
    must_show?: string[];
    must_not_explain?: string[];
    state_delta?: Record<string, unknown>;
    ending_pressure?: string;
  }>;
  conflict_summary?: {
    summary?: string;
    stakes?: string;
    primary_conflict?: Record<string, unknown>;
    secondary_conflict?: Record<string, unknown>;
    approved_new_characters?: string[];
    deferred_characters?: string[];
    rejected_characters?: string[];
  };
  event_beat?: {
    turn?: string;
    pivot?: string;
  };
  simulation_status?: SimulationStatus;
  character_cards?: unknown[];
  foreshadowing?: unknown[];
  next_outline?: string;
  chapter_summary?: {
    chapter_number: number;
    summary: string;
    facts: string[];
    unresolved_threads: string[];
  };
  quality_report?: {
    ok: boolean;
    issues: string[];
    downstream_rewrite_required?: boolean;
    downstream_chapter_number?: number;
    revision_safety?: RevisionSafetyReport;
    review_result?: SimplifiedReview;
    writing_review?: ReviewSection;
    critical_review?: ReviewSection;
    hook_review?: ReviewSection;
    pacing_review?: ReviewSection;
    beats_review?: ReviewSection;
    ai_flavor_review?: ReviewSection;
    length_review?: LengthReview;
    cold_reader_review?: ReviewSection;
    reader_agent_review?: ReviewSection;
    editor_agent_review?: ReviewSection;
    reviewer_agent_review?: ReviewSection;
    simplified_review?: SimplifiedReview;
    skill_reviews?: Record<string, ShuangwenSkillReview | undefined>;
  };
  updated_story?: unknown;
};

export function downstreamRewriteNotice(
  report?: { downstream_rewrite_required?: boolean; downstream_chapter_number?: number } | null,
): string {
  if (!report?.downstream_rewrite_required) return "";
  return report.downstream_chapter_number
    ? `第${report.downstream_chapter_number}章需要同步重写`
    : "后续章节需要同步重写";
}

export type RevisionSafetyReport = {
  reviewer?: string;
  accepted?: boolean;
  selected?: "candidate" | "original" | string;
  reason?: string;
  original_score?: number;
  candidate_score?: number;
  original_chars?: number;
  candidate_chars?: number;
};

export type CharacterStateLayer = {
  current?: Record<string, unknown>;
  recent_changes?: Array<{ chapter?: number; fact: string }>;
};

export type StoryResponse = {
  story_id: string;
  outline: string;
  genre: string;
  style: string;
  current_chapter: number;
  agent_settings: AgentSettings;
  agent_runtime: AgentRuntimeState;
  author_constraints?: string[];
  writing_lessons?: string[];
  world_facts?: string[];
  world_snapshot?: Record<string, unknown>;
  continuity_facts?: Array<{
    text: string;
    source_chapter?: number;
    status?: string;
    updated_chapter?: number;
  }>;
  parent_story_id?: string | null;
  branched_from_chapter?: number | null;
  characters: Array<{
    name: string;
    role: string;
    game_id?: string;
    game_panel?: GamePanel;
    current_state?: CharacterStateLayer | string;
    real_state?: CharacterStateLayer;
    game_state?: CharacterStateLayer;
    character_tier?: string;
    first_appearance?: number | null;
    identity_profile?: CharacterIdentityProfile;
    background_profile?: CharacterBackgroundProfile;
    current_life_profile?: CharacterCurrentLifeProfile;
    story_drive?: CharacterStoryDrive;
    dialogue_examples?: string[];
    relationship_notes?: CharacterRelationshipNote[];
    character_type?: string;
    core_motivation?: string;
    behavior_logic?: string;
    interaction_mode?: string;
    poison_points?: string[];
    social_profile?: Record<string, unknown>;
    psychological_profile?: Record<string, unknown>;
    moral_profile?: Record<string, unknown>;
    personality_portrait?: CharacterPortrait;
    performance_profile?: Record<string, unknown>;
    story_function?: string;
    chapter_role?: string;
    goals: string[];
    memory?: string[];
    secrets?: string[];
    current_emotion?: string;
    location?: string;
    frozen: boolean;
    lifecycle_state: "proposed" | "active" | "rejected" | "frozen";
    last_proposed_chapter: number;
    last_approved_chapter: number;
    introduced_by: string;
    relationships?: Record<
      string,
      {
        target: string;
        trust: number;
        tension: number;
        bond: string;
      }
    >;
  }>;
  history: ChapterBundle[];
};

export type ChapterIndexEntry = {
  chapter_number: number;
  chapter_title: string;
  body_chars: number;
  summary: string;
  next_focus: string;
  has_quality_report: boolean;
  has_simulation: boolean;
};

export type FileStoryOverview = Omit<StoryResponse, "history"> & {
  chapter_count: number;
  total_body_chars: number;
  chapters: ChapterIndexEntry[];
  storage_source: "file";
};

export type StorySummary = {
  story_id: string;
  current_chapter: number;
  parent_story_id?: string | null;
  branched_from_chapter?: number | null;
};

export type ImportedWorldEntry = {
  name: string;
  description?: string;
  [key: string]: unknown;
};

export type ImportedRelationshipEdge = {
  id?: string;
  source: string;
  target: string;
  relation_type?: string;
  bond?: string;
  origin?: string;
  history?: string;
  long_term_conflict_boundary?: string;
  current_state?: string;
  shared_interest_or_conflict?: string;
  tension?: number;
  trust?: number;
  source_knowledge?: string[];
  target_knowledge?: string[];
  private_notes?: string[];
  status?: "active" | "ended" | "hidden";
  first_chapter?: number;
  last_changed_chapter?: number;
  changes?: Array<{ chapter_number?: number; summary?: string; trust?: number | null; tension?: number | null }>;
};

export type ImportedGenrePlugin = {
  id: string;
  name: string;
  core_promises?: string[];
  ledger_fields?: string[];
  quality_checks?: string[];
};

export type ImportedLivingWorld = {
  daily_routines?: string[];
  economy?: {
    resource_flow?: string[];
    pressure_points?: string[];
  };
  power_structure?: {
    dominant_groups?: string[];
    control_methods?: string[];
  };
  information_network?: {
    channels?: string[];
    rumors?: string[];
  };
  location_functions?: ImportedWorldEntry[];
  timeline?: string[];
  reaction_rules?: string[];
};

export type ImportedWorldSystems = {
  material_base?: string[];
  institutions?: ImportedWorldEntry[];
  social_order?: string[];
  conflict_engines?: string[];
  causal_loops?: ImportedWorldEntry[];
};

export type ImportedNpcEntry = ImportedWorldEntry & {
  role?: string;
  location?: string;
  services?: string[];
  agenda?: string;
  knowledge_limit?: string;
  quest_hooks?: string[];
  voice?: string;
};

export type ImportedNpcSystem = {
  npcs?: ImportedNpcEntry[];
  rules?: string[];
};

export type ImportedQuestChain = ImportedWorldEntry & {
  stages?: string[];
  npc_links?: string[];
  risk?: string;
  reward?: string;
};

export type ImportedQuestNetwork = {
  quest_types?: string[];
  active_chains?: ImportedQuestChain[];
  reward_rules?: string[];
  failure_costs?: string[];
};

export type ImportedServerRuntime = {
  phase?: string;
  channels?: string[];
  announcement_rules?: string[];
  gm_rules?: string[];
  anti_cheat_rules?: string[];
  instance_rules?: string[];
};

export type ImportedMapZone = ImportedWorldEntry & {
  resources?: string[];
  npcs?: string[];
  player_density?: string;
  risk?: string;
  outputs?: string[];
};

export type ImportedMapEcology = {
  zones?: ImportedMapZone[];
  rules?: string[];
};

export type ImportedOpeningChapter = {
  purpose?: string;
  must_include?: string[];
  exposition_beats?: string[];
  ending_hook?: string;
};

export type ImportedOpeningArc = {
  golden_three_chapters?: {
    chapter_1?: ImportedOpeningChapter;
    chapter_2?: ImportedOpeningChapter;
    chapter_3?: ImportedOpeningChapter;
    [key: string]: ImportedOpeningChapter | undefined;
  };
  chapter_beats?: Array<{
    chapter?: number;
    title?: string;
    required_payoff?: string;
    ending_hook?: string;
  }>;
};

export type ImportedCharacterProfile = {
  name: string;
  game_id?: string;
  current_state?: CharacterStateLayer | string;
  real_state?: CharacterStateLayer;
  game_state?: CharacterStateLayer;
  game_panel?: GamePanel;
  role?: string;
  character_tier?: string;
  first_appearance?: number | null;
  identity_profile?: CharacterIdentityProfile;
  background_profile?: CharacterBackgroundProfile;
  current_life_profile?: CharacterCurrentLifeProfile;
  story_drive?: CharacterStoryDrive;
  dialogue_examples?: string[];
  relationship_notes?: CharacterRelationshipNote[];
  character_type?: string;
  core_motivation?: string;
  behavior_logic?: string;
  interaction_mode?: string;
  poison_points?: string[];
  social_profile?: Record<string, unknown>;
  psychological_profile?: Record<string, unknown>;
  moral_profile?: Record<string, unknown>;
  story_function?: string;
  chapter_role?: string;
  motivation?: string;
  personality?: string;
  speech_style?: string;
  goals?: string[];
  secrets?: string[];
  conflict_hooks?: string[];
};

export type ImportedEquipmentEvidence = {
  chapter?: number;
  quote?: string;
  confidence?: "confirmed" | "rumor" | "unknown";
};

export type ImportedEquipmentCard = {
  id?: string;
  name: string;
  aliases?: string[];
  equipment_type: string;
  slot?: string;
  rarity?: string;
  required_level?: string;
  class_restrictions?: string[];
  base_attributes?: Record<string, string>;
  special_effects?: string[];
  skills?: string[];
  durability?: string;
  source?: string;
  current_owner?: string;
  current_location?: string;
  first_appearance_chapter?: number;
  last_update_chapter?: number;
  status?: string;
  description?: string;
  lore?: string;
  lore_status?: "confirmed" | "rumor" | "unknown";
  related_characters?: string[];
  related_factions?: string[];
  set_name?: string;
  set_lore?: string;
  evidence?: ImportedEquipmentEvidence[];
};

export type ImportedWorldBlueprint = {
  writing_style?: string;
  premise?: string;
  world_rules?: string[];
  power_system?: string[];
  power_system_spec?: PowerSystemSpec;
  locations?: ImportedWorldEntry[];
  factions?: ImportedWorldEntry[];
  current_arc?: string;
  constraints?: string[];
  progression_rules?: string[];
  economy_rules?: string[];
  quest_rules?: string[];
  reality_bridge_rules?: string[];
  faction_rules?: string[];
  panel_rules?: string[];
  chapter_formula?: string[];
  forbidden_breaks?: string[];
  volume_plan?: Record<string, unknown>;
  longform_framework?: Record<string, unknown>;
  genre_plugins?: ImportedGenrePlugin[];
  genre_plugin_ids?: string[];
  opening_arc?: ImportedOpeningArc;
  world_systems?: ImportedWorldSystems;
  living_world?: ImportedLivingWorld;
  npc_system?: ImportedNpcSystem;
  quest_network?: ImportedQuestNetwork;
  server_runtime?: ImportedServerRuntime;
  map_ecology?: ImportedMapEcology;
  relationship_graph?: ImportedRelationshipEdge[];
  monster_profiles?: ImportedMonsterProfile[];
  equipment_cards?: ImportedEquipmentCard[];
};

export type PowerSystemAttribute = {
  name?: string;
  effect?: string;
};

export type PowerSystemStage = {
  name?: string;
  level?: number;
  entry?: string;
  change?: string;
  failure?: string;
};

export type ClassAdvancementTier = {
  level?: number;
  name?: string;
  purpose?: string;
  common_requirements?: string[];
  failure_rule?: string;
};

export type ClassAdvancementOption = {
  name?: string;
  role?: string;
  requirements?: string[];
  transfer_task?: string;
  ability_changes?: string[];
  new_resources?: string[];
  equipment_permissions?: string[];
  failure_consequence?: string;
  next_options?: string[];
};

export type ClassAdvancementNode = {
  level?: number;
  tier_name?: string;
  options?: ClassAdvancementOption[];
};

export type PowerSystemPath = {
  name?: string;
  role?: string;
  core_resource?: string;
  core_attributes?: string[];
  weapons?: string[];
  armor?: string[];
  combat_loop?: string;
  strengths?: string[];
  weaknesses?: string[];
  skill_categories?: string[];
  branches?: string[];
  transfer_task?: string;
  advancement?: string[];
  advancement_tree?: ClassAdvancementNode[];
};

export type AttributeAllocationRule = {
  mode?: "free";
  points_per_level?: number;
  starting_level?: number;
  base_attributes?: Record<string, number>;
  allow_carry?: boolean;
  respec_rule?: string;
};

export type PowerSystemSpec = {
  name?: string;
  origin?: string[];
  attributes?: PowerSystemAttribute[];
  paths?: PowerSystemPath[];
  stages?: PowerSystemStage[];
  skills?: string[];
  equipment?: string[];
  resources?: string[];
  advancement?: string[];
  costs?: string[];
  counters?: string[];
  boundaries?: string[];
  social_impact?: string[];
  visibility?: string[];
  continuity_ledger?: string[];
  attribute_allocation?: AttributeAllocationRule;
  class_advancement_tiers?: ClassAdvancementTier[];
};

export type ImportedMonsterProfile = {
  id?: string;
  name: string;
  category?: string;
  rank?: string;
  level?: string;
  hp?: string;
  attack_mode?: string;
  skills?: string[];
  traits?: string[];
  habitats?: string[];
  drops?: string[];
  first_appearance_chapter?: number;
  status?: string;
};

export type CreateProjectRequest = {
  project_id: string;
  title: string;
  source_path?: string;
  seed_outline?: string;
  world_summary?: string;
  current_focus?: string;
  author_constraints?: string[];
  world_blueprint?: ImportedWorldBlueprint;
  character_profiles?: ImportedCharacterProfile[];
  relationship_graph?: ImportedRelationshipEdge[];
  enabled_skill_ids?: string[];
  enabled_skill_module_ids?: string[];
  pipeline_stage?: ProjectPipelineStage;
  active_story_id?: string;
};

export type ProjectPipelineStage =
  | "draft"
  | "idea_pending"
  | "direction_ready"
  | "outlining"
  | "imported"
  | "world_ready"
  | "environment_ready"
  | "chapter_planning"
  | "writing"
  | "simulating"
  | "paused"
  | "completed";

export type ProjectStatus = "draft" | "outlining" | "writing" | "reviewing" | "simulating" | "paused" | "completed" | string;
export type ProjectLifecycle = "active" | "archived" | "trashed";
export type SkillModuleSelectionMode = "legacy_all" | "explicit";

export type UpdateProjectRequest = {
  title?: string;
  source_path?: string;
  seed_outline?: string;
  world_summary?: string;
  current_focus?: string;
  author_constraints?: string[];
  world_blueprint?: ImportedWorldBlueprint;
  character_profiles?: ImportedCharacterProfile[];
  relationship_graph?: ImportedRelationshipEdge[];
  enabled_skill_ids?: string[];
  enabled_skill_module_ids?: string[];
  status?: ProjectStatus;
  pipeline_stage?: ProjectPipelineStage;
  active_story_id?: string;
};

export type ProjectSummary = {
  project_id: string;
  title: string;
  status: ProjectStatus;
  pipeline_stage?: ProjectPipelineStage;
  active_story_id: string;
  current_chapter: number;
  source_path: string;
  storage_source?: "sqlite" | "file";
  project_lifecycle?: ProjectLifecycle;
  archived_at?: string;
  trashed_at?: string;
};

export type ProjectResponse = {
  project_id: string;
  title: string;
  source_path: string;
  seed_outline: string;
  world_summary: string;
  current_focus: string;
  author_constraints: string[];
  world_blueprint?: ImportedWorldBlueprint;
  character_profiles?: ImportedCharacterProfile[];
  relationship_graph?: ImportedRelationshipEdge[];
  enabled_skill_ids?: string[];
  enabled_skill_module_ids?: string[] | null;
  skill_module_selection_mode?: SkillModuleSelectionMode;
  status: ProjectStatus;
  pipeline_stage?: ProjectPipelineStage;
  active_story_id: string;
  branches: StorySummary[];
  storage_source?: "sqlite" | "file";
  publishing_assets: PublishingAssets;
  project_lifecycle?: ProjectLifecycle;
  archived_at?: string;
  trashed_at?: string;
  continuation?: { start_after_chapter: number } | null;
};

export type NewFileProjectRequest = {
  mode: "blank" | "inspiration";
  title: string;
  novel_type_id: string;
  idea: string;
  narrative_enhancement_ids?: string[];
};

export type NewFileProjectResponse = ProjectResponse & {
  next_path: string;
};

export type StoryCoreCard = {
  schema_version: "story-core/v1";
  title: string;
  logline: string;
  protagonist_profile: string;
  inciting_incident: string;
  protagonist_goal: string;
  main_conflict: string;
  failure_stakes: string;
  growth_path: string;
  excitement_point: string;
  target_audience: string;
  reader_promise: string;
  ending_direction: string;
  core_advantage: {
    name: string;
    type: string;
    ability: string;
    growth_rule: string;
    limits: string;
    early_payoff: string;
  };
  central_mystery: {
    surface_anomaly: string;
    hidden_truth: string;
    reality_impact: string;
    reveal_path: string[];
  };
  initial_drive: {
    immediate_need: string;
    trigger: string;
    short_term_goal: string;
    failure_stakes: string;
    long_term_transition: string;
  };
  source_direction_id: string;
};

export type OpeningDirection = Omit<StoryCoreCard, "schema_version" | "source_direction_id"> & {
  id: string;
  hook: string;
  opening_promise: string;
  primary_trope_id?: string | null;
};

export type OpeningSetup = {
  brief: {
    schema_version: "opening-brief/v1";
    mode: "blank" | "inspiration";
    novel_type_id: string;
    idea: string;
    working_title: string;
  };
  directions: OpeningDirection[];
  selected_id: string;
  pipeline_stage: ProjectPipelineStage;
  next_path: string;
};

export type OutlineStrategy = "observe" | "expand" | "close";

export type OutlineExtensionGate = {
  continue_route: string;
  close_route: string;
};

export type ProjectOutlineOverall = {
  story: string;
  theme_statement: string;
  foreground_story: string;
  background_story: string;
  book_objective: string;
  ending_image: string;
  protagonist_goal: string;
  main_conflict: string;
  growth_path: string;
  ending_direction: string;
  core_ending_chapter: number;
  extension_ceiling_chapter: number;
  current_strategy: OutlineStrategy;
  ending_contract: string;
  core_selling_point: string;
  long_term_lines: Array<{
    name: string;
    purpose: string;
    start_state: string;
    progression_steps: string[];
    final_payoff: string;
  }>;
  planned_arc_count: number;
  planned_length: number;
  expansion_route: string;
  closing_route: string;
  positioning: {
    protagonist_profile: string;
    inciting_incident: string;
    failure_stakes: string;
    excitement_point: string;
    target_audience: string;
    reader_promise: string;
  };
  protagonist_drive: {
    immediate_need: string;
    trigger: string;
    short_term_goal: string;
    failure_stakes: string;
    long_term_transition: string;
  };
  core_advantage: {
    name: string;
    type: string;
    ability: string;
    growth_rule: string;
    limits: string;
    early_payoff: string;
  };
  central_mystery: {
    surface_anomaly: string;
    hidden_truth: string;
    reality_impact: string;
    reveal_path: string[];
  };
};

export type ProjectOutlineArc = {
  id: string;
  title: string;
  start_chapter: number;
  end_chapter: number;
  pacing_stage_id?: string;
  goal: string;
  obstacle: string;
  payoff: string;
  emotional_curve: string;
  key_results: string[];
  hook_plan: string;
  irreversible_change: string;
  end_state: string;
  stage_antagonist: string;
  long_term_antagonist_traces: string[];
  game_line_payoff: string;
  reality_line_payoff: string;
  extension_gate: OutlineExtensionGate;
  active_long_term_lines: string[];
  core_loop: string;
  escalations: string[];
  midpoint_turn: string;
  climax: string;
  relationship_changes: string[];
  foreshadowing_in: string[];
  foreshadowing_out: string[];
  next_arc_entry: string;
  is_final_arc?: boolean;
  story_nodes?: Array<{
    start_chapter: number;
    end_chapter: number;
    objective: string;
    pressure: string;
    turn: string;
    payoff: string;
    next_effect: string;
  }>;
};

export type CharacterIdentityProfile = {
  aliases?: string[];
  gender?: string;
  age?: number | null;
  birthplace?: string;
  origin?: string;
  current_identity?: string;
  occupation?: string;
  affiliation?: string;
};

export type CharacterBackgroundProfile = {
  family?: string;
  upbringing?: string;
  education_or_training?: string;
  formative_events?: string[];
  arrival_reason?: string;
};

export type CharacterCurrentLifeProfile = {
  residence?: string;
  livelihood?: string;
  economic_state?: string;
  resources_and_ability?: string;
  authority_scope?: string;
  immediate_problem?: string;
};

export type CharacterStoryDrive = {
  long_term_goal?: string;
  immediate_goal?: string;
  motivation?: string;
  failure_stakes?: string;
  hidden_matters?: string[];
  main_conflict_reason?: string;
};

export type CharacterRelationshipNote = {
  target: string;
  relation_type?: string;
  history?: string;
  current_attitude?: string;
  shared_interest_or_conflict?: string;
  known_facts?: string[];
  unknown_facts?: string[];
};

export type ProjectChapterOutline = {
  chapter_number: number;
  title: string;
  goal: string;
  obstacle: string;
  action: string;
  turn: string;
  payoff: string;
  ending_hook: string;
  cast: string[];
  opponent_response: string;
  emotional_change: string;
  gain_or_loss: string;
};

export type RollingOutlineScene = {
  location: string;
  action: string;
  result: string;
};

export type RollingOutlineCastMember = {
  name: string;
  role?: string;
  character_tier?: string;
  this_chapter_role?: string;
};

export type RollingOutlineChapter = {
  chapter_number: number;
  title: string;
  chapter_goal: string;
  core_conflict: string;
  cast: RollingOutlineCastMember[];
  scenes: RollingOutlineScene[];
  gain: string;
  cost: string;
  foreshadowing: string[];
  hook: string;
  state_delta: string;
  source?: string;
};

export type RollingOutline = {
  schema_version: "rolling-outline/v1";
  chapters: RollingOutlineChapter[];
};

export type VolumeWorkflowStatus =
  | "volume_missing"
  | "volume_plan_ready"
  | "detail_partial"
  | "detail_complete";

export type VolumeWorkflowResponse = {
  schema_version: "volume-workflow/v1";
  target_chapter: number;
  status: VolumeWorkflowStatus;
  detail_status: string;
  next_action:
    | "design_next_volume"
    | "generate_volume_detail"
    | "generate_prose";
  volume_id: string | null;
  volume_range: [number, number] | null;
};

export type VolumeDetailGenerationResponse = {
  schema_version: "volume-detail-generation/v1";
  volume_id: string;
  volume_range: [number, number];
  detail_status: "complete" | "partial";
  completed_chapters: number;
  total_chapters: number;
  batches: Array<{
    id: string;
    start_chapter: number;
    end_chapter: number;
    status: string;
    error?: string;
  }>;
};

export type VolumeDesignResponse = {
  schema_version: "volume-design/v1";
  status: "volume_plan_ready";
  next_action: "generate_volume_detail";
  volume_id: string;
  volume_range: [number, number];
  created: boolean;
  outline?: ProjectOutline;
};

export type ProjectOutline = {
  schema_version: "project-outline/v1";
  source: "saved" | "legacy";
  overall: ProjectOutlineOverall;
  arcs: ProjectOutlineArc[];
  chapters: ProjectChapterOutline[];
};

export type ProjectOutlineUpdate = Omit<ProjectOutline, "source">;

export type OutlineGenerationMode = "initial" | "regenerate" | "extend";
export type OutlineGenerationPhaseId = "outline_foundation" | "character_roster" | "chapter_window";
export type OutlineGenerationCheckpoint = {
  id: OutlineGenerationPhaseId;
  status: "waiting" | "running" | "completed" | "failed";
  started_at?: string;
  completed_at?: string;
  error?: string;
  has_payload?: boolean;
  payload?: Record<string, unknown>;
};
export type OutlineGenerationCheckpointResponse = {
  fingerprint?: string;
  updated_at?: string;
  phases: OutlineGenerationCheckpoint[];
};

export type OutlineExtensionReadinessSection =
  | "overall"
  | "arcs"
  | "chapters"
  | "characters"
  | "world";
export type OutlineExtensionReadinessIssue = {
  code: string;
  message: string;
  section: OutlineExtensionReadinessSection;
  names?: string[];
};
export type OutlineExtensionReadinessResponse = {
  schema_version: "outline-extension-readiness/v1";
  ready: boolean;
  current_chapter: number;
  next_chapter_numbers: number[];
  blockers: OutlineExtensionReadinessIssue[];
  warnings: OutlineExtensionReadinessIssue[];
};

// Plan rule: the continuation import bootstrap is a six-phase
// pipeline. The wizard and the workbench both poll the same
// status surface; the type names are exported so callers can
// branch on the literal ids without a stringly-typed hack.
export type ContinuationBootstrapPhaseId =
  | "source_analysis"
  | "outline_foundation"
  | "character_roster"
  | "world_context"
  | "chapter_window"
  | "readiness_check";

export type ContinuationBootstrapPhaseStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "adopted";

export type ContinuationBootstrapPhase = {
  id: ContinuationBootstrapPhaseId;
  status: ContinuationBootstrapPhaseStatus;
  artifact: Record<string, unknown>;
  error: string;
};

export type ContinuationBootstrapStatus = {
  schema_version: "continuation-bootstrap/v1";
  input_fingerprint: string;
  status: "running" | "ready" | "failed";
  phases: ContinuationBootstrapPhase[];
};

export type ContinuationBootstrapStartResponse = {
  status: "queued" | "ready";
  checkpoint: ContinuationBootstrapStatus;
};

export async function startContinuationBootstrap(
  projectId: string,
): Promise<ContinuationBootstrapStartResponse> {
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/continuation-bootstrap`,
    { method: "POST" },
    60000,
  )) as ContinuationBootstrapStartResponse;
}

export async function fetchContinuationBootstrap(
  projectId: string,
): Promise<ContinuationBootstrapStatus> {
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/continuation-bootstrap`,
    { method: "GET" },
    60000,
  )) as ContinuationBootstrapStatus;
}

export type GeneratedOutlinePlanResponse = {
  schema_version: "generated-outline-plan/v1";
  mode: OutlineGenerationMode;
  outline: ProjectOutlineUpdate;
  characters: StoryCharacter[];
  source: "generated";
};

export type ForeshadowingStatus = "open" | "reinforced" | "resolved" | "expired";

export type ForeshadowingEntry = {
  text: string;
  first_chapter: number;
  last_touched_chapter: number;
  status: ForeshadowingStatus;
  payoff_plan: string;
  resolved_chapter: number | null;
};

export type ForeshadowingResponse = {
  items: ForeshadowingEntry[];
  version: string;
};

export type AgentReviseRequest = {
  chapter_number?: number | null;
  instructions: string[];
  include_body?: boolean;
};

export type ChapterDirectionOption = {
  id: string;
  name: string;
  recommended?: boolean;
  chapter_goal: string;
  reader_promise: string;
  main_scenes: string[];
  wow_beat: string;
  ending_hook: string;
  state_delta: string;
  risk: string;
};

/** @deprecated Round 8 removed the three-card direction picker. The shape
 * is kept on the writing packet for backward compatibility, but the
 * ``options`` list is always empty. New code should use
 * ``next_chapter_outline`` + ``rolling_fill`` on ``CodexWritingPacket``.
 */
export type ChapterDirectionOptions = {
  schema_version: "chapter-direction-options/v1";
  chapter_number: number;
  recommended_id: string;
  selection_rule?: string;
  options: ChapterDirectionOption[];
};

export type RollingOutlineStatus = "present" | "missing" | "failed" | "legacy";

export type RollingOutlinePayload = {
  chapter_number?: number;
  title?: string;
  chapter_goal?: string;
  core_conflict?: string;
  cast?: Array<{ name?: string; role?: string }>;
  scenes?: Array<{ location?: string; action?: string; result?: string }>;
  gain?: string;
  cost?: string;
  foreshadowing?: string[];
  hook?: string;
  state_delta?: Record<string, unknown>;
  source?: string;
};

export type RollingFillInfo = {
  status: RollingOutlineStatus;
  chapter_number: number;
  source: "rolling" | "legacy" | "manual" | null;
  filled_chapter_numbers: number[];
  error: string;
};

export type CodexWritingPacket = {
  schema_version: "codex-writing-packet/v1" | "file-writing-packet/v1";
  chapter_number: number;
  chapter_title?: string;
  goal?: string;
  target_chars?: {
    min: number;
    max: number;
  };
  story?: Record<string, unknown>;
  protagonist?: Record<string, unknown>;
  event_plan?: Record<string, unknown>;
  plot_simulation?: Record<string, unknown>;
  scene_cards?: Array<Record<string, unknown>>;
  hard_locks?: string[];
  style_rules?: string[];
  author_constraints?: string[];
  world_facts?: string[];
  continuity?: Record<string, unknown>;
  submission_contract?: Record<string, unknown>;
  /** @deprecated kept for backward compatibility; options list is
   * always empty. New code should use ``next_chapter_outline`` and
   * ``rolling_fill`` instead. */
  chapter_direction_options?: ChapterDirectionOptions;
  next_chapter_outline?: RollingOutlinePayload | null;
  next_chapter_outline_source?: "rolling" | "legacy" | "manual" | null;
  rolling_fill?: RollingFillInfo | null;
};

export type SkillPackModuleSummary = {
  module_id: string;
  title: string;
  description?: string;
  summary?: string;
  purposes?: string[];
  relative_path?: string;
  content?: string;
};

export type SkillPackSummary = {
  schema_version: "skill-pack/v1" | string;
  skill_id: string;
  name: string;
  version: string;
  author?: string;
  description?: string;
  module_count: number;
  modules: SkillPackModuleSummary[];
  root_skill?: string;
  narrative_enhancement_status?: {
    status: "available" | "unavailable" | "incomplete" | "unknown" | string;
    reason: string;
    missing_module_ids: string[];
    purpose_mismatches?: Array<{
      module_id: string;
      required_purposes: string[];
      actual_purposes: string[];
      missing_purposes: string[];
      unexpected_purposes: string[];
    }>;
  };
};

export type UninstallSkillPackResponse = {
  skill_id: string;
  pack: SkillPackSummary;
  affected_project_count: number;
  affected_project_ids: string[];
};

export type PromptPreviewEntry = {
  key: string;
  title: string;
  agent: string;
  stage: string;
  source: string;
  description?: string;
  content: string;
  chars: number;
  module_keys?: string[];
  genre_stage_profile?: string;
  genre_stage_modules?: string[];
};

export type PromptPreviewResponse = {
  schema_version: "file-project-prompt-preview/v1" | "project-prompt-preview/v1";
  project_id: string;
  chapter_number: number;
  chapter_title?: string;
  source: string;
  has_chapter: boolean;
  module_catalog?: PromptModuleSpec[];
  stage_modules?: Record<string, string[]>;
  modules?: PromptPreviewEntry[];
  prompts: PromptPreviewEntry[];
};

export type PromptTemplateEntry = {
  key: string;
  title: string;
  stage: string;
  content: string;
  required_variables: string[];
  version: string;
  source: "global_default" | "global_override" | "project_override";
  applicability?: "all" | "game_only" | "non_game_only";
  active_for_project?: boolean;
};

export type PromptTemplatesResponse = {
  schema_version: "prompt-templates/v1" | "project-prompt-templates/v1";
  project_id?: string;
  templates: PromptTemplateEntry[];
};

export type PromptAuditMode = "template" | "final_call";

export type PromptAuditIssue = {
  code: string;
  title: string;
  evidence: string;
  location: string;
  suggestion: string;
  estimated_reduction_characters: number;
};

export type PromptAuditResult = {
  schema_version: "prompt-audit/v1";
  mode: PromptAuditMode;
  content_sha256: string;
  summary: {
    characters: number;
    lines: number;
    estimated_redundant_characters: number;
    estimated_reduction_percent: number;
    sections: Array<{
      title: string;
      characters: number;
      percent: number;
    }>;
  };
  must_fix: PromptAuditIssue[];
  suggestions: PromptAuditIssue[];
  passed_checks: string[];
};

export type PromptAuditRuntime = {
  provider: string;
  model: string;
  elapsed_seconds: number;
  prompt_characters: number;
};

export type DeepPromptAuditResult = PromptAuditResult & {
  runtime: PromptAuditRuntime;
};

export type PromptAuditRequest = {
  mode: PromptAuditMode;
  content: string;
  template_key?: string;
  required_variables?: string[];
};

export type PromptContextEntry = PromptPreviewEntry & {
  available: boolean;
  reason?: string;
};

export type PromptContextResponse = {
  schema_version: "file-project-prompt-context/v1";
  project_id: string;
  chapter_number: number;
  chapter_title?: string;
  source: string;
  modules: PromptContextEntry[];
};

export type PromptCallSummary = {
  call_id: string;
  project_id?: string;
  chapter_number: number;
  stage: string;
  agent: string;
  attempt: number;
  status: "started" | "succeeded" | "failed" | string;
  provider?: string;
  model?: string;
  temperature?: number | null;
  started_at?: string;
  finished_at?: string;
  elapsed_seconds?: number | null;
  prompt_chars?: number;
  output_chars?: number;
  error?: string;
  genre_stage_profile?: string;
  genre_stage_modules?: string[];
};

export type PromptCallDetail = PromptCallSummary & {
  user_prompt: string;
  system_prompt?: string;
  module_keys: string[];
  template_key?: string;
  template_source?: string;
  template_version?: string;
  output_summary?: string;
};

export type PromptCallListResponse = {
  schema_version: "prompt-call-list/v1";
  project_id: string;
  chapter_number?: number | null;
  calls: PromptCallSummary[];
};

export type PromptModuleSpec = {
  key: string;
  title: string;
  owner: string;
  stage: string;
  purpose: string;
  description: string;
  depends_on: string[];
  role: string;
  replaceable: boolean;
};

export type AgentReviewResponse = {
  schema_version: "agent-review/v1";
  project: {
    project_id?: string;
    title?: string;
    active_story_id?: string;
  };
  story: {
    story_id?: string;
    current_chapter?: number;
  };
  chapter: Partial<ChapterBundle> & {
    chapter_number: number;
    body_chars?: number;
  };
  review?: {
    quality?: ChapterBundle["quality_report"];
    writing_review?: NonNullable<ChapterBundle["quality_report"]>["writing_review"];
  };
  recommendation?: {
    action?: "continue" | "revise" | string;
    reason?: string;
    must_fix?: string[];
    revision_plan?: string[];
  };
};

export type AgentRevisionResponse = {
  schema_version: "agent-revision/v1";
  project: {
    project_id?: string;
    title?: string;
    active_story_id?: string;
  };
  story: {
    story_id?: string;
    current_chapter?: number;
  };
  chapter: Partial<ChapterBundle> & {
    chapter_number: number;
    body_chars?: number;
  };
  review?: {
    quality?: ChapterBundle["quality_report"];
    writing_review?: NonNullable<ChapterBundle["quality_report"]>["writing_review"];
  };
  revision?: {
    changed?: boolean;
    previous_body_chars?: number;
    revised_body_chars?: number;
    instructions?: string[];
    source?: string;
  };
};

export type DeleteStoryResponse = {
  deleted: boolean;
  story_id: string;
};

export type StoryCharacter = StoryResponse["characters"][number];

export async function fetchFileProjectCharacters(projectId: string): Promise<StoryCharacter[]> {
  return (await tryFetchJson(`${apiBase()}/file-projects/${encodeURIComponent(projectId)}/characters`, {
    method: "GET",
  })) as StoryCharacter[];
}

export async function updateFileProjectCharacter(
  projectId: string,
  characterName: string,
  patch: Partial<StoryCharacter>,
): Promise<StoryCharacter> {
  return (await tryFetchJson(
    `${apiBase()}/file-projects/${encodeURIComponent(projectId)}/characters/${encodeURIComponent(characterName)}`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    },
  )) as StoryCharacter;
}

export async function completeFileProjectCharacterPortrait(projectId: string, characterName: string): Promise<StoryCharacter> {
  return (await tryFetchJson(
    `${apiBase()}/file-projects/${encodeURIComponent(projectId)}/characters/${encodeURIComponent(characterName)}/complete-portrait`,
    { method: "POST" },
  )) as StoryCharacter;
}

export type BookImportScanRequest = {
  source_path: string;
};

export type BookImportScanReport = {
  source_path: string;
  exists: boolean;
  missing_required_files: string[];
  missing_optional_files: string[];
  unusable_required_files: string[];
  empty_files: string[];
  present_files: string[];
  warnings: string[];
  can_bootstrap: boolean;
};

export type BookImportBootstrapRequest = {
  source_path: string;
};

export type BookImportBootstrapResponse = {
  report: BookImportScanReport;
  draft: {
    source_path: string;
    title?: string;
    outline: string;
    summary?: string;
    world_summary?: string;
    current_focus?: string;
    author_constraints?: string[];
    world_blueprint?: ImportedWorldBlueprint;
    character_profiles?: ImportedCharacterProfile[];
    relationship_graph?: ImportedRelationshipEdge[];
    characters: Array<{
      name: string;
      goal?: string;
    }>;
  };
};

export type BookLibraryItem = {
  item_id: string;
  title: string;
  kind: string;
  filename: string;
  path: string;
  preview: string;
  content: string;
  chapter_number?: number | null;
  parsed_characters?: string[];
};

export type BookLibrarySection = {
  section_id: string;
  title: string;
  items: BookLibraryItem[];
};

export type BookLibraryCatalogResponse = {
  source_path: string;
  exists: boolean;
  can_bootstrap: boolean;
  sections: BookLibrarySection[];
};

export type BookDissectionReport = {
  schema_version: "book-dissection/v1";
  mode: "reference" | "project";
  summary: string;
  sections: Record<string, string[]>;
  meta?: Record<string, unknown>;
};

export type ContinuationConfidence = "confirmed" | "inferred";

export type ContinuationEvidenceRef = {
  chapter_id: string;
  excerpt_start: number;
  excerpt_end: number;
  quote: string;
};

export type ContinuationClaim = {
  claim: string;
  confidence: ContinuationConfidence;
  evidence: ContinuationEvidenceRef[];
};

export type ContinuationCharacterAnalysis = {
  name: string;
  role: string;
  summary: string;
  confidence: ContinuationConfidence;
  evidence: ContinuationEvidenceRef[];
  states: ContinuationClaim[];
  relationships: ContinuationClaim[];
};

export type ContinuationTimelineEvent = {
  text: string;
  sequence: string;
  confidence: ContinuationConfidence;
  evidence: ContinuationEvidenceRef[];
};

export type ContinuationHook = {
  text: string;
  status: "open" | "resolved" | "uncertain";
  confidence: ContinuationConfidence;
  evidence: ContinuationEvidenceRef[];
};

export type ContinuationAnalysis = {
  story_overview: string;
  characters: ContinuationCharacterAnalysis[];
  world: ContinuationClaim[];
  power_system: ContinuationClaim[];
  timeline: ContinuationTimelineEvent[];
  open_hooks: ContinuationHook[];
  style_profile: {
    narrative_voice: string;
    point_of_view: string;
    tense: string;
    pacing: string;
    dialogue_style: string;
    prose_features: string[];
    confidence: ContinuationConfidence;
    evidence: ContinuationEvidenceRef[];
  };
  continuation_start: {
    chapter_id: string;
    situation: string;
    guidance: string;
    constraints: ContinuationClaim[];
  };
  evidence_index: Record<string, ContinuationEvidenceRef[]>;
  needs_confirmation: Array<{ claim: string; source: string; reason: string }>;
};

export type ContinuationChapter = {
  chapter_id: string;
  number: number;
  title: string;
  body: string;
  source_name: string;
  source_start: number;
  source_end: number;
  fingerprint: string;
};

export type ContinuationScanResult = {
  source_path: string;
  source_kind: "file" | "directory";
  encoding: string;
  chapters: ContinuationChapter[];
  total_chars: number;
  warnings: string[];
  duplicate_groups: string[][];
  numbering_gaps: number[];
  can_analyze: boolean;
};

export type ContinuationImportSession = {
  schema_version: "continuation-import-session/v1";
  session_id: string;
  revision: number;
  status: "parsed" | "analyzing" | "ready" | "failed" | "cancelled";
  source_path: string;
  source_fingerprint: string;
  encoding: string;
  chapters: ContinuationChapter[];
  analysis: ContinuationAnalysis | Record<string, never>;
  analysis_progress: Record<string, unknown>;
  error: string;
  created_at: string;
  updated_at: string;
};

export type ContinuationSourceList = {
  current_path: string;
  directories: Array<{ name: string; path: string }>;
  files: Array<{ name: string; path: string }>;
};

export type ContinuationSettings = {
  start_after_chapter: number;
  fidelity: "faithful" | "adaptive";
  target_chars: number;
  direction: string;
  planned_chapters: number;
  must_preserve: string[];
  forbidden_content: string[];
  generate_outline: boolean;
  outline_chapters: number;
  novel_type_id: string;
};

export type CreatedContinuationProject = {
  project_id: string;
  title: string;
  source_path: string;
  current_chapter: number;
  storage_source: string;
  next_path: string;
  bootstrap_status: "queued" | "ready";
};

export type QuickContinuationResult = {
  session_id: string;
  project_id: string;
  project_route: string;
  job_id: string;
  job_status: string;
};

function apiBase() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
}

function isFileProjectId(value: string): boolean {
  return value.startsWith("file:");
}

function fileProjectPath(projectId: string): string {
  return `${apiBase()}/file-projects/${encodeURIComponent(projectId)}`;
}

function fileStoryPath(storyId: string): string {
  return `${apiBase()}/file-stories/${encodeURIComponent(storyId)}`;
}

type MockStory = {
  story_id: string;
  outline: string;
  genre: string;
  style: string;
  current_chapter: number;
  agent_settings: AgentSettings;
  agent_runtime: AgentRuntimeState;
  author_constraints: string[];
  world_facts?: string[];
  characters: StoryResponse["characters"];
  history: ChapterBundle[];
  initial_story: StoryResponse;
  parent_story_id?: string | null;
  branched_from_chapter?: number | null;
};

type MockProject = {
  project_id: string;
  title: string;
  source_path: string;
  seed_outline: string;
  world_summary: string;
  current_focus: string;
  author_constraints: string[];
  world_blueprint?: ImportedWorldBlueprint;
  character_profiles?: ImportedCharacterProfile[];
  relationship_graph?: ImportedRelationshipEdge[];
  enabled_skill_ids?: string[];
  enabled_skill_module_ids?: string[] | null;
  skill_module_selection_mode?: SkillModuleSelectionMode;
  status: ProjectStatus;
  pipeline_stage?: ProjectPipelineStage;
  active_story_id: string;
  branches: string[];
  storage_source?: "sqlite" | "file";
  publishing_assets: PublishingAssets;
  continuation?: { start_after_chapter: number } | null;
};

const MOCK_STORE_STORAGE_KEY = "novel-autogrowth-engine.stories";
const MOCK_PROJECT_STORE_STORAGE_KEY = "novel-autogrowth-engine.projects";
const MOCK_PROJECT_PREFERENCE_KEY = "novel-autogrowth-engine.projects-prefer-mock";

function loadMockStore(): Map<string, MockStory> {
  if (typeof window === "undefined") return new Map();
  try {
    const raw = window.localStorage.getItem(MOCK_STORE_STORAGE_KEY);
    if (!raw) return new Map();
    const parsed = JSON.parse(raw) as Array<[string, MockStory]>;
    return new Map(
      parsed.map(([storyId, story]) => [
        storyId,
        {
          ...story,
          agent_runtime: normalizeAgentRuntime(story.agent_runtime),
          initial_story: {
            ...story.initial_story,
            agent_runtime: normalizeAgentRuntime(story.initial_story?.agent_runtime),
          },
        },
      ]),
    );
  } catch {
    return new Map();
  }
}

function saveMockStore(store: Map<string, MockStory>) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(MOCK_STORE_STORAGE_KEY, JSON.stringify(Array.from(store.entries())));
  } catch {
    // Storage quota exceeded — keep running in memory.
  }
}

const mockStore = loadMockStore();

function prefersMockProjects(): boolean {
  return false;
}

function setMockProjectPreference(enabled: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(MOCK_PROJECT_PREFERENCE_KEY, enabled ? "1" : "0");
  } catch {
    // ignore localStorage write errors
  }
}

function loadMockProjectStore(): Map<string, MockProject> {
  if (typeof window === "undefined") return new Map();
  try {
    const raw = window.localStorage.getItem(MOCK_PROJECT_STORE_STORAGE_KEY);
    if (!raw) return new Map();
    const parsed = JSON.parse(raw) as Array<[string, MockProject]>;
    return new Map(parsed);
  } catch {
    return new Map();
  }
}

function saveMockProjectStore(store: Map<string, MockProject>) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(MOCK_PROJECT_STORE_STORAGE_KEY, JSON.stringify(Array.from(store.entries())));
  } catch {
    // Storage quota exceeded — keep running in memory.
  }
}

const mockProjectStore = loadMockProjectStore();
let mockRuntimeSettings: RuntimeSettings = defaultRuntimeSettings();
let mockRuntimeStrategy: RuntimeStrategySettings = defaultAgentSettings();
const runtimeSettingsStorageKey = "novel-autogrowth-engine.runtime-settings";

export function runtimeStageLabel(stage: RuntimeStageName): string {
  return stage === "planner" ? "剧情规划" : stage === "writer" ? "正文写作" : "记忆回写";
}

function runtimeSourceLabel(source: AgentRuntimeEntry["source"]): string {
  if (source === "llm") {
    return "模型";
  }
  if (source === "fallback") {
    return "回退";
  }
  return "空闲";
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function defaultAgentSettings(): AgentSettings {
  return {
    mode: "LLM-assisted",
    global_model: "qwen3.6-plus",
    character_model: "qwen3.6-plus",
    director_model: "qwen3.6-plus",
    writer_model: "qwen3.6-plus",
    memory_model: "qwen3.6-plus",
    temperature: "0.7",
    new_character_policy: "Director review",
  };
}

export function createDefaultAgentSettings(): AgentSettings {
  return defaultAgentSettings();
}

export function createDefaultRuntimeSettings(): RuntimeSettings {
  return {
    schema_version: "runtime-config/v2",
    accounts: {
      codexcli: { api_key: "", base_url: "", custom_models: [], codex_command: "codex" },
      antigravity: { api_key: "", base_url: "", custom_models: [], codex_command: "agy" },
    },
    stages: {
      planner: { provider_id: "codexcli", model: "gpt-5-codex" },
      writer: { provider_id: "codexcli", model: "gpt-5-codex" },
    },
    image: {
      enabled: false,
      api_key: "",
      base_url: "",
      model: "",
    },
    temperature: 0.7,
    new_character_policy: "Director review",
  };
}

function defaultRuntimeSettings(): RuntimeSettings {
  return createDefaultRuntimeSettings();
}

function normalizeAgentSettings(
  settings?: Partial<AgentSettings>,
): AgentSettings {
  return {
    ...defaultAgentSettings(),
    ...(settings ?? {}),
    mode: "LLM-assisted",
  };
}

function defaultRuntimeEntry(
  source: AgentRuntimeEntry["source"] = "idle",
  fallbackReason = "",
  lastRunChapter = 0,
  provider = "",
  model = "",
): AgentRuntimeEntry {
  return {
    source,
    provider,
    model,
    fallback_reason: fallbackReason,
    last_run_chapter: lastRunChapter,
  };
}

function normalizeRuntimeEntry(value?: Partial<AgentRuntimeEntry>): AgentRuntimeEntry {
  return defaultRuntimeEntry(
    value?.source ?? "idle",
    value?.fallback_reason ?? "",
    value?.last_run_chapter ?? 0,
    value?.provider ?? "",
    value?.model ?? "",
  );
}

function normalizeAgentRuntime(runtime?: Partial<AgentRuntimeState>): AgentRuntimeState {
  return {
    planner: normalizeRuntimeEntry(runtime?.planner),
    writer: normalizeRuntimeEntry(runtime?.writer),
    memory: normalizeRuntimeEntry(runtime?.memory),
    recent_events: Array.isArray(runtime?.recent_events) ? [...runtime.recent_events] : [],
  };
}

function defaultAgentRuntime(): AgentRuntimeState {
  return normalizeAgentRuntime();
}

function updateRuntimeForChapter(
  runtime: AgentRuntimeState,
  chapterNumber: number,
  source: AgentRuntimeEntry["source"],
  fallbackReason = "",
): AgentRuntimeState {
  const nextRuntime = normalizeAgentRuntime(runtime);
  nextRuntime.planner = defaultRuntimeEntry(source, fallbackReason, chapterNumber);
  nextRuntime.writer = defaultRuntimeEntry(source, fallbackReason, chapterNumber);
  nextRuntime.memory = defaultRuntimeEntry(source, fallbackReason, chapterNumber);
  nextRuntime.recent_events = [
    ...nextRuntime.recent_events,
    `规划阶段：${runtimeSourceLabel(source)}，第 ${chapterNumber} 章${fallbackReason ? `（${fallbackReason}）` : ""}`,
    `写作阶段：${runtimeSourceLabel(source)}，第 ${chapterNumber} 章${fallbackReason ? `（${fallbackReason}）` : ""}`,
    `记忆阶段：${runtimeSourceLabel(source)}，第 ${chapterNumber} 章${fallbackReason ? `（${fallbackReason}）` : ""}`,
  ].slice(-8);
  return nextRuntime;
}

function normalizeRuntimeAccount(value: Partial<RuntimeProviderAccount> | undefined): RuntimeProviderAccount {
  return {
    api_key: typeof value?.api_key === "string" ? value.api_key : "",
    base_url: typeof value?.base_url === "string" ? value.base_url : "",
    custom_models: Array.isArray(value?.custom_models) ? value.custom_models.filter((model): model is string => typeof model === "string") : [],
    codex_command: typeof value?.codex_command === "string" ? value.codex_command : "",
  };
}

function normalizeRuntimeImage(value: unknown): RuntimeImageSettings {
  const candidate = value && typeof value === "object" && !Array.isArray(value)
    ? value as Partial<RuntimeImageSettings>
    : {};
  return {
    enabled: candidate.enabled === true,
    api_key: typeof candidate.api_key === "string" ? candidate.api_key : "",
    base_url: typeof candidate.base_url === "string" ? candidate.base_url : "",
    model: typeof candidate.model === "string" ? candidate.model : "",
  };
}

function normalizeSynopsisAsset(value: unknown): SynopsisAsset | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as Partial<SynopsisAsset>;
  if (
    !Array.isArray(candidate.tags)
    || candidate.tags.some((tag) => typeof tag !== "string")
    || typeof candidate.body !== "string"
    || typeof candidate.format !== "string"
    || typeof candidate.updated_at !== "string"
  ) {
    return null;
  }
  const safeExtras = cloneSafePublishingValue(value);
  const synopsis = safeExtras && typeof safeExtras === "object" && !Array.isArray(safeExtras)
    ? safeExtras as SynopsisAsset & { [key: string]: unknown }
    : {} as SynopsisAsset & { [key: string]: unknown };
  for (const field of ["tags", "body", "format", "updated_at"]) delete synopsis[field];
  return Object.assign(synopsis, {
    tags: [...candidate.tags],
    body: candidate.body,
    format: candidate.format,
    updated_at: candidate.updated_at,
  } satisfies SynopsisAsset);
}

const UNSAFE_PUBLISHING_KEYS = new Set(["__proto__", "prototype", "constructor"]);
const COVER_FIELDS = new Set([
  "prompt", "image_version", "base_image_version", "rendered_from_base_version", "width", "height",
  "mime_type", "model", "rendered_title", "updated_at", "schema_version", "base_path", "rendered_path",
]);

function publishingPathLikeKey(key: string): boolean {
  const folded = key.toLowerCase();
  return ["path", "file", "filename", "url", "uri", "filepath", "file_path"].includes(folded)
    || /_(?:path|file|filename|url|uri|filepath)$/.test(folded);
}

function unsafePublishingString(value: string): boolean {
  const candidate = value.trim();
  return candidate.startsWith("/")
    || candidate.startsWith("\\")
    || candidate.startsWith("file:")
    || /^[a-zA-Z]:[\\/]/.test(candidate)
    || /(^|[\\/])\.\.([\\/]|$)/.test(candidate);
}

function cloneSafePublishingValue(value: unknown, seen = new WeakSet<object>(), depth = 0): unknown {
  if (depth > 32) return undefined;
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "string") return unsafePublishingString(value) ? undefined : value;
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (!value || typeof value !== "object" || seen.has(value)) return undefined;
  seen.add(value);
  if (Array.isArray(value)) {
    const cloned = value
      .map((item) => cloneSafePublishingValue(item, seen, depth + 1))
      .filter((item) => item !== undefined);
    seen.delete(value);
    return cloned;
  }
  const cloned: { [key: string]: unknown } = {};
  for (const [key, item] of Object.entries(value)) {
    if (UNSAFE_PUBLISHING_KEYS.has(key) || publishingPathLikeKey(key)) continue;
    const safeItem = cloneSafePublishingValue(item, seen, depth + 1);
    if (safeItem !== undefined) cloned[key] = safeItem;
  }
  seen.delete(value);
  return cloned;
}

function normalizeCoverAsset(value: unknown): CoverAsset | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as CoverAsset;
  const safeExtras = cloneSafePublishingValue(value);
  const cover = safeExtras && typeof safeExtras === "object" && !Array.isArray(safeExtras)
    ? safeExtras as CoverAsset & { [key: string]: unknown }
    : {} as CoverAsset & { [key: string]: unknown };
  for (const field of COVER_FIELDS) delete cover[field];
  if (typeof candidate.prompt === "string") cover.prompt = candidate.prompt;
  if (typeof candidate.image_version === "string") cover.image_version = candidate.image_version;
  if (typeof candidate.base_image_version === "string") cover.base_image_version = candidate.base_image_version;
  if (typeof candidate.rendered_from_base_version === "string") cover.rendered_from_base_version = candidate.rendered_from_base_version;
  if (typeof candidate.width === "number" && Number.isFinite(candidate.width) && candidate.width > 0) cover.width = candidate.width;
  if (typeof candidate.height === "number" && Number.isFinite(candidate.height) && candidate.height > 0) cover.height = candidate.height;
  if (typeof candidate.mime_type === "string") cover.mime_type = candidate.mime_type;
  if (typeof candidate.model === "string") cover.model = candidate.model;
  if (typeof candidate.rendered_title === "string") cover.rendered_title = candidate.rendered_title;
  if (typeof candidate.updated_at === "string") cover.updated_at = candidate.updated_at;
  if (candidate.schema_version === "cover/v1") cover.schema_version = candidate.schema_version;
  if (candidate.base_path === "assets/cover-base.png") cover.base_path = candidate.base_path;
  if (candidate.rendered_path === "assets/cover.png") cover.rendered_path = candidate.rendered_path;
  return Object.keys(cover).length > 0 ? cover : null;
}

function normalizePublishingAssets(value: unknown): PublishingAssets {
  const candidate = value && typeof value === "object" && !Array.isArray(value)
    ? value as Partial<PublishingAssets>
    : {};
  const safeExtras = cloneSafePublishingValue(value);
  const normalized = safeExtras && typeof safeExtras === "object" && !Array.isArray(safeExtras)
    ? safeExtras as { [key: string]: unknown }
    : {} as { [key: string]: unknown };
  delete normalized.schema_version;
  delete normalized.synopsis;
  delete normalized.cover;
  return Object.assign(normalized, {
    schema_version: "publishing-assets/v1",
    synopsis: normalizeSynopsisAsset(candidate.synopsis),
    cover: normalizeCoverAsset(candidate.cover),
  } satisfies PublishingAssets) as PublishingAssets;
}

export function normalizeProjectResponse(value: unknown): ProjectResponse {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("invalid_project_response");
  }
  const candidate = value as ProjectResponse & { publishing_assets?: unknown };
  return {
    ...candidate,
    publishing_assets: normalizePublishingAssets(candidate.publishing_assets),
  };
}

function normalizeNestedProjectResponse<T extends { project: unknown }>(value: T): T & { project: ProjectResponse } {
  return { ...value, project: normalizeProjectResponse(value.project) };
}

function normalizeRuntimeSettings(value?: Partial<RuntimeSettings>): RuntimeSettings {
  const base = defaultRuntimeSettings();
  if (!value || value.schema_version !== "runtime-config/v2") return base;
  const accounts = Object.fromEntries(
    Object.entries(value.accounts ?? {}).map(([providerId, account]) => [providerId, normalizeRuntimeAccount(account)]),
  );
  if (!accounts.codexcli) accounts.codexcli = base.accounts.codexcli;
  if (!accounts.antigravity) accounts.antigravity = base.accounts.antigravity;
  return {
    schema_version: "runtime-config/v2",
    accounts,
    stages: {
      planner: {
        provider_id: value.stages?.planner?.provider_id || base.stages.planner.provider_id,
        model: value.stages?.planner?.model ?? base.stages.planner.model,
      },
      writer: {
        provider_id: value.stages?.writer?.provider_id || base.stages.writer.provider_id,
        model: value.stages?.writer?.model ?? base.stages.writer.model,
      },
    },
    image: normalizeRuntimeImage(value.image),
    temperature: Number(value.temperature ?? base.temperature),
    new_character_policy: value.new_character_policy ?? base.new_character_policy,
  };
}

function relationshipShift(goals: string[]): { trustDelta: number; tensionDelta: number } {
  const goalText = goals.join(" ").toLowerCase();

  if (/(protect|save|guard|help)/.test(goalText)) {
    return { trustDelta: 0.1, tensionDelta: -0.1 };
  }
  if (/(expose|find|accuse|hunt)/.test(goalText)) {
    return { trustDelta: -0.1, tensionDelta: 0.1 };
  }
  return { trustDelta: 0.05, tensionDelta: 0.05 };
}

function relationshipSentence(story: MockStory): string {
  const lead = story.characters[0];
  const relations = Object.values(lead?.relationships ?? {});
  if (!lead || !relations.length) {
    return "The room offers no certainty, only pressure.";
  }

  const relation = relations[0];
  if (relation.tension >= 0.8) {
    return `Each exchange with ${relation.target} needles the alliance closer to open fracture.`;
  }
  if (relation.trust >= 0.5 && relation.tension <= 0.5) {
    return `${lead.name} works in fragile step with ${relation.target}, trusting the silence between them.`;
  }
  return `${lead.name} studies ${relation.target} carefully, unsure which way the balance will tip.`;
}

function continuitySentence(story: MockStory): string {
  const parts: string[] = [];
  const lastFact = story.history.at(-1)?.chapter_summary?.facts?.[0];
  const foreshadowingText = story.history.at(-1)?.foreshadowing?.[0]
    ? ((story.history.at(-1)?.foreshadowing?.[0] as { text?: string }).text ?? "")
    : "";

  if (lastFact) {
    parts.push(`Carries forward: ${lastFact}`);
  }
  if (foreshadowingText) {
    parts.push(`Foreshadowing lingers: ${foreshadowingText}`);
  }

  return parts.join(" ");
}

function findMockProjectByStoryId(storyId: string): MockProject | null {
  for (const project of mockProjectStore.values()) {
    if (project.active_story_id === storyId || project.branches.includes(storyId)) {
      return project;
    }
  }
  return null;
}

function syncMockStoryAuthorConstraints(story: MockStory): string[] {
  const project = findMockProjectByStoryId(story.story_id);
  const authorConstraints = clone(project?.author_constraints ?? story.author_constraints ?? []);
  story.author_constraints = authorConstraints;
  story.initial_story.author_constraints = clone(authorConstraints);
  story.world_facts = clone(story.world_facts ?? []);
  story.initial_story.world_facts = clone(story.initial_story.world_facts ?? story.world_facts ?? []);
  return authorConstraints;
}

function persistStoryIntoMockStore(story: StoryResponse): StoryResponse {
  const normalizedRuntime = normalizeAgentRuntime(story.agent_runtime);
  const mirroredStory: MockStory = {
    story_id: story.story_id,
    outline: story.outline,
    genre: story.genre,
    style: story.style,
    current_chapter: story.current_chapter,
    agent_settings: clone(story.agent_settings),
    agent_runtime: clone(normalizedRuntime),
    author_constraints: clone(story.author_constraints ?? []),
    world_facts: clone(story.world_facts ?? []),
    characters: clone(story.characters),
    history: clone(story.history),
    initial_story: {
      ...clone(story),
      agent_runtime: clone(normalizedRuntime),
      history: [],
    },
    parent_story_id: story.parent_story_id ?? null,
    branched_from_chapter: story.branched_from_chapter ?? null,
  };
  mockStore.set(story.story_id, mirroredStory);
  saveMockStore(mockStore);
  return mockFetchStory(story.story_id);
}

function authorConstraintSentences(authorConstraints: string[]): string[] {
  const text = authorConstraints.join(" ");
  const lines: string[] = [];
  if (/不要跳过调查|不要省略调查|调查/.test(text)) {
    lines.push("调查必须一步一步推进，任何结论都要靠线索和行动换来。");
  }
  if (/不要突然神降|不要开挂|不要天降答案|不要 deus ex machina/i.test(text)) {
    lines.push("局势没有被天降答案轻易改写，所有转机都只能从既有矛盾里逼出来。");
  }
  if (/不要引入新角色|no new characters/i.test(text)) {
    lines.push("这一轮没有新的棋子闯入局面，压力仍旧落在现有角色之间。");
  }
  return lines;
}

function mockCreateStory(payload: CreateStoryRequest): StoryResponse {
  const agentSettings = normalizeAgentSettings(payload.agent_settings);
  const agentRuntime = defaultAgentRuntime();
  const normalizedCharacters = clone(payload.characters ?? []).map((character) => ({
    ...character,
    lifecycle_state: character.lifecycle_state ?? (character.frozen ? "frozen" : "active"),
    last_proposed_chapter: character.last_proposed_chapter ?? 0,
    last_approved_chapter: character.last_approved_chapter ?? 0,
    introduced_by: character.introduced_by ?? "",
  }));

  const initialStory: StoryResponse = {
    story_id: payload.story_id,
    outline: payload.outline,
    genre: payload.genre,
    style: payload.style,
    current_chapter: 0,
    agent_settings: clone(agentSettings),
    agent_runtime: clone(agentRuntime),
    author_constraints: [],
    world_facts: [],
    parent_story_id: null,
    branched_from_chapter: null,
    characters: normalizedCharacters,
    history: [],
  };

  const story: MockStory = {
    story_id: payload.story_id,
    outline: payload.outline,
    genre: payload.genre,
    style: payload.style,
    current_chapter: 0,
    agent_settings: clone(agentSettings),
    agent_runtime: clone(agentRuntime),
    author_constraints: [],
    world_facts: [],
    characters: clone(normalizedCharacters),
    history: [],
    initial_story: initialStory,
    parent_story_id: null,
    branched_from_chapter: null,
  };
  mockStore.set(payload.story_id, story);
  saveMockStore(mockStore);
  return clone(initialStory);
}

function mockGenerateNextChapter(storyId: string): ChapterBundle {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");
  const authorConstraints = syncMockStoryAuthorConstraints(story);

  const chapterNumber = story.current_chapter + 1;
  story.current_chapter = chapterNumber;
  const source: AgentRuntimeEntry["source"] = "fallback";
  const fallbackReason = "模拟后端使用确定性回退。";
  story.agent_runtime = updateRuntimeForChapter(
    story.agent_runtime,
    chapterNumber,
    source,
    fallbackReason,
  );
  story.characters = story.characters.map((character, index) => {
    if (index !== 0 || character.frozen || !character.relationships) {
      return {
        ...character,
        lifecycle_state: character.frozen ? "frozen" : character.lifecycle_state,
      };
    }

    const nextRelationships = Object.fromEntries(
      Object.entries(character.relationships).map(([key, relationship]) => [
        key,
        {
          ...relationship,
          trust: Math.max(0, Math.min(1, Number((relationship.trust + relationshipShift(character.goals).trustDelta).toFixed(2)))),
          tension: Math.max(0, Math.min(1, Number((relationship.tension + relationshipShift(character.goals).tensionDelta).toFixed(2)))),
        },
      ]),
    );

    return {
      ...character,
      lifecycle_state: character.frozen ? "frozen" : character.lifecycle_state,
      relationships: nextRelationships,
    };
  });

  const constraintLines = authorConstraintSentences(authorConstraints);
  const mustKeepFacts = [`第 ${chapterNumber} 章确认调查仍在继续推进。`];
  if (constraintLines.length) {
    mustKeepFacts.push(...constraintLines);
  }

  const unresolvedThreads = [`第 ${chapterNumber} 章之后，谁会先掌控线索？`];
  if (authorConstraints.some((constraint) => /不要引入新角色|no new characters/i.test(constraint))) {
    unresolvedThreads.push("现有角色之间的冲突必须继续消化，不能靠新角色接管局势。");
  }

  const orderedActions = story.characters.slice(0, 3).map((character, index) => ({
    name: character.name,
    goal: character.goals[0] ?? "守住当前局面",
    action:
      index === 0
        ? `${character.name}继续顺着既有线索推进，试图把最新证据钉死。`
        : `${character.name}围绕当前压力调整动作，不让局面脱离既有角色的掌控。`,
    priority: index + 1,
  }));

  const bodySegments = [
    `第${chapterNumber}章正文。`,
    relationshipSentence(story),
    continuitySentence(story),
    "一封被压住的密信在章末浮出水面。",
    ...constraintLines,
  ].filter(Boolean);

  const bundle: ChapterBundle = {
    chapter_number: chapterNumber,
    body: bodySegments.join(" "),
    chapter_title: `第 ${chapterNumber} 章`,
    chapter_intent: {
      chapter_title: `第 ${chapterNumber} 章`,
      cadence: chapterNumber % 2 === 0 ? "measured" : "urgent",
      next_focus: `继续逼近第 ${chapterNumber} 章抛出的新线索。`,
      primary_conflict: {
        collision: `${story.characters[0]?.name ?? "主角"}必须在现有局面里继续压缩真相空间。`,
      },
      approved_new_characters: authorConstraints.some((constraint) => /不要引入新角色|no new characters/i.test(constraint))
        ? []
        : ["候选旁观者"],
      deferred_characters: authorConstraints.some((constraint) => /不要引入新角色|no new characters/i.test(constraint))
        ? ["新角色提案已被作者约束拦下"]
        : [],
      rejected_characters: [],
    },
    character_moves: orderedActions,
    memory_constraints: {
      must_keep_facts: mustKeepFacts,
      unresolved_threads: unresolvedThreads,
      protected_characters: story.characters.slice(0, 2).map((character) => character.name),
      protected_foreshadowing: [{ text: "一封被压住的密信在章末浮出水面。", status: "open", first_chapter: chapterNumber }],
      author_constraints: clone(authorConstraints),
      current_focus: `第 ${chapterNumber} 章的核心压力`,
      conflict_anchor: "真相控制权还在拉扯",
      event_guardrail: constraintLines[0] ?? "保持既有冲突自然推进。",
    },
    event_plan: {
      chapter_number: chapterNumber,
      chapter_title: `第 ${chapterNumber} 章`,
      turn: `${story.characters[0]?.name ?? "主角"}继续追索线索，但每一步都被现有对手顶住。`,
      pivot: `第 ${chapterNumber} 章把局势重新压回旧矛盾，而不是靠外力重置棋盘。`,
      collision: `${story.characters[0]?.name ?? "主角"}与既有阵营在证据控制权上再次正面碰撞。`,
      ordered_actions: orderedActions,
      stakes: "谁先掌控证据，谁就能定义下一章的主动权。",
      next_focus: `处理第 ${chapterNumber} 章留下的密信与控制权争夺。`,
      author_constraints: clone(authorConstraints),
    },
    character_cards: story.characters.map((character) => ({
      name: character.name,
      role: character.role,
      goals: character.goals,
      current_emotion: character.frozen ? "steady" : "alert",
      location: character.frozen ? "held position" : "palace archive",
      relationships: character.relationships ?? {},
    })),
    foreshadowing: [{ text: "A hidden letter appears.", first_chapter: chapterNumber, status: "open" }],
    next_outline: `Chapter ${chapterNumber + 1}: force the lead to act on the newest clue.`,
    chapter_summary: {
      chapter_number: chapterNumber,
      summary: `第 ${chapterNumber} 章继续推动调查，并把压力压回现有角色之间。`,
      facts: mustKeepFacts,
      unresolved_threads: unresolvedThreads,
    },
    simulation_status: {
      ok: true,
      mode: "degraded",
      fallback_agents: ["planner", "writer", "memory"],
      recent_events: clone(story.agent_runtime.recent_events),
      agents: {
        planner: clone(story.agent_runtime.planner),
        writer: clone(story.agent_runtime.writer),
        memory: clone(story.agent_runtime.memory),
      },
    },
    quality_report: {
      ok: true,
      issues: [],
    },
    updated_story: {
      story_id: story.story_id,
      outline: story.outline,
      genre: story.genre,
      style: story.style,
      current_chapter: story.current_chapter,
      agent_settings: clone(story.agent_settings),
      agent_runtime: clone(story.agent_runtime),
      author_constraints: clone(authorConstraints),
      world_facts: clone(story.world_facts ?? []),
      characters: story.characters,
      timeline: [
        {
          chapter_number: chapterNumber,
          summary: `第 ${chapterNumber} 章把核心谜团继续往前推，并抬高现有角色之间的压力。`,
          impact: "既有角色的对抗继续升温",
        },
      ],
      chapter_summaries: [],
      foreshadowing: [],
    },
  };

  story.history.push(bundle);
  saveMockStore(mockStore);
  return clone(bundle);
}

function mockRollbackStory(storyId: string): StoryResponse {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");

  if (story.history.length > 0) {
    story.history.pop();
    if (story.history.length > 0) {
      const restored = story.history.at(-1)?.updated_story as StoryResponse;
      story.current_chapter = restored.current_chapter;
      story.characters = clone(restored.characters);
      story.agent_runtime = clone(restored.agent_runtime);
    } else {
      story.current_chapter = story.initial_story.current_chapter;
      story.characters = clone(story.initial_story.characters);
      story.agent_runtime = clone(story.initial_story.agent_runtime);
    }
  }

  saveMockStore(mockStore);
  return {
    story_id: story.story_id,
    outline: story.outline,
    genre: story.genre,
    style: story.style,
    current_chapter: story.current_chapter,
    agent_settings: clone(story.agent_settings),
    agent_runtime: clone(story.agent_runtime),
    author_constraints: clone(story.author_constraints),
    world_facts: clone(story.world_facts ?? []),
    characters: clone(story.characters),
    history: clone(story.history),
    parent_story_id: story.parent_story_id ?? null,
    branched_from_chapter: story.branched_from_chapter ?? null,
  };
}

function mockFetchStory(storyId: string): StoryResponse {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");
  return {
    story_id: story.story_id,
    outline: story.outline,
    genre: story.genre,
    style: story.style,
    current_chapter: story.current_chapter,
    agent_settings: clone(story.agent_settings),
    agent_runtime: clone(story.agent_runtime),
    author_constraints: clone(syncMockStoryAuthorConstraints(story)),
    world_facts: clone(story.world_facts ?? []),
    characters: clone(story.characters),
    history: clone(story.history),
    parent_story_id: story.parent_story_id ?? null,
    branched_from_chapter: story.branched_from_chapter ?? null,
  };
}

function mockBranchStory(storyId: string, newStoryId: string, fromChapter: number): StoryResponse {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");
  if (mockStore.has(newStoryId)) throw new Error("mock: story_exists");
  if (fromChapter < 0 || fromChapter > story.history.length) throw new Error("mock: chapter_not_found");

  const branchHistory = clone(story.history.slice(0, fromChapter));
  const branchState =
    fromChapter === 0
      ? clone(story.initial_story)
      : clone((branchHistory.at(-1)?.updated_story as StoryResponse | undefined) ?? story.initial_story);

  branchState.story_id = newStoryId;
  branchState.history = branchHistory;

  const branchStory: MockStory = {
    story_id: newStoryId,
    outline: story.outline,
    genre: story.genre,
    style: story.style,
    current_chapter: branchState.current_chapter,
    agent_settings: clone(branchState.agent_settings),
    agent_runtime: clone(branchState.agent_runtime),
    author_constraints: clone(story.author_constraints),
    world_facts: clone(story.world_facts ?? []),
    characters: clone(branchState.characters),
    history: branchHistory,
    initial_story: {
      ...clone(story.initial_story),
      story_id: newStoryId,
      author_constraints: clone(story.author_constraints),
      world_facts: clone(story.world_facts ?? []),
    },
    parent_story_id: storyId,
    branched_from_chapter: fromChapter,
  };

  for (const bundle of branchStory.history) {
    if (bundle.updated_story && typeof bundle.updated_story === "object") {
      (bundle.updated_story as { story_id?: string }).story_id = newStoryId;
    }
  }

  mockStore.set(newStoryId, branchStory);
  saveMockStore(mockStore);
  return mockFetchStory(newStoryId);
}

function mockRenameStory(storyId: string, newStoryId: string): StoryResponse {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");
  if (mockStore.has(newStoryId)) throw new Error("mock: story_exists");

  mockStore.delete(storyId);
  story.story_id = newStoryId;
  story.initial_story.story_id = newStoryId;
  for (const bundle of story.history) {
    if (bundle.updated_story && typeof bundle.updated_story === "object") {
      (bundle.updated_story as { story_id?: string }).story_id = newStoryId;
    }
  }
  for (const child of mockStore.values()) {
    if (child.parent_story_id === storyId) {
      child.parent_story_id = newStoryId;
    }
  }
  mockStore.set(newStoryId, story);
  saveMockStore(mockStore);
  return mockFetchStory(newStoryId);
}

function mockDeleteStory(storyId: string): DeleteStoryResponse {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");
  if (!story.parent_story_id) throw new Error("mock: cannot_delete_root");
  if (Array.from(mockStore.values()).some((entry) => entry.parent_story_id === storyId)) {
    throw new Error("mock: story_has_children");
  }
  mockStore.delete(storyId);
  saveMockStore(mockStore);
  return {
    deleted: true,
    story_id: storyId,
  };
}

function mockFetchRuntimeSettings(): RuntimeSettings {
  if (typeof window !== "undefined") {
    try {
      const stored = window.localStorage.getItem(runtimeSettingsStorageKey);
      if (stored) {
        mockRuntimeSettings = normalizeRuntimeSettings(JSON.parse(stored));
      }
    } catch {
      // Ignore storage errors and fall back to the in-memory copy.
    }
  }

  return clone(mockRuntimeSettings);
}

function mockFetchRuntimeStrategy(): RuntimeStrategySettings {
  if (typeof window !== "undefined") {
    try {
      const stored = window.localStorage.getItem(CONFIG_AGENT_SETTINGS_STORAGE_KEY);
      if (stored) {
        mockRuntimeStrategy = normalizeAgentSettings(JSON.parse(stored));
      }
    } catch {
      // Ignore storage errors and fall back to the in-memory copy.
    }
  }

  return clone(mockRuntimeStrategy);
}

function mockSaveRuntimeSettings(settings: RuntimeSettings): RuntimeSettings {
  mockRuntimeSettings = normalizeRuntimeSettings(settings);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(runtimeSettingsStorageKey, JSON.stringify(mockRuntimeSettings));
    } catch {
      // Ignore storage errors and keep the in-memory fallback.
    }
  }
  return clone(mockRuntimeSettings);
}

function mockSaveRuntimeStrategy(settings: RuntimeStrategySettings): RuntimeStrategySettings {
  mockRuntimeStrategy = normalizeAgentSettings(settings);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(CONFIG_AGENT_SETTINGS_STORAGE_KEY, JSON.stringify(mockRuntimeStrategy));
    } catch {
      // Ignore storage errors and keep the in-memory fallback.
    }
  }
  return clone(mockRuntimeStrategy);
}

async function requestWithTimeout<T>(
  url: string,
  init: RequestInit,
  readResponse: (response: Response) => Promise<T>,
  timeoutMs = 30000,
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  try {
    const resp = await fetch(url, { ...init, signal: controller.signal });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      console.error('[tryFetchJson] Not OK, detail:', detail.slice(0, 500));
      let message = detail ? `${url} failed: ${resp.status} ${detail}` : `${url} failed: ${resp.status}`;
      if (detail) {
        let parsed: any;
        try {
          parsed = JSON.parse(detail);
        } catch {
          parsed = undefined;
        }
        if (parsed) {
          const structuredDetail = parsed.detail;
          if (structuredDetail && typeof structuredDetail === "object" && !Array.isArray(structuredDetail)
            && typeof structuredDetail.code === "string") {
            throw new PublishingApiError(structuredDetail.code, structuredDetail);
          } else if (typeof structuredDetail === "string" && structuredDetail.trim()) {
            message = structuredDetail.trim();
          } else if (Array.isArray(structuredDetail)) {
            const issues = structuredDetail
              .map((issue) => typeof issue?.msg === "string" ? issue.msg.trim() : "")
              .filter(Boolean);
            if (issues.length) message = issues.join("；");
          }
        }
      }
      throw new Error(message);
    }
    return await readResponse(resp);
  } catch (error) {
    console.error('[tryFetchJson] Error:', error);
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`${url} failed: request timed out (${Math.round(timeoutMs / 1000)}s)`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function tryFetchJson(url: string, init: RequestInit, timeoutMs = 30000): Promise<any> {
  return await requestWithTimeout(
    url,
    init,
    async (response) => {
      const text = await response.text();
      return JSON.parse(text);
    },
    timeoutMs,
  );
}

const LONG_RUNNING_REQUEST_TIMEOUT_MS = 1_800_000;
// A cover can make one 70s text request followed by one 70s image request;
// synopsis repair can make two 70s text requests. Keep client time above both.
export const PUBLISHING_GENERATION_TIMEOUT_MS = 180_000;

async function fetchOptionalJson(url: string, init: RequestInit, timeoutMs = 30000): Promise<any | null> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    if (response.status === 404) return null;
    if (!response.ok) {
      const detail = await response.text().catch(() => "");
      throw new Error(detail || `${url} failed: ${response.status}`);
    }
    return JSON.parse(await response.text());
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`${url} failed: request timed out (${Math.round(timeoutMs / 1000)}s)`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function fetchRuntimeSettings(): Promise<RuntimeSettings> {
  const response = await tryFetchJson(`${apiBase()}/runtime-settings`, {
    method: "GET",
  });
  return normalizeRuntimeSettings(response);
}

export async function fetchRuntimeProviderCatalog(): Promise<RuntimeProviderCatalog> {
  return (await tryFetchJson(`${apiBase()}/runtime-settings/providers`, { method: "GET" })) as RuntimeProviderCatalog;
}

export async function revealRuntimeApiKey(providerId: RuntimeProvider | "image"): Promise<string> {
  const response = (await tryFetchJson(`${apiBase()}/runtime-settings/reveal-api-key`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ provider_id: providerId }),
  })) as { api_key?: string };
  return response.api_key ?? "";
}

export async function fetchCodexCLIInfo(): Promise<CodexCLIInfo> {
  return (await tryFetchJson(`${apiBase()}/runtime-settings/cli-info`, {
    method: "GET",
  })) as CodexCLIInfo;
}

export async function fetchRuntimeStrategy(): Promise<RuntimeStrategySettings> {
  try {
    const response = await tryFetchJson(`${apiBase()}/runtime-strategy`, {
      method: "GET",
    });
    return normalizeAgentSettings(response);
  } catch {
    return mockFetchRuntimeStrategy();
  }
}

export async function saveRuntimeSettings(settings: RuntimeSettings): Promise<RuntimeSettings> {
  const response = await tryFetchJson(`${apiBase()}/runtime-settings`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(settings),
  });
  return normalizeRuntimeSettings(response);
}

export async function saveRuntimeStrategy(settings: RuntimeStrategySettings): Promise<RuntimeStrategySettings> {
  try {
    const response = await tryFetchJson(`${apiBase()}/runtime-strategy`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(settings),
    });
    return normalizeAgentSettings(response);
  } catch {
    return mockSaveRuntimeStrategy(settings);
  }
}

export async function testRuntimeSettingsConnection(
  settings: RuntimeSettings,
  stage: RuntimeStageName,
): Promise<RuntimeConnectionResult> {
  try {
    const response = await tryFetchJson(`${apiBase()}/runtime-settings/test`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        stage,
        runtime_settings: settings,
      }),
    });
    return response as RuntimeConnectionResult;
  } catch (error) {
    console.error('Test connection failed:', error);
    throw error;
  }
}

export async function discoverRuntimeModels(
  settings: RuntimeSettings,
  providerId: string,
): Promise<RuntimeModelDiscoveryResult> {
  return (await tryFetchJson(`${apiBase()}/runtime-settings/discover-models`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ provider_id: providerId, runtime_settings: settings }),
  })) as RuntimeModelDiscoveryResult;
}

export async function scanBookImport(sourcePath: string): Promise<BookImportScanReport> {
  return (await tryFetchJson(`${apiBase()}/book-import/scan`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath } satisfies BookImportScanRequest),
  })) as BookImportScanReport;
}

export async function bootstrapBookImport(sourcePath: string): Promise<BookImportBootstrapResponse> {
  return (await tryFetchJson(`${apiBase()}/book-import/bootstrap`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath } satisfies BookImportBootstrapRequest),
  })) as BookImportBootstrapResponse;
}

export async function fetchBookLibraryCatalog(sourcePath: string): Promise<BookLibraryCatalogResponse> {
  return (await tryFetchJson(`${apiBase()}/book-import/catalog`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath }),
  })) as BookLibraryCatalogResponse;
}

export async function listContinuationSources(sourcePath = ""): Promise<ContinuationSourceList> {
  return (await tryFetchJson(`${apiBase()}/continuation-imports/list-sources`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath }),
  })) as ContinuationSourceList;
}

export async function scanContinuationSource(
  sourcePath: string,
  forcedEncoding?: string,
): Promise<ContinuationScanResult> {
  return (await tryFetchJson(`${apiBase()}/continuation-imports/scan`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath, forced_encoding: forcedEncoding || null }),
  })) as ContinuationScanResult;
}

export async function createContinuationImport(
  sourcePath: string,
  forcedEncoding?: string,
): Promise<ContinuationImportSession> {
  return (await tryFetchJson(`${apiBase()}/continuation-imports`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath, forced_encoding: forcedEncoding || null }),
  })) as ContinuationImportSession;
}

export async function fetchContinuationImport(sessionId: string): Promise<ContinuationImportSession> {
  return (await tryFetchJson(`${apiBase()}/continuation-imports/${encodeURIComponent(sessionId)}`, {
    method: "GET",
  })) as ContinuationImportSession;
}

export async function replaceContinuationChapters(
  sessionId: string,
  expectedRevision: number,
  chapters: ContinuationChapter[],
): Promise<ContinuationImportSession> {
  return (await tryFetchJson(`${apiBase()}/continuation-imports/${encodeURIComponent(sessionId)}/chapters`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ expected_revision: expectedRevision, chapters }),
  })) as ContinuationImportSession;
}

export async function startContinuationAnalysis(sessionId: string): Promise<{ session_id: string; status: string }> {
  return (await tryFetchJson(`${apiBase()}/continuation-imports/${encodeURIComponent(sessionId)}/analyze`, {
    method: "POST",
  }, 180000)) as { session_id: string; status: string };
}

export async function fetchContinuationAnalysis(sessionId: string): Promise<ContinuationAnalysis> {
  return (await tryFetchJson(`${apiBase()}/continuation-imports/${encodeURIComponent(sessionId)}/analysis`, {
    method: "GET",
  })) as ContinuationAnalysis;
}

export async function confirmContinuationAnalysis(
  sessionId: string,
  expectedRevision: number,
  analysis: ContinuationAnalysis,
): Promise<ContinuationImportSession> {
  return (await tryFetchJson(`${apiBase()}/continuation-imports/${encodeURIComponent(sessionId)}/analysis`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ expected_revision: expectedRevision, analysis }),
  })) as ContinuationImportSession;
}

export async function createContinuationProject(
  sessionId: string,
  expectedRevision: number,
  settings: ContinuationSettings,
): Promise<CreatedContinuationProject> {
  return (await tryFetchJson(`${apiBase()}/continuation-imports/${encodeURIComponent(sessionId)}/create-project`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ expected_revision: expectedRevision, settings }),
  }, 180000)) as CreatedContinuationProject;
}

export async function quickContinueNovel(
  sessionId: string,
  targetChars?: number,
): Promise<QuickContinuationResult> {
  return (await tryFetchJson(
    `${apiBase()}/continuation-imports/${encodeURIComponent(sessionId)}/quick-continue`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(targetChars ? { target_chars: targetChars } : {}),
    },
    180000,
  )) as QuickContinuationResult;
}

export interface BookFolderListResponse {
  drives: { name: string; path: string; is_drive: boolean }[];
  folders: { name: string; path: string }[];
  current_path: string;
}

export async function listBookFolders(sourcePath: string): Promise<BookFolderListResponse> {
  return (await tryFetchJson(`${apiBase()}/book-import/list-folders`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath }),
  })) as BookFolderListResponse;
}

export async function dissectReferenceText(payload: {
  text: string;
  genre?: string;
  focus?: string;
}): Promise<BookDissectionReport> {
  return (await tryFetchJson(`${apiBase()}/book-dissection/reference`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })) as BookDissectionReport;
}

export async function dissectFileProjectChapter(
  projectId: string,
  chapterNumber?: number,
  body?: string,
): Promise<BookDissectionReport> {
  if (!isFileProjectId(projectId)) {
    throw new Error("book_dissection_only_supports_file_projects");
  }
  return (await tryFetchJson(`${fileProjectPath(projectId)}/book-dissection/chapter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chapter_number: chapterNumber, ...(body === undefined ? {} : { body }) }),
  })) as BookDissectionReport;
}

export async function createStory(payload: CreateStoryRequest): Promise<StoryResponse> {
  try {
    const response = (await tryFetchJson(`${apiBase()}/stories`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    })) as StoryResponse;
    return persistStoryIntoMockStore(response);
  } catch {
    return mockCreateStory(payload);
  }
}

export async function generateNextChapter(storyId: string): Promise<ChapterBundle> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/generate`, {
    method: "POST",
  }, 900000);
}

export async function startGenerationJob(storyId: string, chapterDirectionId?: string): Promise<GenerationJobResponse> {
  const path = isFileProjectId(storyId)
    ? `${fileProjectPath(storyId)}/generation-jobs`
    : `${apiBase()}/stories/${encodeURIComponent(storyId)}/generation-jobs`;
  const init: RequestInit = { method: "POST" };
  if (isFileProjectId(storyId) && chapterDirectionId) {
    init.headers = { "content-type": "application/json" };
    init.body = JSON.stringify({ chapter_direction_id: chapterDirectionId });
  }
  return (await tryFetchJson(path, init)) as GenerationJobResponse;
}

export async function startFileProjectRegenerationJob(
  projectId: string,
  chapterNumber: number,
  variant?: string,
  guidance?: string,
): Promise<GenerationJobResponse> {
  if (!isFileProjectId(projectId)) {
    throw new Error("regenerate_chapter_only_supports_file_projects");
  }
  return (await tryFetchJson(`${fileProjectPath(projectId)}/generation-jobs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chapter_number: chapterNumber, variant, guidance }),
  })) as GenerationJobResponse;
}

export async function startFileProjectExpansionJob(
  projectId: string,
  chapterNumber: number,
): Promise<GenerationJobResponse> {
  if (!isFileProjectId(projectId)) {
    throw new Error("expand_chapter_only_supports_file_projects");
  }
  return (await tryFetchJson(`${fileProjectPath(projectId)}/generation-jobs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chapter_number: chapterNumber, operation: "expand" }),
  })) as GenerationJobResponse;
}

export async function fetchCurrentGenerationJob(storyId: string): Promise<GenerationJobResponse | null> {
  const path = isFileProjectId(storyId)
    ? `${fileProjectPath(storyId)}/generation-jobs/current`
    : `${apiBase()}/stories/${encodeURIComponent(storyId)}/generation-jobs/current`;
  try {
    return (await fetchOptionalJson(path, { method: "GET" }, 90000)) as GenerationJobResponse | null;
  } catch {
    return null;
  }
}

export async function fetchGenerationJobHistory(storyId: string, limit = 30): Promise<GenerationJobHistoryResponse> {
  if (!isFileProjectId(storyId)) {
    const current = await fetchCurrentGenerationJob(storyId);
    return {
      schema_version: "file-generation-job-history/v1",
      items: current ? [{
        job_id: current.job_id,
        story_id: current.story_id,
        status: current.status,
        progress: current.progress,
        chapter_number: current.chapter_number,
        error: current.error,
        created_at: current.created_at,
        updated_at: current.updated_at,
      }] : [],
    };
  }
  return (await tryFetchJson(
    `${fileProjectPath(storyId)}/generation-jobs?limit=${Math.max(1, Math.min(limit, 100))}`,
    { method: "GET" },
    90000,
  )) as GenerationJobHistoryResponse;
}

export async function fetchGenerationJob(storyId: string, jobId: string): Promise<GenerationJobResponse> {
  const path = isFileProjectId(storyId)
    ? `${fileProjectPath(storyId)}/generation-jobs/${encodeURIComponent(jobId)}`
    : `${apiBase()}/stories/${encodeURIComponent(storyId)}/generation-jobs/${encodeURIComponent(jobId)}`;
  return (await tryFetchJson(
    path,
    {
      method: "GET",
    },
    90000,
  )) as GenerationJobResponse;
}

export async function regenerateFileProjectChapter(
  projectId: string,
  chapterNumber: number,
  variant?: string,
  guidance?: string,
): Promise<{ project: ProjectResponse; story: StoryResponse; generated: Record<string, unknown> }> {
  if (!isFileProjectId(projectId)) {
    throw new Error("regenerate_chapter_only_supports_file_projects");
  }
  const response = (await tryFetchJson(`${fileProjectPath(projectId)}/regenerate-chapter`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chapter_number: chapterNumber, variant, guidance }),
  }, 900000)) as { project: ProjectResponse; story: StoryResponse; generated: Record<string, unknown> };
  return normalizeNestedProjectResponse(response);
}

export async function startProjectAutomationJob(
  projectId: string,
  payload: ProjectAutomationJobRequest = {},
): Promise<ProjectAutomationJobResponse> {
  return (await tryFetchJson(`${apiBase()}/projects/${encodeURIComponent(projectId)}/automation-jobs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  })) as ProjectAutomationJobResponse;
}

export async function fetchProjectAutomationJob(
  projectId: string,
  jobId: string,
): Promise<ProjectAutomationJobResponse> {
  return (await tryFetchJson(
    `${apiBase()}/projects/${encodeURIComponent(projectId)}/automation-jobs/${encodeURIComponent(jobId)}`,
    {
      method: "GET",
    },
  )) as ProjectAutomationJobResponse;
}

export async function rollbackStory(storyId: string): Promise<StoryResponse> {
  try {
    const response = (await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/rollback`, {
      method: "POST",
    })) as StoryResponse;
    return persistStoryIntoMockStore(response);
  } catch {
    return mockRollbackStory(storyId);
  }
}

export async function reviseProjectChapter(
  projectId: string,
  payload: AgentReviseRequest,
): Promise<AgentRevisionResponse> {
  return (await tryFetchJson(
    `${apiBase()}/projects/${encodeURIComponent(projectId)}/agent-revise`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
    180000,
  )) as AgentRevisionResponse;
}

export async function fetchProjectAgentReview(
  projectId: string,
  chapterNumber?: number | null,
  includeBody = true,
): Promise<AgentReviewResponse> {
  const params = new URLSearchParams();
  if (chapterNumber != null) {
    params.set("chapter_number", String(chapterNumber));
  }
  if (includeBody) {
    params.set("include_body", "true");
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return (await tryFetchJson(
    `${apiBase()}/projects/${encodeURIComponent(projectId)}/agent-review${suffix}`,
    {
      method: "GET",
    },
    180000,
  )) as AgentReviewResponse;
}

export async function fetchProjectWritingPacket(
  projectId: string,
  chapterNumber?: number | null,
): Promise<CodexWritingPacket> {
  const params = new URLSearchParams();
  if (chapterNumber != null) {
    params.set("chapter_number", String(chapterNumber));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const path = isFileProjectId(projectId)
    ? `${fileProjectPath(projectId)}/writing-packet${suffix}`
    : `${apiBase()}/projects/${encodeURIComponent(projectId)}/writing-packet${suffix}`;
  return (await tryFetchJson(
    path,
    {
      method: "GET",
    },
    120000,
  )) as CodexWritingPacket;
}

export async function fetchProjectPromptPreview(
  projectId: string,
  chapterNumber?: number | null,
): Promise<PromptPreviewResponse> {
  const params = new URLSearchParams();
  if (chapterNumber != null) {
    params.set("chapter_number", String(chapterNumber));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const path = isFileProjectId(projectId)
    ? `${fileProjectPath(projectId)}/prompt-preview${suffix}`
    : `${apiBase()}/projects/${encodeURIComponent(projectId)}/prompt-preview${suffix}`;
  return (await tryFetchJson(
    path,
    {
      method: "GET",
    },
    120000,
  )) as PromptPreviewResponse;
}

export async function fetchGlobalPromptTemplates(): Promise<PromptTemplatesResponse> {
  return (await tryFetchJson(`${apiBase()}/prompt-templates`, { method: "GET" })) as PromptTemplatesResponse;
}

export async function auditPrompt(payload: PromptAuditRequest): Promise<PromptAuditResult> {
  return (await tryFetchJson(`${apiBase()}/prompt-audit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })) as PromptAuditResult;
}

export async function deepAuditPrompt(
  payload: PromptAuditRequest,
  localResult: PromptAuditResult,
): Promise<DeepPromptAuditResult> {
  const sanitizedLocalResult: PromptAuditResult = {
    schema_version: localResult.schema_version,
    mode: localResult.mode,
    content_sha256: localResult.content_sha256,
    summary: localResult.summary,
    must_fix: localResult.must_fix,
    suggestions: localResult.suggestions,
    passed_checks: localResult.passed_checks,
  };
  return (await tryFetchJson(`${apiBase()}/prompt-audit/deep`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, local_result: sanitizedLocalResult }),
  }, 360000)) as DeepPromptAuditResult;
}

export async function saveGlobalPromptTemplate(
  templateKey: string,
  content: string,
): Promise<PromptTemplateEntry> {
  return (await tryFetchJson(`${apiBase()}/prompt-templates/${encodeURIComponent(templateKey)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  })) as PromptTemplateEntry;
}

export async function fetchProjectPromptTemplates(projectId: string): Promise<PromptTemplatesResponse> {
  return (await tryFetchJson(`${fileProjectPath(projectId)}/prompt-templates`, {
    method: "GET",
  })) as PromptTemplatesResponse;
}

export async function saveProjectPromptTemplate(
  projectId: string,
  templateKey: string,
  content: string,
): Promise<PromptTemplateEntry> {
  return (await tryFetchJson(`${fileProjectPath(projectId)}/prompt-templates/${encodeURIComponent(templateKey)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  })) as PromptTemplateEntry;
}

export async function deleteProjectPromptTemplate(
  projectId: string,
  templateKey: string,
): Promise<PromptTemplateEntry> {
  return (await tryFetchJson(`${fileProjectPath(projectId)}/prompt-templates/${encodeURIComponent(templateKey)}`, {
    method: "DELETE",
  })) as PromptTemplateEntry;
}

export async function fetchProjectPromptContext(
  projectId: string,
  chapterNumber?: number | null,
): Promise<PromptContextResponse> {
  const params = new URLSearchParams();
  if (chapterNumber != null) params.set("chapter_number", String(chapterNumber));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return (await tryFetchJson(`${fileProjectPath(projectId)}/prompt-context${suffix}`, {
    method: "GET",
  })) as PromptContextResponse;
}

export async function fetchProjectPromptCalls(
  projectId: string,
  chapterNumber?: number | null,
): Promise<PromptCallListResponse> {
  const params = new URLSearchParams();
  if (chapterNumber != null) params.set("chapter_number", String(chapterNumber));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return (await tryFetchJson(`${fileProjectPath(projectId)}/prompt-calls${suffix}`, {
    method: "GET",
  })) as PromptCallListResponse;
}

export async function fetchProjectPromptCall(projectId: string, callId: string): Promise<PromptCallDetail> {
  return (await tryFetchJson(`${fileProjectPath(projectId)}/prompt-calls/${encodeURIComponent(callId)}`, {
    method: "GET",
  })) as PromptCallDetail;
}

export async function listSkillPacks(): Promise<SkillPackSummary[]> {
  return (await tryFetchJson(`${apiBase()}/skill-packs`, {
    method: "GET",
  })) as SkillPackSummary[];
}

export async function fetchSkillPack(skillId: string): Promise<SkillPackSummary> {
  return (await tryFetchJson(`${apiBase()}/skill-packs/${encodeURIComponent(skillId)}`, {
    method: "GET",
  })) as SkillPackSummary;
}

export async function importSkillPackFromPath(sourcePath: string): Promise<SkillPackSummary> {
  return (await tryFetchJson(`${apiBase()}/skill-packs/import`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath }),
  })) as SkillPackSummary;
}

export async function uploadSkillPackZip(file: File): Promise<SkillPackSummary> {
  return (await tryFetchJson(`${apiBase()}/skill-packs/upload`, {
    method: "POST",
    headers: { "content-type": "application/zip" },
    body: await file.arrayBuffer(),
  })) as SkillPackSummary;
}

export async function uninstallSkillPack(skillId: string): Promise<UninstallSkillPackResponse> {
  return (await tryFetchJson(`${apiBase()}/skill-packs/${encodeURIComponent(skillId)}`, {
    method: "DELETE",
  })) as UninstallSkillPackResponse;
}

export async function uninstallSkillModule(skillId: string, moduleId: string): Promise<UninstallSkillPackResponse> {
  return (await tryFetchJson(
    `${apiBase()}/skill-packs/${encodeURIComponent(skillId)}/modules/${encodeURIComponent(moduleId)}`,
    { method: "DELETE" },
  )) as UninstallSkillPackResponse;
}

export async function fetchStory(storyId: string): Promise<StoryResponse> {
  try {
    const fileStory = isFileProjectId(storyId);
    const path = fileStory
      ? fileStoryPath(storyId)
      : `${apiBase()}/stories/${encodeURIComponent(storyId)}`;
    const response = (await tryFetchJson(path, {
      method: "GET",
    }, fileStory ? 120000 : 30000)) as StoryResponse;
    return persistStoryIntoMockStore(response);
  } catch {
    return mockFetchStory(storyId);
  }
}

export async function fetchFileStoryOverview(storyId: string): Promise<FileStoryOverview> {
  return (await tryFetchJson(`${fileStoryPath(storyId)}/overview`, {
    method: "GET",
    cache: "no-store",
  }, 30000)) as FileStoryOverview;
}

export async function fetchFileChapter(storyId: string, chapterNumber: number): Promise<ChapterBundle> {
  return (await tryFetchJson(`${fileStoryPath(storyId)}/chapters/${chapterNumber}`, {
    method: "GET",
    cache: "no-store",
  }, 30000)) as ChapterBundle;
}

export async function runFileProjectShuangwenReview(
  projectId: string,
  chapterNumber: number,
): Promise<ShuangwenSkillReview> {
  if (!isFileProjectId(projectId)) {
    throw new Error("shuangwen_review_only_supports_file_projects");
  }
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/chapters/${chapterNumber}/skill-reviews/commercial-shuangwen`,
    { method: "POST" },
    180000,
  )) as ShuangwenSkillReview;
}

export async function createProject(payload: CreateProjectRequest): Promise<ProjectResponse> {
  try {
    const response = (await tryFetchJson(`${apiBase()}/projects`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    })) as ProjectResponse;
    return persistProjectIntoMockStore(normalizeProjectResponse(response));
  } catch {
    return mockCreateProject(payload);
  }
}

export async function createFileProject(payload: NewFileProjectRequest): Promise<NewFileProjectResponse> {
  const response = (await tryFetchJson(`${apiBase()}/file-projects`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  })) as NewFileProjectResponse;
  return normalizeProjectResponse(response) as NewFileProjectResponse;
}

export async function fetchOpeningSetup(projectId: string): Promise<OpeningSetup> {
  return (await tryFetchJson(`${fileProjectPath(projectId)}/opening-directions`, {
    method: "GET",
  })) as OpeningSetup;
}

export async function generateOpeningDirections(projectId: string, guidance: string = ""): Promise<OpeningSetup> {
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/opening-directions`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ guidance }),
    },
    180000,
  )) as OpeningSetup;
}

export async function selectOpeningDirection(projectId: string, directionId: string): Promise<OpeningSetup> {
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/opening-directions/${encodeURIComponent(directionId)}/select`,
    { method: "POST" },
  )) as OpeningSetup;
}

export async function fetchStoryCore(projectId: string): Promise<StoryCoreCard> {
  return (await tryFetchJson(`${fileProjectPath(projectId)}/story-core`, {
    method: "GET",
  })) as StoryCoreCard;
}

export async function updateStoryCore(projectId: string, payload: StoryCoreCard): Promise<StoryCoreCard> {
  return (await tryFetchJson(`${fileProjectPath(projectId)}/story-core`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  })) as StoryCoreCard;
}

export type WorkflowArtifactStage = {
  stage_id: string;
  agent_id: string;
  status: string;
  elapsed_ms: number;
  artifact_path: string;
  artifact_sha256: string;
  reads: Record<string, unknown>[];
  selected_entity_ids: string[];
  selected_module_ids: string[];
  provider: string;
  model: string;
  prompt_template_id: string;
  prompt_template_version: string;
  output_summary: string;
  error: string;
  started_at: string;
  finished_at: string;
  blocking_issues?: { code: string; message: string; source: string }[];
};

export type WorkflowArtifactJob = {
  job_id: string;
  stages: WorkflowArtifactStage[];
};

export type WorkflowArtifactListResponse = {
  schema_version: string;
  project_id: string;
  items: WorkflowArtifactJob[];
};

export type WorkflowArtifactResponse = {
  schema_version: string;
  project_id: string;
  job_id: string;
  stage_id: string;
  stage: WorkflowArtifactStage;
};

export async function fetchWorkflowArtifacts(
  projectId: string,
  jobId?: string,
): Promise<WorkflowArtifactListResponse> {
  const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/workflow-artifacts${query}`,
    { method: "GET" },
  )) as WorkflowArtifactListResponse;
}

export async function fetchWorkflowArtifact(
  projectId: string,
  jobId: string,
  stageId: string,
): Promise<WorkflowArtifactResponse> {
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/workflow-artifacts/${encodeURIComponent(jobId)}/${encodeURIComponent(stageId)}`,
    { method: "GET" },
  )) as WorkflowArtifactResponse;
}

function mockListStories(): StorySummary[] {
  return Array.from(mockStore.values()).map((story) => ({
    story_id: story.story_id,
    current_chapter: story.current_chapter,
    parent_story_id: story.parent_story_id ?? null,
    branched_from_chapter: story.branched_from_chapter ?? null,
  }));
}

function mockCreateProject(payload: CreateProjectRequest): ProjectResponse {
  const project: MockProject = {
    project_id: payload.project_id,
    title: payload.title,
    source_path: payload.source_path ?? "",
    seed_outline: payload.seed_outline ?? "",
    world_summary: payload.world_summary ?? "",
    current_focus: payload.current_focus ?? "",
    author_constraints: payload.author_constraints ?? [],
    world_blueprint: payload.world_blueprint ?? {},
    character_profiles: payload.character_profiles ?? [],
    relationship_graph: payload.relationship_graph ?? payload.world_blueprint?.relationship_graph ?? [],
    enabled_skill_ids: payload.enabled_skill_ids ?? [],
    enabled_skill_module_ids: payload.enabled_skill_module_ids ?? [],
    skill_module_selection_mode: "explicit",
    status: payload.active_story_id ? "simulating" : "draft",
    pipeline_stage: payload.pipeline_stage ?? (payload.active_story_id ? "environment_ready" : "imported"),
    active_story_id: payload.active_story_id ?? "",
    branches: payload.active_story_id ? [payload.active_story_id] : [],
    publishing_assets: normalizePublishingAssets(undefined),
  };
  mockProjectStore.set(project.project_id, project);
  const activeStory = project.active_story_id ? mockStore.get(project.active_story_id) : null;
  if (activeStory) {
    syncMockStoryAuthorConstraints(activeStory);
    saveMockStore(mockStore);
  }
  saveMockProjectStore(mockProjectStore);
  setMockProjectPreference(true);
  return normalizeProjectResponse({
    ...project,
    branches: project.branches.map((storyId) => ({
      story_id: storyId,
      current_chapter: mockStore.get(storyId)?.current_chapter ?? 0,
      parent_story_id: mockStore.get(storyId)?.parent_story_id ?? null,
      branched_from_chapter: mockStore.get(storyId)?.branched_from_chapter ?? null,
    })),
  });
}

function mockListProjects(): ProjectSummary[] {
  return Array.from(mockProjectStore.values()).map((project) => ({
    project_id: project.project_id,
    title: project.title,
    status: project.status,
    pipeline_stage: project.pipeline_stage ?? "imported",
    active_story_id: project.active_story_id,
    current_chapter: mockStore.get(project.active_story_id)?.current_chapter ?? 0,
    source_path: project.source_path,
    storage_source: project.storage_source,
  }));
}

function mockFetchProject(projectId: string): ProjectResponse {
  let project = mockProjectStore.get(projectId);
  if (!project && typeof window !== "undefined") {
    project = loadMockProjectStore().get(projectId);
    if (project) mockProjectStore.set(projectId, project);
  }
  if (!project) {
    throw new Error("mock: project_not_found");
  }
  return normalizeProjectResponse({
    ...project,
    branches: project.branches.map((storyId) => ({
      story_id: storyId,
      current_chapter: mockStore.get(storyId)?.current_chapter ?? 0,
      parent_story_id: mockStore.get(storyId)?.parent_story_id ?? null,
      branched_from_chapter: mockStore.get(storyId)?.branched_from_chapter ?? null,
    })),
    storage_source: project.storage_source,
    publishing_assets: project.publishing_assets,
    continuation: clone(project.continuation ?? null),
  });
}

export async function generateSynopsis(projectId: string, guidance = ""): Promise<SynopsisAsset> {
  const response = (await tryFetchJson(
    `${fileProjectPath(projectId)}/publishing/synopsis`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ guidance }),
    },
    PUBLISHING_GENERATION_TIMEOUT_MS,
  )) as { synopsis: SynopsisAsset };
  return response.synopsis;
}

export async function updateSynopsis(
  projectId: string,
  payload: Pick<SynopsisAsset, "tags" | "body">,
): Promise<SynopsisAsset> {
  const response = (await tryFetchJson(
    `${fileProjectPath(projectId)}/publishing/synopsis`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
    30000,
  )) as { synopsis: SynopsisAsset };
  return response.synopsis;
}

export async function generateCover(projectId: string, guidance = ""): Promise<CoverGenerationResponse> {
  const response = (await tryFetchJson(
    `${fileProjectPath(projectId)}/publishing/cover`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ guidance }),
    },
    PUBLISHING_GENERATION_TIMEOUT_MS,
  )) as CoverGenerationResponse;
  return response;
}

export async function generateCoverFromPrompt(projectId: string): Promise<CoverGenerationResponse> {
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/publishing/cover/render-image`,
    { method: "POST" },
    PUBLISHING_GENERATION_TIMEOUT_MS,
  )) as CoverGenerationResponse;
}

export async function updateCoverPrompt(projectId: string, prompt: string): Promise<CoverAsset> {
  const response = (await tryFetchJson(
    `${fileProjectPath(projectId)}/publishing/cover-prompt`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt }),
    },
    30000,
  )) as { cover: CoverAsset };
  return response.cover;
}

export async function renderCoverTitle(projectId: string): Promise<CoverAsset> {
  const response = (await tryFetchJson(
    `${fileProjectPath(projectId)}/publishing/cover/render-title`,
    { method: "POST" },
    30000,
  )) as { status: "ready"; cover: CoverAsset };
  return response.cover;
}

export function coverImageUrl(projectId: string, version: string, download = false): string {
  const suffix = download ? "&download=1" : "";
  return `${fileProjectPath(projectId)}/publishing/cover.png?version=${encodeURIComponent(version)}${suffix}`;
}

function persistProjectIntoMockStore(project: ProjectResponse): ProjectResponse {
  const mirroredProject: MockProject = {
    project_id: project.project_id,
    title: project.title,
    source_path: project.source_path,
    seed_outline: project.seed_outline,
    world_summary: project.world_summary,
    current_focus: project.current_focus,
    author_constraints: clone(project.author_constraints ?? []),
    world_blueprint: clone(project.world_blueprint ?? {}),
    character_profiles: clone(project.character_profiles ?? []),
    relationship_graph: clone(project.relationship_graph ?? project.world_blueprint?.relationship_graph ?? []),
    enabled_skill_ids: clone(project.enabled_skill_ids ?? []),
    enabled_skill_module_ids: clone(project.enabled_skill_module_ids ?? []),
    skill_module_selection_mode: project.skill_module_selection_mode,
    status: project.status,
    pipeline_stage: project.pipeline_stage ?? "imported",
    active_story_id: project.active_story_id,
    branches: project.branches.map((branch) => branch.story_id),
    storage_source: project.storage_source,
    publishing_assets: clone(project.publishing_assets),
    continuation: clone(project.continuation ?? null),
  };
  mockProjectStore.set(project.project_id, mirroredProject);
  saveMockProjectStore(mockProjectStore);
  setMockProjectPreference(true);

  const activeStory = mirroredProject.active_story_id ? mockStore.get(mirroredProject.active_story_id) : null;
  if (activeStory) {
    syncMockStoryAuthorConstraints(activeStory);
    saveMockStore(mockStore);
  }

  return {
    ...project,
    publishing_assets: clone(project.publishing_assets),
  };
}

function mockUpdateProject(projectId: string, payload: UpdateProjectRequest): ProjectResponse {
  const project = mockProjectStore.get(projectId);
  if (!project) {
    throw new Error("mock: project_not_found");
  }
  const nextProject: MockProject = {
    ...project,
    ...(payload.title !== undefined ? { title: payload.title } : {}),
    ...(payload.source_path !== undefined ? { source_path: payload.source_path } : {}),
    ...(payload.seed_outline !== undefined ? { seed_outline: payload.seed_outline } : {}),
    ...(payload.world_summary !== undefined ? { world_summary: payload.world_summary } : {}),
    ...(payload.current_focus !== undefined ? { current_focus: payload.current_focus } : {}),
    ...(payload.author_constraints !== undefined ? { author_constraints: payload.author_constraints } : {}),
    ...(payload.world_blueprint !== undefined ? { world_blueprint: payload.world_blueprint } : {}),
    ...(payload.character_profiles !== undefined ? { character_profiles: payload.character_profiles } : {}),
    ...(payload.relationship_graph !== undefined ? { relationship_graph: payload.relationship_graph } : {}),
    ...(payload.enabled_skill_ids !== undefined ? { enabled_skill_ids: payload.enabled_skill_ids } : {}),
    ...(payload.enabled_skill_module_ids !== undefined ? { enabled_skill_module_ids: payload.enabled_skill_module_ids } : {}),
    ...(payload.enabled_skill_module_ids !== undefined ? { skill_module_selection_mode: "explicit" as const } : {}),
    ...(payload.status !== undefined ? { status: payload.status } : {}),
    ...(payload.pipeline_stage !== undefined ? { pipeline_stage: payload.pipeline_stage } : {}),
    ...(payload.active_story_id !== undefined ? { active_story_id: payload.active_story_id } : {}),
  };
  mockProjectStore.set(projectId, nextProject);
  const activeStory = nextProject.active_story_id ? mockStore.get(nextProject.active_story_id) : null;
  if (activeStory) {
    syncMockStoryAuthorConstraints(activeStory);
    saveMockStore(mockStore);
  }
  saveMockProjectStore(mockProjectStore);
  setMockProjectPreference(true);
  return mockFetchProject(projectId);
}

function mockActivateProjectStory(projectId: string, storyId: string): ProjectResponse {
  const project = mockProjectStore.get(projectId);
  if (!project) {
    throw new Error("mock: project_not_found");
  }
  const nextBranches = project.branches.includes(storyId) ? project.branches : [...project.branches, storyId];
  const nextProject: MockProject = {
    ...project,
    active_story_id: storyId,
    branches: nextBranches,
    status: "simulating",
    pipeline_stage: "environment_ready",
  };
  mockProjectStore.set(projectId, nextProject);
  const activeStory = mockStore.get(storyId);
  if (activeStory) {
    syncMockStoryAuthorConstraints(activeStory);
    saveMockStore(mockStore);
  }
  saveMockProjectStore(mockProjectStore);
  setMockProjectPreference(true);
  return mockFetchProject(projectId);
}

export async function listStories(): Promise<StorySummary[]> {
  try {
    return await tryFetchJson(`${apiBase()}/stories`, {
      method: "GET",
    });
  } catch {
    return mockListStories();
  }
}

export async function listProjects(lifecycle: ProjectLifecycle = "active"): Promise<ProjectSummary[]> {
  const query = `?lifecycle=${encodeURIComponent(lifecycle)}`;
  try {
    const response = (await tryFetchJson(`${apiBase()}/projects${query}`, {
      method: "GET",
    })) as ProjectSummary[];
    const fileProjects = (await tryFetchJson(`${apiBase()}/file-projects${query}`, {
      method: "GET",
    }).catch(() => [])) as ProjectSummary[];
    const seen = new Set(response.map((project) => project.project_id));
    return [...response, ...fileProjects.filter((project) => !seen.has(project.project_id))];
  } catch (err) {
    const fileProjects = (await tryFetchJson(`${apiBase()}/file-projects${query}`, {
      method: "GET",
    }).catch(() => [])) as ProjectSummary[];
    if (fileProjects.length > 0) {
      return fileProjects;
    }
    throw err;
  }
}

export async function fetchFileProjectCandidates(
  projectId: string,
  chapterNumber?: number,
): Promise<CandidateListResponse> {
  if (!isFileProjectId(projectId)) throw new Error("candidates_only_support_file_projects");
  const query = Number.isInteger(chapterNumber) ? `?chapter_number=${chapterNumber}` : "";
  return (await tryFetchJson(`${fileProjectPath(projectId)}/candidates${query}`, { method: "GET" })) as CandidateListResponse;
}

export async function discardFileProjectCandidate(projectId: string, candidateId: string): Promise<{ candidate: CandidateDraft }> {
  if (!isFileProjectId(projectId)) throw new Error("candidates_only_support_file_projects");
  return (await tryFetchJson(`${fileProjectPath(projectId)}/candidates/${encodeURIComponent(candidateId)}/discard`, {
    method: "POST",
  })) as { candidate: CandidateDraft };
}

export async function confirmFileProjectCandidate(projectId: string, candidateId: string, force = false): Promise<{
  candidate: CandidateDraft;
  project: ProjectResponse;
  story: StoryResponse;
}> {
  if (!isFileProjectId(projectId)) throw new Error("candidates_only_support_file_projects");
  const suffix = force ? "?force=true" : "";
  return (await tryFetchJson(`${fileProjectPath(projectId)}/candidates/${encodeURIComponent(candidateId)}/confirm${suffix}`, {
    method: "POST",
  }, 900000)) as { candidate: CandidateDraft; project: ProjectResponse; story: StoryResponse };
}

function projectLifecyclePath(projectId: string, action: "archive" | "trash" | "restore"): string {
  const base = isFileProjectId(projectId)
    ? fileProjectPath(projectId)
    : `${apiBase()}/projects/${encodeURIComponent(projectId)}`;
  return `${base}/${action}`;
}

export async function archiveProject(projectId: string): Promise<ProjectResponse> {
  return await tryFetchJson(projectLifecyclePath(projectId, "archive"), { method: "POST" });
}

export async function trashProject(projectId: string): Promise<ProjectResponse> {
  return await tryFetchJson(projectLifecyclePath(projectId, "trash"), { method: "POST" });
}

export async function restoreProject(projectId: string): Promise<ProjectResponse> {
  return await tryFetchJson(projectLifecyclePath(projectId, "restore"), { method: "POST" });
}

export async function permanentlyDeleteProject(projectId: string, title: string): Promise<void> {
  const base = isFileProjectId(projectId)
    ? fileProjectPath(projectId)
    : `${apiBase()}/projects/${encodeURIComponent(projectId)}`;
  await tryFetchJson(`${base}?confirm_title=${encodeURIComponent(title)}`, { method: "DELETE" });
}

export async function fetchProject(projectId: string): Promise<ProjectResponse> {
  try {
    const fileProject = isFileProjectId(projectId);
    const path = fileProject
      ? fileProjectPath(projectId)
      : `${apiBase()}/projects/${encodeURIComponent(projectId)}`;
    const response = (await tryFetchJson(path, {
      method: "GET",
    }, fileProject ? 90000 : 30000)) as ProjectResponse;
    return persistProjectIntoMockStore(normalizeProjectResponse(response));
  } catch {
    return mockFetchProject(projectId);
  }
}

export type UpdateProjectOptions = {
  fallbackToMock?: boolean;
};

export async function updateProject(
  projectId: string,
  payload: UpdateProjectRequest,
  { fallbackToMock = true }: UpdateProjectOptions = {},
): Promise<ProjectResponse> {
  try {
    const path = isFileProjectId(projectId)
      ? fileProjectPath(projectId)
      : `${apiBase()}/projects/${encodeURIComponent(projectId)}`;
    const response = (await tryFetchJson(path, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    })) as ProjectResponse;
    return persistProjectIntoMockStore(normalizeProjectResponse(response));
  } catch (error) {
    if (!fallbackToMock) throw error;
    return mockUpdateProject(projectId, payload);
  }
}

export async function fetchProjectOutline(projectId: string): Promise<ProjectOutline> {
  if (!isFileProjectId(projectId)) {
    throw new Error("three_level_outline_requires_file_project");
  }
  return (await tryFetchJson(`${fileProjectPath(projectId)}/outline`, { method: "GET" })) as ProjectOutline;
}

export async function fetchProjectRollingOutline(projectId: string): Promise<RollingOutline> {
  if (!isFileProjectId(projectId)) {
    throw new Error("rolling_outline_requires_file_project");
  }
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/outline/rolling`,
    { method: "GET" },
  )) as RollingOutline;
}

export async function fetchVolumeWorkflow(
  projectId: string,
  targetChapter: number,
): Promise<VolumeWorkflowResponse> {
  if (!isFileProjectId(projectId)) {
    throw new Error("volume_workflow_requires_file_project");
  }
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/outline/volume-workflow?target_chapter=${encodeURIComponent(String(targetChapter))}`,
    { method: "GET" },
  )) as VolumeWorkflowResponse;
}

export async function designNextVolume(
  projectId: string,
  guidance = "",
): Promise<VolumeDesignResponse> {
  if (!isFileProjectId(projectId)) {
    throw new Error("volume_workflow_requires_file_project");
  }
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/outline/volumes/next`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ guidance }),
    },
    420000,
  )) as VolumeDesignResponse;
}

export async function generateVolumeDetail(
  projectId: string,
  volumeId: string,
  guidance = "",
): Promise<VolumeDetailGenerationResponse> {
  if (!isFileProjectId(projectId)) {
    throw new Error("volume_workflow_requires_file_project");
  }
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/outline/volumes/${encodeURIComponent(volumeId)}/detail`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ guidance }),
    },
    420000,
  )) as VolumeDetailGenerationResponse;
}

export async function updateProjectOutline(projectId: string, payload: ProjectOutlineUpdate): Promise<ProjectOutline> {
  if (!isFileProjectId(projectId)) {
    throw new Error("three_level_outline_requires_file_project");
  }
  return (await tryFetchJson(`${fileProjectPath(projectId)}/outline`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  })) as ProjectOutline;
}

export async function fetchProjectForeshadowing(projectId: string): Promise<ForeshadowingResponse> {
  return (await tryFetchJson(`${fileProjectPath(projectId)}/foreshadowing`, {
    method: "GET",
  })) as ForeshadowingResponse;
}

export async function updateProjectForeshadowing(
  projectId: string,
  items: ForeshadowingEntry[],
  baseVersion: string,
): Promise<ForeshadowingResponse> {
  return (await tryFetchJson(`${fileProjectPath(projectId)}/foreshadowing`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ items, base_version: baseVersion }),
  })) as ForeshadowingResponse;
}

export async function generateProjectOutline(
  projectId: string,
  mode: OutlineGenerationMode,
  guidance = "",
  restartFrom?: OutlineGenerationPhaseId,
): Promise<GeneratedOutlinePlanResponse> {
  if (!isFileProjectId(projectId)) {
    throw new Error("只有文件项目支持生成大纲");
  }
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/outline/generate`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode, guidance, ...(restartFrom ? { restart_from: restartFrom } : {}) }),
    },
    420000,
  )) as GeneratedOutlinePlanResponse;
}

export async function fetchOutlineExtensionReadiness(
  projectId: string,
): Promise<OutlineExtensionReadinessResponse> {
  if (!isFileProjectId(projectId)) {
    throw new Error("只有文件项目支持后续细纲体检");
  }
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/outline/extension-readiness`,
    { method: "GET" },
  )) as OutlineExtensionReadinessResponse;
}

export async function fetchOutlineGenerationCheckpoints(
  projectId: string,
): Promise<OutlineGenerationCheckpointResponse> {
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/outline/generation-checkpoints`,
    { method: "GET" },
  )) as OutlineGenerationCheckpointResponse;
}

export async function enrichProjectWorld(projectId: string): Promise<ProjectResponse> {
  const path = isFileProjectId(projectId)
    ? `${fileProjectPath(projectId)}/enrich-world`
    : `${apiBase()}/projects/${encodeURIComponent(projectId)}/enrich-world`;
  const response = (await tryFetchJson(path, {
    method: "POST",
  }, LONG_RUNNING_REQUEST_TIMEOUT_MS)) as ProjectResponse;
  return persistProjectIntoMockStore(normalizeProjectResponse(response));
}

export async function enrichProjectRulebook(projectId: string): Promise<ProjectResponse> {
  const response = (await tryFetchJson(`${apiBase()}/projects/${encodeURIComponent(projectId)}/enrich-rulebook`, {
    method: "POST",
  }, 180000)) as ProjectResponse;
  return persistProjectIntoMockStore(normalizeProjectResponse(response));
}

export async function activateProjectStory(projectId: string, storyId: string): Promise<ProjectResponse> {
  try {
    const response = (await tryFetchJson(`${apiBase()}/projects/${encodeURIComponent(projectId)}/activate`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ story_id: storyId }),
    })) as ProjectResponse;
    return persistProjectIntoMockStore(normalizeProjectResponse(response));
  } catch {
    return mockActivateProjectStory(projectId, storyId);
  }
}

export async function branchStory(storyId: string, newStoryId: string, fromChapter: number): Promise<StoryResponse> {
  try {
    return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/branch`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ new_story_id: newStoryId, from_chapter: fromChapter }),
    });
  } catch {
    return mockBranchStory(storyId, newStoryId, fromChapter);
  }
}

export async function renameStory(storyId: string, newStoryId: string): Promise<StoryResponse> {
  try {
    return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/rename`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ new_story_id: newStoryId }),
    });
  } catch {
    return mockRenameStory(storyId, newStoryId);
  }
}

export async function deleteStory(storyId: string): Promise<DeleteStoryResponse> {
  try {
    return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}`, {
      method: "DELETE",
    });
  } catch {
    return mockDeleteStory(storyId);
  }
}

export async function freezeCharacter(storyId: string, characterName: string): Promise<StoryResponse> {
  try {
    return await tryFetchJson(
      `${apiBase()}/stories/${encodeURIComponent(storyId)}/characters/${encodeURIComponent(characterName)}/freeze`,
      {
        method: "POST",
      },
    );
  } catch {
    const story = mockStore.get(storyId);
    if (!story) throw new Error("mock: story_not_found");
    story.characters = story.characters.map((character) =>
      character.name === characterName
        ? { ...character, frozen: true, lifecycle_state: "frozen" }
        : character,
    );
    saveMockStore(mockStore);
    return mockFetchStory(storyId);
  }
}

// ── Outline API ────────────────────────────────────────────────

export async function generateOutline(storyId: string, targetChapters: number = 30): Promise<NovelOutlineResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/outline/generate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ target_chapters: targetChapters }),
  });
}

export async function fetchOutline(storyId: string): Promise<NovelOutlineResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/outline`, {
    method: "GET",
  });
}

export async function updateOutline(storyId: string, payload: {
  chapters: ChapterOutline[];
  overall_arc?: string;
  act_breaks?: Array<{ act: number; start: number; end: number; theme: string }>;
  notes?: string;
}): Promise<NovelOutlineResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/outline`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// ── World Bible API ────────────────────────────────────────────

export async function fetchWorldBible(storyId: string): Promise<WorldBibleResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/world-bible`, {
    method: "GET",
  });
}

export async function updateWorldBible(storyId: string, payload: WorldBibleRequest): Promise<WorldBibleResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/world-bible`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// ── Novel Status API ───────────────────────────────────────────

export async function fetchNovelStatus(storyId: string): Promise<NovelStatusResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/status`, {
    method: "GET",
  });
}

export async function updateNovelStatus(storyId: string, payload: {
  status?: NovelStatusType;
  total_chapters_planned?: number;
}): Promise<NovelStatusResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/status`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// ── Global Novel Type Library API ─────────────────────────────

export async function fetchNovelTypes(): Promise<NovelType[]> {
  return await tryFetchJson(`${apiBase()}/novel-types`, { method: "GET" });
}

export async function createNovelType(payload: NovelTypeWriteRequest): Promise<NovelType> {
  return await tryFetchJson(`${apiBase()}/novel-types`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateNovelType(typeId: string, payload: NovelTypeWriteRequest): Promise<NovelType> {
  return await tryFetchJson(`${apiBase()}/novel-types/${encodeURIComponent(typeId)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteNovelType(typeId: string): Promise<void> {
  await requestWithTimeout(
    `${apiBase()}/novel-types/${encodeURIComponent(typeId)}`,
    { method: "DELETE" },
    async () => undefined,
  );
}
