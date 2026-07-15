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

export type RuntimeEndpoint = {
  api_key: string;
  base_url: string;
  provider: "codexcli" | "openai";
  codex_command: string;
};

export type AgentRuntimeName = "character" | "director" | "writer" | "memory";

export type RuntimeSettings = {
  global: RuntimeEndpoint;
  agents: Record<AgentRuntimeName, RuntimeEndpoint>;
};

export type RuntimeConnectionTarget = "global" | AgentRuntimeName;

export type RuntimeConnectionResult = {
  ok: boolean;
  agent_name: RuntimeConnectionTarget;
  message: string;
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
  builtin: boolean;
};

export type NovelTypeWriteRequest = Omit<NovelType, "builtin">;

export type GenerationJobStatus = "queued" | "running" | "completed" | "failed";

export type GenerationJobResponse = {
  job_id: string;
  story_id: string;
  status: GenerationJobStatus;
  progress: string;
  chapter_number: number | null;
  error: string;
  created_at: string;
  updated_at: string;
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

export type RuntimeSettingsPatch = {
  global?: Partial<RuntimeEndpoint>;
  agents?: Partial<RuntimeSettings["agents"]>;
};

export const CONFIG_AGENT_SETTINGS_STORAGE_KEY = "novel-autogrowth-engine.agent-settings";

export const AGENT_RUNTIME_TARGETS = ["global", "character", "director", "writer", "memory"] as const;

export type AgentRuntimeEntry = {
  mode: "LLM-assisted";
  source: "idle" | "llm" | "fallback";
  fallback_reason: string;
  last_run_chapter: number;
};

export type AgentRuntimeState = {
  character_agent: AgentRuntimeEntry;
  director_agent: AgentRuntimeEntry;
  writer_agent: AgentRuntimeEntry;
  memory_agent: AgentRuntimeEntry;
  outline_agent: AgentRuntimeEntry;
  recent_events: string[];
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

export type SimplifiedReview = {
  schema_version: "simplified-review/v1" | string;
  pass: boolean;
  has_hard_errors: boolean;
  summary: string;
  categories: {
    hard: { label: string; count: number };
    prose: { label: string; count: number };
    ai_flavor: { label: string; count: number };
  };
  issues: Array<{
    category: "hard" | "prose" | "ai_flavor" | string;
    severity: "blocking" | "advisory" | string;
    message: string;
    suggestion: string;
  }>;
  total_issues: number;
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
  simulation_status?: {
    ok?: boolean;
    mode?: "full" | "degraded";
    fallback_agents?: string[];
    recent_events?: string[];
    agents?: Record<string, { source?: string; fallback_reason?: string; last_run_chapter?: number }>;
    world_pulse?: {
      latest?: Record<string, unknown>;
      history?: Array<Record<string, unknown>>;
    };
    visibility_inbox?: Array<Record<string, unknown>>;
  };
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
    revision_safety?: RevisionSafetyReport;
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
  };
  updated_story?: unknown;
};

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
  parent_story_id?: string | null;
  branched_from_chapter?: number | null;
  characters: Array<{
    name: string;
    role: string;
    game_id?: string;
    game_panel?: GamePanel;
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

export type StorySummary = {
  story_id: string;
  current_chapter: number;
  parent_story_id?: string | null;
  branched_from_chapter?: number | null;
};

export type ImportedWorldEntry = {
  name: string;
  description?: string;
};

export type ImportedRelationshipEdge = {
  id?: string;
  source: string;
  target: string;
  relation_type?: string;
  bond?: string;
  origin?: string;
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
  current_state?: string;
  personality?: string;
  speech_style?: string;
  goals?: string[];
  secrets?: string[];
  conflict_hooks?: string[];
};

export type ImportedWorldBlueprint = {
  premise?: string;
  world_rules?: string[];
  power_system?: string[];
  locations?: ImportedWorldEntry[];
  factions?: ImportedWorldEntry[];
  current_arc?: string;
  constraints?: string[];
  progression_rules?: string[];
  economy_rules?: string[];
  quest_rules?: string[];
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
  status: ProjectStatus;
  pipeline_stage?: ProjectPipelineStage;
  active_story_id: string;
  branches: StorySummary[];
  storage_source?: "sqlite" | "file";
};

export type NewFileProjectRequest = {
  mode: "blank" | "inspiration";
  title: string;
  novel_type_id: string;
  idea: string;
};

export type NewFileProjectResponse = ProjectResponse & {
  next_path: string;
};

export type OpeningDirection = {
  id: string;
  title: string;
  hook: string;
  protagonist_goal: string;
  main_conflict: string;
  growth_path: string;
  opening_promise: string;
};

export type OpeningSetup = {
  brief: {
    schema_version: "opening-brief/v1";
    mode: "inspiration";
    novel_type_id: string;
    idea: string;
    working_title: string;
  };
  directions: OpeningDirection[];
  selected_id: string;
  pipeline_stage: ProjectPipelineStage;
  next_path: string;
};

export type ProjectOutlineOverall = {
  story: string;
  protagonist_goal: string;
  main_conflict: string;
  growth_path: string;
  ending_direction: string;
};

export type ProjectOutlineArc = {
  id: string;
  title: string;
  start_chapter: number;
  end_chapter: number;
  goal: string;
  obstacle: string;
  payoff: string;
  end_state: string;
  stage_antagonist: string;
  long_term_antagonist_traces: string[];
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

export type GeneratedOutlinePlanResponse = {
  schema_version: "generated-outline-plan/v1";
  mode: OutlineGenerationMode;
  outline: ProjectOutlineUpdate;
  characters: StoryCharacter[];
  source: "generated";
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
};

export type ChapterDirectionOptions = {
  schema_version: "chapter-direction-options/v1";
  chapter_number: number;
  recommended_id: string;
  selection_rule?: string;
  options: ChapterDirectionOption[];
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
  chapter_direction_options?: ChapterDirectionOptions;
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

export type ManualDraftRequest = {
  chapter_number: number;
  body: string;
  instructions?: string[];
  include_body?: boolean;
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
  status: ProjectStatus;
  pipeline_stage?: ProjectPipelineStage;
  active_story_id: string;
  branches: string[];
  storage_source?: "sqlite" | "file";
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
    return new Map(parsed);
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

export function runtimeTargetLabel(target: RuntimeConnectionTarget): string {
  return target === "global"
    ? "全局默认"
    : target === "character"
      ? "角色代理"
      : target === "director"
        ? "导演代理"
        : target === "writer"
          ? "写作代理"
          : "记忆代理";
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

function defaultRuntimeEndpoint(): RuntimeEndpoint {
  return {
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    provider: "codexcli",
    codex_command: "codex",
  };
}

function blankRuntimeEndpoint(): RuntimeEndpoint {
  return {
    api_key: "",
    base_url: "",
    provider: "openai",
    codex_command: "",
  };
}

export function createDefaultRuntimeSettings(): RuntimeSettings {
  return {
    global: defaultRuntimeEndpoint(),
    agents: {
      character: blankRuntimeEndpoint(),
      director: blankRuntimeEndpoint(),
      writer: blankRuntimeEndpoint(),
      memory: blankRuntimeEndpoint(),
    },
  };
}

export function mergeRuntimeSettings(
  current: RuntimeSettings,
  updates: RuntimeSettingsPatch,
): RuntimeSettings {
  return {
    global: { ...current.global, ...(updates.global ?? {}) },
    agents: {
      ...current.agents,
      ...Object.entries(updates.agents ?? {}).reduce((acc, [key, value]) => {
        acc[key as AgentRuntimeName] = {
          ...current.agents[key as AgentRuntimeName],
          ...value,
        };
        return acc;
      }, {} as RuntimeSettings["agents"]),
    },
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
  mode: AgentSettings["mode"],
  source: AgentRuntimeEntry["source"] = "idle",
  fallbackReason = "",
  lastRunChapter = 0,
): AgentRuntimeEntry {
  return {
    mode,
    source,
    fallback_reason: fallbackReason,
    last_run_chapter: lastRunChapter,
  };
}

function defaultAgentRuntime(mode: AgentSettings["mode"]): AgentRuntimeState {
  return {
    character_agent: defaultRuntimeEntry(mode),
    director_agent: defaultRuntimeEntry(mode),
    writer_agent: defaultRuntimeEntry(mode),
    memory_agent: defaultRuntimeEntry(mode),
    outline_agent: defaultRuntimeEntry(mode),
    recent_events: [],
  };
}

function updateRuntimeForChapter(
  runtime: AgentRuntimeState,
  mode: AgentSettings["mode"],
  chapterNumber: number,
  source: AgentRuntimeEntry["source"],
  fallbackReason = "",
): AgentRuntimeState {
  const nextRuntime = clone(runtime);
  nextRuntime.character_agent = defaultRuntimeEntry(mode, source, fallbackReason, chapterNumber);
  nextRuntime.director_agent = defaultRuntimeEntry(mode, source, fallbackReason, chapterNumber);
  nextRuntime.writer_agent = defaultRuntimeEntry(mode, source, fallbackReason, chapterNumber);
  nextRuntime.memory_agent = defaultRuntimeEntry(mode, source, fallbackReason, chapterNumber);
  nextRuntime.recent_events = [
    ...nextRuntime.recent_events,
    `角色代理：${runtimeSourceLabel(source)}，第 ${chapterNumber} 章${fallbackReason ? `（${fallbackReason}）` : ""}`,
    `导演代理：${runtimeSourceLabel(source)}，第 ${chapterNumber} 章${fallbackReason ? `（${fallbackReason}）` : ""}`,
    `写作代理：${runtimeSourceLabel(source)}，第 ${chapterNumber} 章${fallbackReason ? `（${fallbackReason}）` : ""}`,
    `记忆代理：${runtimeSourceLabel(source)}，第 ${chapterNumber} 章${fallbackReason ? `（${fallbackReason}）` : ""}`,
  ].slice(-8);
  return nextRuntime;
}

function normalizeRuntimeEndpoint(
  value?: Partial<RuntimeEndpoint>,
  fallbackBaseUrl = "https://api.openai.com/v1",
): RuntimeEndpoint {
  return {
    api_key: value?.api_key ?? "",
    base_url: value?.base_url ?? fallbackBaseUrl,
    provider: value?.provider === "openai" ? "openai" : value?.provider === "codexcli" ? "codexcli" : "openai",
    codex_command: value?.codex_command ?? "",
  };
}

function normalizeRuntimeSettings(value?: Partial<RuntimeSettings> | any): RuntimeSettings {
  const base = defaultRuntimeSettings();
  if (!value) {
    return base;
  }

  if ("api_key" in value || "base_url" in value) {
    const endpoint = normalizeRuntimeEndpoint(value as Partial<RuntimeEndpoint>);
    return {
      global: endpoint,
      agents: base.agents,
    };
  }

  return {
    global: normalizeRuntimeEndpoint(value.global),
    agents: {
      character: normalizeRuntimeEndpoint(value.agents?.character, ""),
      director: normalizeRuntimeEndpoint(value.agents?.director, ""),
      writer: normalizeRuntimeEndpoint(value.agents?.writer, ""),
      memory: normalizeRuntimeEndpoint(value.agents?.memory, ""),
    },
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
  const mirroredStory: MockStory = {
    story_id: story.story_id,
    outline: story.outline,
    genre: story.genre,
    style: story.style,
    current_chapter: story.current_chapter,
    agent_settings: clone(story.agent_settings),
    agent_runtime: clone(story.agent_runtime),
    author_constraints: clone(story.author_constraints ?? []),
    world_facts: clone(story.world_facts ?? []),
    characters: clone(story.characters),
    history: clone(story.history),
    initial_story: {
      ...clone(story),
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
  const agentRuntime = defaultAgentRuntime(agentSettings.mode);
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
    story.agent_settings.mode,
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
      fallback_agents: ["character_agent", "director_agent", "memory_agent", "writer_agent"],
      recent_events: clone(story.agent_runtime.recent_events),
      agents: {
        character_agent: clone(story.agent_runtime.character_agent),
        director_agent: clone(story.agent_runtime.director_agent),
        memory_agent: clone(story.agent_runtime.memory_agent),
        writer_agent: clone(story.agent_runtime.writer_agent),
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

async function tryFetchJson(url: string, init: RequestInit, timeoutMs = 30000): Promise<any> {
  console.log('[tryFetchJson] Requesting:', url, init.method);
  console.log('[tryFetchJson] Init:', JSON.stringify(init).slice(0, 200));
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    console.log('[tryFetchJson] Timeout, aborting:', url);
    controller.abort();
  }, timeoutMs);

  try {
    const resp = await fetch(url, { ...init, signal: controller.signal });
    console.log('[tryFetchJson] Response status:', resp.status, resp.statusText);
    console.log('[tryFetchJson] Response headers:', Object.fromEntries(resp.headers.entries()));
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      console.error('[tryFetchJson] Not OK, detail:', detail.slice(0, 500));
      let message = detail ? `${url} failed: ${resp.status} ${detail}` : `${url} failed: ${resp.status}`;
      if (detail) {
        try {
          const parsed = JSON.parse(detail);
          if (typeof parsed?.detail === "string" && parsed.detail.trim()) {
            message = parsed.detail.trim();
          }
        } catch {
          // Keep the raw detail string if it is not JSON.
        }
      }
      throw new Error(message);
    }
    const text = await resp.text();
    console.log('[tryFetchJson] Response text (first 300):', text.slice(0, 300));
    const data = JSON.parse(text);
    console.log('[tryFetchJson] Parsed OK, keys:', Object.keys(data));
    return data;
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

export async function fetchRuntimeSettings(): Promise<RuntimeSettings> {
  try {
    const response = await tryFetchJson(`${apiBase()}/runtime-settings`, {
      method: "GET",
    });
    return normalizeRuntimeSettings(response);
  } catch {
    return mockFetchRuntimeSettings();
  }
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
  console.log('[api] saveRuntimeSettings called, apiBase:', apiBase());
  console.log('[api] saveRuntimeSettings settings:', JSON.stringify(settings).slice(0, 300));
  try {
    const response = await tryFetchJson(`${apiBase()}/runtime-settings`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(settings),
    });
    console.log('[api] saveRuntimeSettings response received, normalizing...');
    const normalized = normalizeRuntimeSettings(response);
    console.log('[api] saveRuntimeSettings done, normalized:', JSON.stringify(normalized).slice(0, 300));
    return normalized;
  } catch (error) {
    console.error('[api] saveRuntimeSettings FAILED:', error);
    return mockSaveRuntimeSettings(settings);
  }
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
  target: RuntimeConnectionTarget,
  modelName?: string,
): Promise<RuntimeConnectionResult> {
  try {
    const response = await tryFetchJson(`${apiBase()}/runtime-settings/test`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        agent_name: target,
        model_name: modelName,
        runtime_settings: settings,
      }),
    });
    return response as RuntimeConnectionResult;
  } catch (error) {
    console.error('Test connection failed:', error);
    throw error;
  }
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
): Promise<BookDissectionReport> {
  if (!isFileProjectId(projectId)) {
    throw new Error("book_dissection_only_supports_file_projects");
  }
  return (await tryFetchJson(`${fileProjectPath(projectId)}/book-dissection/chapter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chapter_number: chapterNumber }),
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

export async function fetchGenerationJob(storyId: string, jobId: string): Promise<GenerationJobResponse> {
  const path = isFileProjectId(storyId)
    ? `${fileProjectPath(storyId)}/generation-jobs/${encodeURIComponent(jobId)}`
    : `${apiBase()}/stories/${encodeURIComponent(storyId)}/generation-jobs/${encodeURIComponent(jobId)}`;
  return (await tryFetchJson(
    path,
    {
      method: "GET",
    },
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
  return (await tryFetchJson(`${fileProjectPath(projectId)}/regenerate-chapter`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chapter_number: chapterNumber, variant, guidance }),
  }, 900000)) as { project: ProjectResponse; story: StoryResponse; generated: Record<string, unknown> };
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

export async function submitProjectManualDraft(
  projectId: string,
  payload: ManualDraftRequest,
): Promise<AgentRevisionResponse> {
  return (await tryFetchJson(
    `${apiBase()}/projects/${encodeURIComponent(projectId)}/manual-draft`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
    180000,
  )) as AgentRevisionResponse;
}

export async function fetchStory(storyId: string): Promise<StoryResponse> {
  try {
    const path = isFileProjectId(storyId)
      ? fileStoryPath(storyId)
      : `${apiBase()}/stories/${encodeURIComponent(storyId)}`;
    const response = (await tryFetchJson(path, {
      method: "GET",
    })) as StoryResponse;
    return persistStoryIntoMockStore(response);
  } catch {
    return mockFetchStory(storyId);
  }
}

export async function createProject(payload: CreateProjectRequest): Promise<ProjectResponse> {
  try {
    const response = (await tryFetchJson(`${apiBase()}/projects`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    })) as ProjectResponse;
    return persistProjectIntoMockStore(response);
  } catch {
    return mockCreateProject(payload);
  }
}

export async function createFileProject(payload: NewFileProjectRequest): Promise<NewFileProjectResponse> {
  return (await tryFetchJson(`${apiBase()}/file-projects`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  })) as NewFileProjectResponse;
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
    status: payload.active_story_id ? "simulating" : "draft",
    pipeline_stage: payload.pipeline_stage ?? (payload.active_story_id ? "environment_ready" : "imported"),
    active_story_id: payload.active_story_id ?? "",
    branches: payload.active_story_id ? [payload.active_story_id] : [],
  };
  mockProjectStore.set(project.project_id, project);
  const activeStory = project.active_story_id ? mockStore.get(project.active_story_id) : null;
  if (activeStory) {
    syncMockStoryAuthorConstraints(activeStory);
    saveMockStore(mockStore);
  }
  saveMockProjectStore(mockProjectStore);
  setMockProjectPreference(true);
  return {
    ...project,
    branches: project.branches.map((storyId) => ({
      story_id: storyId,
      current_chapter: mockStore.get(storyId)?.current_chapter ?? 0,
      parent_story_id: mockStore.get(storyId)?.parent_story_id ?? null,
      branched_from_chapter: mockStore.get(storyId)?.branched_from_chapter ?? null,
    })),
  };
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
  const project = mockProjectStore.get(projectId);
  if (!project) {
    throw new Error("mock: project_not_found");
  }
  return {
    ...project,
    branches: project.branches.map((storyId) => ({
      story_id: storyId,
      current_chapter: mockStore.get(storyId)?.current_chapter ?? 0,
      parent_story_id: mockStore.get(storyId)?.parent_story_id ?? null,
      branched_from_chapter: mockStore.get(storyId)?.branched_from_chapter ?? null,
    })),
    storage_source: project.storage_source,
  };
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
    status: project.status,
    pipeline_stage: project.pipeline_stage ?? "imported",
    active_story_id: project.active_story_id,
    branches: project.branches.map((branch) => branch.story_id),
    storage_source: project.storage_source,
  };
  mockProjectStore.set(project.project_id, mirroredProject);
  saveMockProjectStore(mockProjectStore);
  setMockProjectPreference(true);

  const activeStory = mirroredProject.active_story_id ? mockStore.get(mirroredProject.active_story_id) : null;
  if (activeStory) {
    syncMockStoryAuthorConstraints(activeStory);
    saveMockStore(mockStore);
  }

  return mockFetchProject(project.project_id);
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

export async function listProjects(): Promise<ProjectSummary[]> {
  try {
    const response = (await tryFetchJson(`${apiBase()}/projects`, {
      method: "GET",
    })) as ProjectSummary[];
    const fileProjects = (await tryFetchJson(`${apiBase()}/file-projects`, {
      method: "GET",
    }).catch(() => [])) as ProjectSummary[];
    const seen = new Set(response.map((project) => project.project_id));
    return [...response, ...fileProjects.filter((project) => !seen.has(project.project_id))];
  } catch (err) {
    const fileProjects = (await tryFetchJson(`${apiBase()}/file-projects`, {
      method: "GET",
    }).catch(() => [])) as ProjectSummary[];
    if (fileProjects.length > 0) {
      return fileProjects;
    }
    throw err;
  }
}

export async function fetchProject(projectId: string): Promise<ProjectResponse> {
  try {
    const path = isFileProjectId(projectId)
      ? fileProjectPath(projectId)
      : `${apiBase()}/projects/${encodeURIComponent(projectId)}`;
    const response = (await tryFetchJson(path, {
      method: "GET",
    })) as ProjectResponse;
    return persistProjectIntoMockStore(response);
  } catch {
    return mockFetchProject(projectId);
  }
}

export async function updateProject(projectId: string, payload: UpdateProjectRequest): Promise<ProjectResponse> {
  try {
    const path = isFileProjectId(projectId)
      ? fileProjectPath(projectId)
      : `${apiBase()}/projects/${encodeURIComponent(projectId)}`;
    const response = (await tryFetchJson(path, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    })) as ProjectResponse;
    return persistProjectIntoMockStore(response);
  } catch {
    return mockUpdateProject(projectId, payload);
  }
}

export async function fetchProjectOutline(projectId: string): Promise<ProjectOutline> {
  if (!isFileProjectId(projectId)) {
    throw new Error("three_level_outline_requires_file_project");
  }
  return (await tryFetchJson(`${fileProjectPath(projectId)}/outline`, { method: "GET" })) as ProjectOutline;
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

export async function generateProjectOutline(
  projectId: string,
  mode: OutlineGenerationMode,
  guidance = "",
): Promise<GeneratedOutlinePlanResponse> {
  if (!isFileProjectId(projectId)) {
    throw new Error("只有文件项目支持生成大纲");
  }
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/outline/generate`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode, guidance }),
    },
    180000,
  )) as GeneratedOutlinePlanResponse;
}

export async function enrichProjectWorld(projectId: string): Promise<ProjectResponse> {
  const response = (await tryFetchJson(`${apiBase()}/projects/${encodeURIComponent(projectId)}/enrich-world`, {
    method: "POST",
  }, 180000)) as ProjectResponse;
  return persistProjectIntoMockStore(response);
}

export async function enrichProjectRulebook(projectId: string): Promise<ProjectResponse> {
  const response = (await tryFetchJson(`${apiBase()}/projects/${encodeURIComponent(projectId)}/enrich-rulebook`, {
    method: "POST",
  }, 180000)) as ProjectResponse;
  return persistProjectIntoMockStore(response);
}

export async function activateProjectStory(projectId: string, storyId: string): Promise<ProjectResponse> {
  try {
    const response = (await tryFetchJson(`${apiBase()}/projects/${encodeURIComponent(projectId)}/activate`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ story_id: storyId }),
    })) as ProjectResponse;
    return persistProjectIntoMockStore(response);
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
  const response = await fetch(`${apiBase()}/novel-types/${encodeURIComponent(typeId)}`, { method: "DELETE" });
  if (response.ok) return;

  const text = await response.text().catch(() => "");
  let message = text || `删除失败（${response.status}）`;
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) message = parsed.detail.trim();
  } catch {
    // Preserve the server response when it is not JSON.
  }
  throw new Error(message);
}
