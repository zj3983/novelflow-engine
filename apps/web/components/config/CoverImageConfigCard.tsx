import { useEffect, useState } from "react";

import { revealRuntimeApiKey, type RuntimeImageSettings } from "../../lib/api";

type ImageValidationErrors = Partial<Record<"api_key" | "base_url" | "model", string>>;

type Props = {
  value: RuntimeImageSettings;
  errors: ImageValidationErrors;
  onChange: (next: RuntimeImageSettings) => void;
};

export function CoverImageConfigCard({ value, errors, onChange }: Props) {
  const [showApiKey, setShowApiKey] = useState(false);
  const [revealedApiKey, setRevealedApiKey] = useState("");
  const [revealPending, setRevealPending] = useState(false);
  const [revealError, setRevealError] = useState("");
  const apiKeyIsStored = value.api_key === "********";
  const apiKeyInputValue = apiKeyIsStored ? revealedApiKey : value.api_key;

  useEffect(() => {
    setShowApiKey(false);
    setRevealedApiKey("");
    setRevealError("");
  }, [value.api_key]);

  function update(patch: Partial<RuntimeImageSettings>) {
    onChange({ ...value, ...patch });
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
      setRevealedApiKey(await revealRuntimeApiKey("image"));
      setShowApiKey(true);
    } catch (error) {
      setRevealError(error instanceof Error ? error.message : "读取已保存的封面图片密钥失败");
    } finally {
      setRevealPending(false);
    }
  }

  return (
    <section className="config-card config-card--spacious" aria-label="封面图片模型">
      <div className="config-card__header">
        <div>
          <p className="config-card__eyebrow">IMAGE PIPELINE</p>
          <h2 className="config-card__title">封面图片模型</h2>
          <p className="config-card__subtitle">独立于正文模型配置，用于生成书籍封面底图与标题成图。</p>
        </div>
      </div>

      <div className="config-stack">
        <div className="field">
          <label className="config-image-toggle" htmlFor="config-cover-image-enabled">
            <input
              id="config-cover-image-enabled"
              aria-label="启用封面图片模型"
              type="checkbox"
              checked={value.enabled}
              onChange={(event) => update({ enabled: event.target.checked })}
            />
            <span>
              <strong>启用封面图片模型</strong>
              <small>关闭后保留当前配置，保存时不会用于封面生成。</small>
            </span>
          </label>
        </div>

        <div className="config-grid config-grid--two-up">
          <div className="field">
            <label htmlFor="config-cover-image-base-url">封面图片 API 地址</label>
            <input
              id="config-cover-image-base-url"
              aria-label="封面图片 API 地址"
              aria-invalid={Boolean(errors.base_url)}
              aria-describedby={errors.base_url ? "config-cover-image-base-url-error" : undefined}
              className="text-input"
              value={value.base_url}
              onChange={(event) => update({ base_url: event.target.value })}
              placeholder="https://api.example.com/v1"
              inputMode="url"
            />
            {errors.base_url ? <p id="config-cover-image-base-url-error" className="field-error" role="alert">{errors.base_url}</p> : null}
          </div>
          <div className="field">
            <label htmlFor="config-cover-image-model">封面图片模型名称</label>
            <input
              id="config-cover-image-model"
              aria-label="封面图片模型名称"
              aria-invalid={Boolean(errors.model)}
              aria-describedby={errors.model ? "config-cover-image-model-error" : undefined}
              className="text-input"
              value={value.model}
              onChange={(event) => update({ model: event.target.value })}
              placeholder="cover-model"
            />
            {errors.model ? <p id="config-cover-image-model-error" className="field-error" role="alert">{errors.model}</p> : null}
          </div>
        </div>

        <div className="field">
          <label htmlFor="config-cover-image-api-key">封面图片 API 密钥</label>
          <div className="config-input-with-action">
            <input
              id="config-cover-image-api-key"
              aria-label="封面图片 API 密钥"
              aria-invalid={Boolean(errors.api_key)}
              aria-describedby={errors.api_key ? "config-cover-image-api-key-error" : undefined}
              type={showApiKey ? "text" : "password"}
              className="text-input"
              value={apiKeyInputValue}
              readOnly={apiKeyIsStored && showApiKey}
              onChange={(event) => {
                setRevealedApiKey("");
                update({ api_key: event.target.value });
              }}
              placeholder={apiKeyIsStored ? "输入新密钥以替换" : "请输入封面图片 API 密钥"}
              autoComplete="new-password"
            />
            <button
              className="btn btn--ghost"
              type="button"
              aria-pressed={showApiKey}
              aria-label={showApiKey ? "隐藏封面图片 API 密钥" : "显示封面图片 API 密钥"}
              disabled={revealPending}
              onClick={() => void toggleApiKeyVisibility()}
            >
              {revealPending ? "读取中" : showApiKey ? "隐藏" : "显示"}
            </button>
          </div>
          {errors.api_key ? <p id="config-cover-image-api-key-error" className="field-error" role="alert">{errors.api_key}</p> : null}
          {revealError ? <p className="field-error" role="alert">{revealError}</p> : null}
          {apiKeyIsStored ? <span className="runtime-status__badge runtime-status__badge--success">密钥已保存</span> : null}
        </div>
      </div>
    </section>
  );
}
