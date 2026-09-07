"use client";

import type { RuntimeOutlinePlanningSettings, RuntimeSettings } from "../../lib/api";

type Props = {
  value: RuntimeOutlinePlanningSettings;
  disabled: boolean;
  onChange: (next: RuntimeOutlinePlanningSettings) => void;
};

export function OutlinePlanningCard({ value, disabled, onChange }: Props) {
  return (
    <section className="config-card" aria-label="大纲规划">
      <h2>大纲规划</h2>
      <p className="config-card__hint">
        开书大纲的生成方式。k3 等推理型模型出完整大纲很慢，建议开启分相与流式。
      </p>
      <label className="config-field config-field--inline">
        <input
          type="checkbox"
          checked={value.split_phases}
          disabled={disabled}
          onChange={(event) => onChange({ ...value, split_phases: event.target.checked })}
          aria-label="分相生成"
        />
        <span>
          分相生成（结构总纲 → 角色阵容 → 章节窗口 三次小调用，慢模型更稳）
        </span>
      </label>
      <label className="config-field config-field--inline">
        <input
          type="checkbox"
          checked={value.stream}
          disabled={disabled}
          onChange={(event) => onChange({ ...value, stream: event.target.checked })}
          aria-label="流式读取"
        />
        <span>
          流式读取模型响应（长生成期间保持连接活跃，不被超时杀死）
        </span>
      </label>
      <label className="config-field">
        <span>单次调用超时（秒）</span>
        <input
          type="number"
          min={60}
          max={7200}
          step={60}
          value={value.timeout_seconds}
          disabled={disabled}
          onChange={(event) => {
            const next = Number(event.target.value);
            onChange({
              ...value,
              timeout_seconds: Number.isFinite(next) ? next : value.timeout_seconds,
            });
          }}
          aria-label="单次调用超时秒数"
        />
      </label>
    </section>
  );
}
