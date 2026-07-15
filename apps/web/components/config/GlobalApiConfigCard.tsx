import type { RuntimeConnectionState, RuntimeSettingsSnapshot } from "./types";

type GlobalApiConfigCardProps = {
  value: RuntimeSettingsSnapshot["global"];
  status: RuntimeConnectionState;
  statusMessage: string;
  onChange: (next: RuntimeSettingsSnapshot["global"]) => void;
  onTest: () => void;
};

export function GlobalApiConfigCard({
  value,
  status,
  statusMessage,
  onChange,
  onTest,
}: GlobalApiConfigCardProps) {
  return (
    <section className="config-card config-card--spacious" aria-label="全局默认配置">
      <div className="config-card__header">
        <div>
          <h2 className="config-card__title">全局默认配置</h2>
        </div>
      </div>

      <div className="config-stack">
        <div className="field">
          <label htmlFor="config-global-provider">模型来源</label>
          <select
            id="config-global-provider"
            aria-label="模型来源"
            className="text-input"
            value={value.provider}
            onChange={(event) =>
              onChange({
                ...value,
                provider: event.target.value as typeof value.provider,
              })
            }
          >
            <option value="codexcli">Codex CLI</option>
            <option value="openai">OpenAI 兼容 API</option>
          </select>
        </div>

        {value.provider === "codexcli" ? (
          <div className="field">
            <label htmlFor="config-global-codex-command">Codex CLI 命令</label>
            <input
              id="config-global-codex-command"
              aria-label="Codex CLI 命令"
              className="text-input"
              value={value.codex_command}
              onChange={(event) => onChange({ ...value, codex_command: event.target.value })}
              placeholder="codex"
            />
          </div>
        ) : null}

        {value.provider === "openai" ? (
          <>
            <div className="field">
              <label htmlFor="config-global-api-key">全局 API 密钥</label>
              <input
                id="config-global-api-key"
                aria-label="全局 API 密钥"
                type="password"
                className="text-input"
                value={value.api_key}
                onChange={(event) => onChange({ ...value, api_key: event.target.value })}
              />
            </div>

            <div className="field">
              <label htmlFor="config-global-base-url">全局接口地址</label>
              <input
                id="config-global-base-url"
                aria-label="全局接口地址"
                className="text-input"
                value={value.base_url}
                onChange={(event) => onChange({ ...value, base_url: event.target.value })}
              />
            </div>
          </>
        ) : null}

        <div className="config-card__footer">
          <button className="btn btn--ghost" type="button" onClick={onTest}>
            测试连接
          </button>
          <p className="config-status" aria-live="polite">
            <span className={`runtime-status__badge runtime-status__badge--${status}`}>
              {status === "idle" ? "待测" : status === "testing" ? "测试中" : status === "success" ? "正常" : "失败"}
            </span>
            <span className="runtime-status__text">
              {statusMessage || "留空即可沿用当前环境中的默认 API。"}
            </span>
          </p>
        </div>
      </div>
    </section>
  );
}
