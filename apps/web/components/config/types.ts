import type { RuntimeSettings, RuntimeStageName } from "../../lib/api";

export type RuntimeConnectionState = "idle" | "testing" | "success" | "error";

export type RuntimeConnectionMap = Record<
  RuntimeStageName,
  { state: RuntimeConnectionState; message: string }
>;

export type RuntimeSettingsSnapshot = RuntimeSettings;
