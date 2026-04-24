import type {
  AgentSettings,
  RuntimeConnectionTarget,
  RuntimeSettings,
} from "../../lib/api";

export type RuntimeConnectionState = "idle" | "testing" | "success" | "error";

export type RuntimeConnectionMap = Record<
  RuntimeConnectionTarget,
  {
    state: RuntimeConnectionState;
    message: string;
  }
>;

export type RuntimeStrategySettings = AgentSettings;

export type RuntimeStrategyField = {
  key: keyof Pick<
    RuntimeStrategySettings,
    "mode" | "global_model" | "character_model" | "director_model" | "writer_model" | "memory_model" | "temperature" | "new_character_policy"
  >;
  label: string;
};

export type RuntimeSettingsSnapshot = RuntimeSettings;
