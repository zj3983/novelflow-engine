import { apiBase, fetchJson } from "./api-client";
import type { RuntimeSettings, RuntimeStageName } from "./api";

export type CapabilityRecord = {
  state: "supported" | "unsupported" | "unknown";
  value: number | null;
  source: string;
  verification_status: string;
  verified_at: string | null;
  expires_at: string | null;
};
export type CapabilityProfile = {
  provider: string;
  model: string;
  protocol: string;
  identity_key: string;
  records: Record<string, CapabilityRecord>;
  output_budget: "best_effort" | "provider_parameter";
};
export type CapabilityRefresh = {
  ok: boolean;
  steps: { step: string; status: string; reason?: string; selected_model_found?: boolean; model_count?: number }[];
  profile: CapabilityProfile;
};

export function readCapabilities(runtime_settings: RuntimeSettings, stage: RuntimeStageName) {
  return fetchJson<CapabilityProfile>(`${apiBase()}/runtime-settings/capabilities`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ stage, runtime_settings }),
  });
}

export function refreshCapabilities(runtime_settings: RuntimeSettings, stage: RuntimeStageName) {
  return fetchJson<CapabilityRefresh>(`${apiBase()}/runtime-settings/refresh-capabilities`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ stage, runtime_settings }),
  }, 90_000);
}
