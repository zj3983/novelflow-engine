import type { RuntimeSettings, RuntimeStageName } from "../../lib/api";

export type RuntimeConnectionState = "idle" | "testing" | "success" | "error";

export type RuntimeConnectionStatus = { state: RuntimeConnectionState; message: string };
export type RuntimeConnectionMap = Record<string, RuntimeConnectionStatus>;

export type RuntimeSettingsSnapshot = RuntimeSettings;
