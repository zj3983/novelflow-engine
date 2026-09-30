import type { RuntimeSettings, RuntimeStageName } from "../../lib/config-capabilities";

export type RuntimeConnectionState = "idle" | "testing" | "success" | "error";

export type RuntimeConnectionStatus = { state: RuntimeConnectionState; message: string; heading?: string };
export type RuntimeConnectionMap = Record<string, RuntimeConnectionStatus>;

export type RuntimeSettingsSnapshot = RuntimeSettings;
