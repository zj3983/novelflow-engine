import { useEffect, useState } from "react";

import { revealRuntimeApiKey, type CodexCLIInfo, type RuntimeSettings } from "../../lib/api";

type Props = {
  value: RuntimeSettings;
  cliInfo: CodexCLIInfo | null;
  disabled: boolean;
  onChange: (next: RuntimeSettings) => void;
};

export function GlobalApiConfigCard({ value, cliInfo, disabled, onChange }: Props) {
  const selected = value.providers[value.provider];
  const [showApiKey, setShowApiKey] = useState(false);
  const [revealedApiKey, setRevealedApiKey] = useState("");
  const [revealPending, setRevealPending] = useState(false);
  const [revealError, setRevealError] = useState("");
  const apiKeyIsStored = selected.api_key === "********";
  const apiKeyInputValue = apiKeyIsStored ? revealedApiKey : selected.api_key;

  useEffect(() => {
    setShowApiKey(false);
    setRevealedApiKey("");
    setRevealError("");
  }, [value.provider]);

  const updateLabel =
    cliInfo?.update_status === "current"
      ? "已是最新版本"
      : cliInfo?.update_status === "available"
        ? `有新版本 ${cliInfo.latest_version}`
        : "当前状态不可用";

  function updateSelected(patch: Partial<typeof selected>) {
    onChange({
      ...value,
      providers: {
        ...value.providers,
        [value.provider]: { ...selected, ...patch },
      },
    });
  }

  async function toggleApiKeyVisibility() {
    if (showApiKey) {
      setShowApiKey(false);
      setRevealedApiKey("");
      setRevealError("");
      return;
    }
    if (!apiKeyIsStored) {
      setShowApiKey(true);
      return;
    }

    setRevealPending(true);
    setRevealError("");
    try {
      setRevealedApiKey(await revealRuntimeApiKey(value.provider));
      setShowApiKey(true);
    } catch (error) {
      setRevealError(error instanceof Error ? error.message : "读取已保存密钥失败");
    } finally {
      setRevealPending(false);
    }
  }

  return (
    <section className="config-card config-card--spacious" aria-label="模型执行方式" aria-busy={disabled || revealPending}>
      <div className="config-card__header">
        <h2 className="config-card__title">模型执行方式</h2>
      </div>

      <div className="config-stack">
        <div className="field">
          <label htmlFor="config-global-provider">模型提供方</label>
          <select
            id="config-global-provider"
            aria-label="模型提供方"
            className="text-input"
            value={value.provider}
            disabled={disabled}
            onChange={(event) => onChange({ ...value, provider: event.target.value as RuntimeSettings["provider"] })}
          >
            <option value="codexcli">Codex CLI</option>
            <option value="openai">OpenAI 兼容 API</option>
          </select>
        </div>

        {value.provider === "codexcli" ? (
          <div className="config-grid config-grid--two-up">
            <div className="field">
              <label htmlFor="config-global-codex-command">Codex CLI 命令</label>
              <input
                id="config-global-codex-command"
                aria-label="Codex CLI 命令"
                className="text-input"
                value={selected.codex_command}
                disabled={disabled}
                onChange={(event) => updateSelected({ codex_command: event.target.value })}
                placeholder="codex"
              />
            </div>
            <div className="field">
              <label>CLI 版本</label>
              <div className="config-readonly" aria-label="CLI 版本">
                <span>{cliInfo?.available ? cliInfo.version : "暂未获取"}</span>
                <span
                  className={`runtime-status__badge runtime-status__badge--${
                    cliInfo?.update_status === "current"
                      ? "success"
                      : cliInfo?.update_status === "available"
                        ? "warning"
                        : "idle"
                  }`}
                >
                  {updateLabel}
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="config-grid config-grid--two-up">
            <div className="field">
              <label htmlFor="config-global-api-key">全局 API 密钥</label>
              <div className="config-input-with-action">
                <input
                  id="config-global-api-key"
                  aria-label="全局 API 密钥"
                  type={showApiKey ? "text" : "password"}
                  className="text-input"
                  value={apiKeyInputValue}
                  disabled={disabled}
                  readOnly={apiKeyIsStored && showApiKey}
                  onChange={(event) => {
                    setRevealedApiKey("");
                    updateSelected({ api_key: event.target.value });
                  }}
                  placeholder={apiKeyIsStored ? "输入新密钥以替换" : "请输入 API 密钥"}
                  autoComplete="new-password"
                />
                <button
                  className="btn btn--ghost"
                  type="button"
                  aria-pressed={showApiKey}
                  aria-label={showApiKey ? "隐藏 API 密钥" : "显示 API 密钥"}
                  disabled={disabled || revealPending}
                  onClick={toggleApiKeyVisibility}
                >
                  {revealPending ? "读取中" : showApiKey ? "隐藏" : "显示"}
                </button>
              </div>
              {revealError ? <p className="field-error" role="alert">{revealError}</p> : null}
              {apiKeyIsStored ? (
                <span className="runtime-status__badge runtime-status__badge--success">密钥已保存</span>
              ) : null}
            </div>
            <div className="field">
              <label htmlFor="config-global-base-url">全局 API 地址</label>
              <input
                id="config-global-base-url"
                aria-label="全局 API 地址"
                className="text-input"
                value={selected.base_url}
                disabled={disabled}
                onChange={(event) => updateSelected({ base_url: event.target.value })}
              />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
