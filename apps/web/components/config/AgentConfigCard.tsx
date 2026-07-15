import type { RuntimeConnectionState, RuntimeSettingsSnapshot } from "./types";

type AgentConfigCardProps = {
  label: string;
  value: RuntimeSettingsSnapshot["agents"][keyof RuntimeSettingsSnapshot["agents"]];
  inherited: RuntimeSettingsSnapshot["global"];
  status: RuntimeConnectionState;
  statusMessage: string;
  modelName: string;
  onChange: (next: RuntimeSettingsSnapshot["agents"][keyof RuntimeSettingsSnapshot["agents"]]) => void;
  onTest: () => void;
};

export function AgentConfigCard({
  label,
  value,
  inherited,
  status,
  statusMessage,
  modelName,
  onChange,
  onTest,
}: AgentConfigCardProps) {
  const effectiveBaseUrl = value.base_url.trim() || inherited.base_url;
  const effectiveApiKey = value.api_key.trim() || inherited.api_key;
  const hasOverride = Boolean(value.api_key.trim() || value.base_url.trim());

  return (
    <article className="config-card config-card--compact" aria-label={label}>
      <div className="config-card__header">
        <div>
          <h3 className="config-card__title">{label}</h3>
        </div>
      </div>

      <div className="config-stack">
        <div className="field">
          <label htmlFor={`config-${label}-api-key`}>{label} API 密钥</label>
          <input
            id={`config-${label}-api-key`}
            aria-label={`${label} API 密钥`}
            type="password"
            className="text-input"
            value={value.api_key}
            onChange={(event) => onChange({ ...value, api_key: event.target.value })}
          />
        </div>

        <div className="field">
          <label htmlFor={`config-${label}-base-url`}>{label} 接口地址</label>
          <input
            id={`config-${label}-base-url`}
            aria-label={`${label} 接口地址`}
            className="text-input"
            value={value.base_url}
            onChange={(event) => onChange({ ...value, base_url: event.target.value })}
          />
        </div>

        <div className="config-card__note config-card__note--inline">
          <p className="hint">{hasOverride ? "使用独立覆盖" : "继承全局默认"}</p>
          <p className="hint">模型：{modelName || "未填写"}</p>
          <p className="hint">地址：{effectiveBaseUrl || "未设置"}</p>
          <p className="hint">密钥：{effectiveApiKey ? "已配置" : "未配置"}</p>
        </div>

        <div className="config-card__footer">
          <button className="btn btn--ghost" type="button" onClick={onTest}>
            测试{label}连接
          </button>
          <p className="config-status" aria-live="polite">
            <span className={`runtime-status__badge runtime-status__badge--${status}`}>
              {status === "idle" ? "待测" : status === "testing" ? "测试中" : status === "success" ? "正常" : "失败"}
            </span>
            <span className="runtime-status__text">
              {statusMessage || "留空则继承全局默认。"}
            </span>
          </p>
        </div>
      </div>
    </article>
  );
}
