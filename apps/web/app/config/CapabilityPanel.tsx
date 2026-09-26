"use client";

import { useEffect, useRef, useState } from "react";
import type { RuntimeSettings, RuntimeStageName } from "../../lib/api";
import { readCapabilities, refreshCapabilities, type CapabilityProfile } from "../../lib/config-capabilities";

const labels: Record<string, string> = {
  streaming: "流式输出", json_mode: "JSON 模式", temperature: "Temperature",
  reasoning_effort: "推理强度", thinking: "Thinking", thinking_budget: "推理预算",
  input_token_limit: "输入上限", context_window: "上下文窗口", max_output_tokens: "输出上限",
};
const sources: Record<string, string> = {
  runtime_observation: "运行验证", provider_metadata: "服务商元数据",
  official_catalog: "官方声明", user_declared: "用户声明", unknown: "未知",
};
const states = { supported: "支持", unsupported: "不支持", unknown: "未知" };
const steps: Record<string, string> = { connectivity: "连接", discovery: "模型发现", ...labels };
const statuses: Record<string, string> = { success: "成功", failed: "失败", skipped: "跳过", ...states };

function StageCapabilities({ settings, stage, disabled }: { settings: RuntimeSettings; stage: RuntimeStageName; disabled: boolean }) {
  const [profile, setProfile] = useState<CapabilityProfile | null>(null);
  const [message, setMessage] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const generation = useRef(0);
  const stageName = stage === "planner" ? "剧情规划" : "正文写作";
  // The whole candidate snapshot includes declarations, endpoint and credentials.
  // Any edit invalidates in-flight UI results; read only calls never probe.
  const snapshot = JSON.stringify(settings);
  useEffect(() => {
    const current = ++generation.current;
    setProfile(null);
    setMessage("配置已变化，正在读取当前能力；读取不会访问服务商。");
    setRefreshing(false);
    if (disabled) return;
    const timer = setTimeout(() => {
      void readCapabilities(JSON.parse(snapshot), stage).then((next) => {
        if (current !== generation.current) return;
        setProfile(next);
        setMessage("当前配置的能力记录已载入。");
      }).catch(() => {
        if (current === generation.current) setMessage("能力记录暂不可用，请检查配置后重试。");
      });
    }, 200);
    return () => { clearTimeout(timer); generation.current++; };
  }, [snapshot, stage, disabled]);

  async function refresh() {
    const current = ++generation.current;
    setRefreshing(true);
    setMessage("正在测试连接、发现模型并刷新能力…");
    try {
      const result = await refreshCapabilities(settings, stage);
      if (current !== generation.current) return;
      setProfile(result.profile);
      setMessage(result.steps.map((item) => `${steps[item.step] ?? item.step}：${statuses[item.status] ?? item.status}${item.step === "discovery" && item.status === "success" ? `（${item.model_count} 个模型${item.selected_model_found ? "，包含当前模型" : "，未列出当前模型"}）` : ""}${item.reason === "cli_budget_best_effort" ? "（CLI 无可验证输出硬上限）" : ""}`).join("；"));
    } catch {
      if (current === generation.current) setMessage("刷新失败，请检查当前模型、密钥和服务商地址后重试。");
    } finally {
      if (current === generation.current) setRefreshing(false);
    }
  }

  return <section aria-label={`${stageName}能力记录`}>
    <h3>{stageName} · {settings.stages[stage].model}</h3>
    <button className="btn btn--secondary" type="button" disabled={disabled || refreshing} onClick={() => void refresh()}>
      {refreshing ? "刷新中…" : `测试并刷新${stageName}能力`}
    </button>
    <p role="status">{message}</p>
    {profile?.output_budget === "best_effort" && <p>CLI 输出预算为 best_effort，不是硬上限；低成本探测已跳过，可单独测试连接。</p>}
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", textAlign: "left", fontSize: "0.85rem" }}>
        <thead><tr><th>能力</th><th>状态</th><th>来源</th><th>验证时间 / 到期时间</th></tr></thead>
        <tbody>{Object.entries(labels).map(([key, label]) => {
          const record = profile?.records[key];
          const expired = record?.expires_at && Date.parse(record.expires_at) <= Date.now();
          const state = expired ? "unknown" : record?.state ?? "unknown";
          return <tr key={key}>
            <td>{label}</td>
            <td>{states[state]}{state === "supported" && record?.value != null ? ` · ${record.value.toLocaleString()}` : ""}{expired ? "（已过期）" : ""}</td>
            <td>{record ? sources[record.source] ?? "未知" : "未知"} {state !== "unknown" && record?.verification_status === "declared" ? "· 声明" : state !== "unknown" && record?.verification_status === "verified" ? "· 已验证" : ""}</td>
            <td>{record?.verified_at ?? "未验证"}<br />{record?.expires_at ?? "未设置到期时间"}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>
  </section>;
}

export function CapabilityPanel({ settings, disabled }: { settings: RuntimeSettings; disabled: boolean }) {
  return <section className="config-card config-card--spacious" aria-label="模型能力与来源">
    <h2>模型能力与来源</h2>
    <p>使用页面当前配置，保存后也可随时刷新。点击测试并刷新将发送最多 4 次短生成请求和 1 次模型发现请求，可能产生少量费用。不会探测大上下文。</p>
    <p>未知能力按保守策略处理；流式未知或不支持时使用完整响应。推理参数和限额无证据时保持未知。</p>
    {(["planner", "writer"] as const).map((stage) => <StageCapabilities key={stage} settings={settings} stage={stage} disabled={disabled} />)}
  </section>;
}
