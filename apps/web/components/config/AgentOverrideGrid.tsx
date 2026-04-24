import type { RuntimeSettingsSnapshot } from "./types";
import { AgentConfigCard } from "./AgentConfigCard";

export type AgentOverrideMeta = {
  key: keyof RuntimeSettingsSnapshot["agents"];
  label: string;
  modelName: string;
};

type AgentOverrideGridProps = {
  agents: RuntimeSettingsSnapshot["agents"];
  inherited: RuntimeSettingsSnapshot["global"];
  statuses: Record<
    keyof RuntimeSettingsSnapshot["agents"],
    {
      state: "idle" | "testing" | "success" | "error";
      message: string;
    }
  >;
  onChange: (agent: keyof RuntimeSettingsSnapshot["agents"], next: RuntimeSettingsSnapshot["agents"][keyof RuntimeSettingsSnapshot["agents"]]) => void;
  onTest: (agent: keyof RuntimeSettingsSnapshot["agents"]) => void;
  meta: AgentOverrideMeta[];
};

export function AgentOverrideGrid({
  agents,
  inherited,
  statuses,
  onChange,
  onTest,
  meta,
}: AgentOverrideGridProps) {
  return (
    <section className="config-card config-card--grid" aria-label="Agent 独立覆盖">
      <div className="config-card__header">
        <div>
          <p className="config-card__eyebrow">Agent 独立覆盖</p>
          <h2 className="config-card__title">四个 Agent 的独立覆盖</h2>
        </div>
        <p className="config-card__subtitle">每个卡片都可以单独覆盖 API 密钥与接口地址。</p>
      </div>

      <div className="config-grid">
        {meta.map(({ key, label, modelName }) => (
          <AgentConfigCard
            key={key}
            label={label}
            value={agents[key]}
            inherited={inherited}
            status={statuses[key].state}
            statusMessage={statuses[key].message}
            modelName={modelName}
            onChange={(next) => onChange(key, next)}
            onTest={() => onTest(key)}
          />
        ))}
      </div>
    </section>
  );
}
