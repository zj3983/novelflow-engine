import { apiBase, fetchJson } from "./api-client";

export type RuntimeStageName = "planner" | "writer";
export type RuntimeProviderAccount = { api_key: string; base_url: string; custom_models: string[]; codex_command: string };
export type RuntimeImageSettings = { enabled: boolean; api_key: string; base_url: string; model: string };
export type RuntimeSettings = {
  accounts: Record<string, RuntimeProviderAccount>;
  stages: Record<RuntimeStageName, { provider_id: string; model: string }>;
  image: RuntimeImageSettings;
};
export type RuntimeProviderDefinition = {
  provider_id: string; name: string; default_base_url: string;
  planner_models: string[]; writer_models: string[];
  requires_api_key: boolean; base_url_editable: boolean;
  uses_local_command: boolean; default_command: string; account_label: string;
};
export type ModelUsability = {
  status: "ready" | "untested" | "connection_error" | "blocked";
  heading: string; message: string; tone: string; can_continue: boolean;
  actions: { id: "test" | "edit_connection" | "choose_model"; label: string }[];
};
export type ProductModel = { name: string; selectable: boolean; message: string; can_test: boolean };

const base = () => `${apiBase()}/runtime-settings/product`;
async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  try {
    return await fetchJson<T>(`${base()}${path}`, {
      method, headers: { "content-type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    }, 90_000);
  } catch {
    throw new Error("暂时无法完成操作，请检查连接设置后重试。");
  }
}
export const createDefaultRuntimeSettings = (): RuntimeSettings => ({
  accounts: {}, stages: { planner: { provider_id: "codexcli", model: "" }, writer: { provider_id: "codexcli", model: "" } },
  image: { enabled: false, api_key: "", base_url: "", model: "" },
});
export const fetchRuntimeSettings = () => request<RuntimeSettings>("");
export const fetchRuntimeProviderCatalog = () => request<{ providers: RuntimeProviderDefinition[] }>("/providers");
export const saveRuntimeSettings = (settings: RuntimeSettings) => request<RuntimeSettings>("", "PUT", settings);
export const readModelStatus = (settings: RuntimeSettings, stage: RuntimeStageName) => request<ModelUsability>("/model-status", "POST", { settings, stage });
export const testModel = (settings: RuntimeSettings, stage: RuntimeStageName) => request<ModelUsability>("/test-model", "POST", { settings, stage });
export const discoverRuntimeModels = (settings: RuntimeSettings, provider_id: string) => request<{ message: string; models: ProductModel[] }>("/discover-models", "POST", { settings, provider_id });
// Revealing a saved key remains an explicit user action in the connection form.
export async function revealRuntimeApiKey(provider_id: string): Promise<string> {
  try {
    const result = await fetchJson<{ api_key: string }>(`${apiBase()}/runtime-settings/reveal-api-key`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ provider_id }),
    });
    return result.api_key;
  } catch { throw new Error("暂时无法显示已保存的密钥，请稍后重试。"); }
}
