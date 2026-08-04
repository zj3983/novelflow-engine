import { Eye, EyeOff, PlugZap, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  discoverRuntimeModels,
  revealRuntimeApiKey,
  type RuntimeDiscoveredModel,
  type RuntimeProviderAccount,
  type RuntimeProviderDefinition,
  type RuntimeSettings,
} from "../../lib/api";
import type { RuntimeConnectionStatus } from "./types";

type Props = {
  value: RuntimeSettings;
  providers: RuntimeProviderDefinition[];
  statuses: Record<string, RuntimeConnectionStatus>;
  disabled: boolean;
  onChange: (next: RuntimeSettings) => void;
  onTest: (providerId: string, model?: string) => void;
};

function accountFor(value: RuntimeSettings, provider: RuntimeProviderDefinition): RuntimeProviderAccount {
  return value.accounts[provider.provider_id] ?? {
    api_key: "",
    base_url: provider.default_base_url,
    custom_models: [],
    codex_command: provider.protocol === "codex_cli" ? "codex" : provider.protocol === "antigravity_cli" ? "agy" : "",
  };
}

export function ProviderAccountsCard({ value, providers, statuses, disabled, onChange, onTest }: Props) {
  const [selectedId, setSelectedId] = useState(providers[0]?.provider_id ?? "codexcli");
  const [showKey, setShowKey] = useState(false);
  const [revealedKey, setRevealedKey] = useState("");
  const [revealError, setRevealError] = useState("");
  const [discoveredModels, setDiscoveredModels] = useState<RuntimeDiscoveredModel[]>([]);
  const [discoveryState, setDiscoveryState] = useState<"idle" | "loading" | "error">("idle");
  const [discoveryMessage, setDiscoveryMessage] = useState("");
  const selected = providers.find((provider) => provider.provider_id === selectedId) ?? providers[0];
  const account = selected ? accountFor(value, selected) : null;
  const status = statuses[selectedId] ?? { state: "idle", message: "" };
  const storedKey = account?.api_key === "********";
  const keyValue = storedKey ? revealedKey : (account?.api_key ?? "");

  useEffect(() => {
    if (providers.length > 0 && !providers.some((provider) => provider.provider_id === selectedId)) {
      setSelectedId(providers[0].provider_id);
    }
  }, [providers, selectedId]);

  useEffect(() => {
    setShowKey(false);
    setRevealedKey("");
    setRevealError("");
    setDiscoveredModels([]);
    setDiscoveryState("idle");
    setDiscoveryMessage("");
  }, [selectedId, disabled]);

  const selectedModels = useMemo(() => {
    if (!selected || !account) return [];
    return Array.from(new Set([...selected.planner_models, ...selected.writer_models, ...account.custom_models]));
  }, [account, selected]);

  if (!selected || !account) return null;
  const activeAccount = account;

  function updateAccount(patch: Partial<RuntimeProviderAccount>) {
    onChange({
      ...value,
      accounts: { ...value.accounts, [selected.provider_id]: { ...activeAccount, ...patch } },
    });
  }

  async function toggleKey() {
    if (showKey) {
      setShowKey(false);
      setRevealedKey("");
      return;
    }
    if (!storedKey) {
      setShowKey(true);
      return;
    }
    setRevealError("");
    try {
      setRevealedKey(await revealRuntimeApiKey(selected.provider_id));
      setShowKey(true);
    } catch (error) {
      setRevealError(error instanceof Error ? error.message : "读取已保存密钥失败");
    }
  }

  async function discoverModels() {
    setDiscoveryState("loading");
    setDiscoveryMessage("");
    try {
      const result = await discoverRuntimeModels(value, selected.provider_id);
      setDiscoveredModels(result.models);
      setDiscoveryState("idle");
      setDiscoveryMessage(result.models.length ? `发现 ${result.models.length} 个候选模型` : "没有发现模型");
    } catch (error) {
      setDiscoveryState("error");
      setDiscoveryMessage(error instanceof Error ? error.message : "获取模型列表失败");
    }
  }

  function toggleDiscoveredModel(model: RuntimeDiscoveredModel, enabled: boolean) {
    if (model.compatibility === "unsupported") return;
    const next = enabled
      ? Array.from(new Set([...activeAccount.custom_models, model.model_id]))
      : activeAccount.custom_models.filter((item) => item !== model.model_id);
    updateAccount({ custom_models: next });
  }

  function compatibilityLabel(model: RuntimeDiscoveredModel) {
    if (model.compatibility === "supported") return "可用于写作";
    if (model.compatibility === "unsupported") return "不可用于写作";
    return "需要测试";
  }

  return (
    <section className="config-card config-card--spacious" aria-label="供应商账号">
      <div className="config-card__header">
        <div>
          <h2 className="config-card__title">供应商账号</h2>
          <p className="config-card__subtitle">每家供应商独立保存密钥、地址和自定义模型。</p>
        </div>
      </div>

      <div className="provider-account-layout">
        <nav className="provider-account-list" aria-label="供应商列表">
          {providers.map((provider) => (
            <button
              type="button"
              className={`provider-account-list__item${provider.provider_id === selected.provider_id ? " is-active" : ""}`}
              aria-current={provider.provider_id === selected.provider_id ? "true" : undefined}
              disabled={disabled}
              key={provider.provider_id}
              onClick={() => setSelectedId(provider.provider_id)}
            >
              <span>{provider.name}</span>
              <small>{value.accounts[provider.provider_id]?.api_key === "********" || !provider.requires_api_key ? "可用" : "未配置"}</small>
            </button>
          ))}
        </nav>

        <div className="provider-account-editor">
          <div className="config-card__header">
            <div>
              <h3 className="config-card__title">{selected.name}</h3>
              <p className="config-card__subtitle">{selected.help_text}</p>
            </div>
            <button className="btn btn--ghost" type="button" disabled={disabled || status.state === "testing"} onClick={() => onTest(selected.provider_id)}>
              <PlugZap size={16} aria-hidden="true" />
              {status.state === "testing" ? "测试中" : "测试连接"}
            </button>
          </div>

          {selected.protocol.endsWith("_cli") ? (
            <div className="field">
              <label htmlFor="provider-cli-command">{selected.name} 命令</label>
              <input id="provider-cli-command" aria-label={`${selected.name} 命令`} className="text-input" value={account.codex_command} disabled={disabled} onChange={(event) => updateAccount({ codex_command: event.target.value })} />
            </div>
          ) : (
            <div className="config-grid config-grid--two-up">
              <div className="field">
                <label htmlFor="provider-api-key">API 密钥</label>
                <div className="config-input-with-action">
                  <input id="provider-api-key" aria-label={`${selected.name} API 密钥`} className="text-input" type={showKey ? "text" : "password"} value={keyValue} readOnly={storedKey && showKey} disabled={disabled} placeholder={storedKey ? "输入新密钥以替换" : "请输入 API 密钥"} onChange={(event) => { setRevealedKey(""); updateAccount({ api_key: event.target.value }); }} />
                  <button className="btn btn--icon" type="button" title={showKey ? "隐藏密钥" : "显示密钥"} aria-label={showKey ? `隐藏 ${selected.name} API 密钥` : `显示 ${selected.name} API 密钥`} disabled={disabled} onClick={() => void toggleKey()}>
                    {showKey ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
                {storedKey ? <span className="runtime-status__badge runtime-status__badge--success">密钥已保存</span> : null}
                {revealError ? <p className="field-error" role="alert">{revealError}</p> : null}
              </div>
              <div className="field">
                <label htmlFor="provider-base-url">API 地址</label>
                <input id="provider-base-url" aria-label={`${selected.name} API 地址`} className="text-input" value={account.base_url} readOnly={!selected.base_url_editable} disabled={disabled} onChange={(event) => updateAccount({ base_url: event.target.value })} />
              </div>
            </div>
          )}

          <div className="field">
            <label htmlFor="provider-custom-models">自定义模型</label>
            <input id="provider-custom-models" aria-label={`${selected.name} 自定义模型`} className="text-input" value={account.custom_models.join(", ")} disabled={disabled} placeholder="多个模型用逗号分隔" onChange={(event) => updateAccount({ custom_models: event.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean) })} />
            <small className="field-help">当前可选模型：{selectedModels.join("、") || "请添加自定义模型"}</small>
          </div>

          <div className="provider-model-catalog">
            <div className="provider-model-catalog__header">
              <div>
                <h4>模型列表</h4>
                <p>发现结果只表示账号可见，勾选后才会加入写作模型。</p>
              </div>
              <button className="btn btn--ghost" type="button" disabled={disabled || discoveryState === "loading"} onClick={() => void discoverModels()}>
                <RefreshCw size={16} aria-hidden="true" />
                {discoveryState === "loading" ? "获取中" : "获取模型列表"}
              </button>
            </div>
            {discoveryMessage ? <p className={discoveryState === "error" ? "field-error" : "field-help"}>{discoveryMessage}</p> : null}
            {discoveredModels.length ? (
              <div className="provider-model-list">
                {discoveredModels.map((model) => (
                  <div className={`provider-model-row provider-model-row--${model.compatibility}`} key={model.model_id}>
                    <input
                      type="checkbox"
                      aria-label={`启用模型 ${model.model_id}`}
                      checked={activeAccount.custom_models.includes(model.model_id)}
                      disabled={disabled || model.compatibility === "unsupported"}
                      onChange={(event) => toggleDiscoveredModel(model, event.target.checked)}
                    />
                    <span className="provider-model-row__body">
                      <strong>{model.model_id}</strong>
                      <small>{model.endpoint} · {model.reason}</small>
                    </span>
                    <span className={`runtime-status__badge runtime-status__badge--${model.compatibility === "supported" ? "success" : model.compatibility === "unsupported" ? "error" : "warning"}`}>
                      {compatibilityLabel(model)}
                    </span>
                    {model.compatibility !== "unsupported" ? (
                      <button
                        className="btn btn--ghost provider-model-row__test"
                        type="button"
                        aria-label={`测试模型 ${model.model_id}`}
                        disabled={disabled || status.state === "testing"}
                        onClick={() => onTest(selected.provider_id, model.model_id)}
                      >
                        测试
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          <p className="config-status" aria-live="polite">
            <span className={`runtime-status__badge runtime-status__badge--${status.state}`}>{status.state === "success" ? "正常" : status.state === "error" ? "失败" : status.state === "testing" ? "测试中" : "待测"}</span>
            {status.message ? <span className="runtime-status__text">{status.message}</span> : null}
          </p>
        </div>
      </div>
    </section>
  );
}
