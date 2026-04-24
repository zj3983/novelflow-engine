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
          <p className="config-card__eyebrow">全局默认配置</p>
          <h2 className="config-card__title">全局默认配置</h2>
        </div>
        <p className="config-card__subtitle">这里保存所有 Agent 共享的默认 API 信息。</p>
      </div>

      <div className="config-stack">
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
