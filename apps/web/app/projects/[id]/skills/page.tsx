"use client";

import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
  importSkillPackFromPath,
  listSkillPacks,
  updateProject,
  uploadSkillPackZip,
  type SkillPackSummary,
} from "../../../../lib/api";

function moduleLabel(pack: SkillPackSummary): string {
  return `${pack.module_count || 0} 个子 skill`;
}

const purposeLabels: Record<string, string> = {
  writer: "正文写作",
  reviewer: "审稿检查",
  dialogue: "对话质量",
  style: "语言风格",
  genre: "题材规则",
  continuity: "连续性",
  workflow: "流程规划",
  text: "长文本处理",
  general: "通用",
};

function readablePurpose(purpose: string): string {
  return purposeLabels[purpose] ?? purpose;
}

function moduleIntro(module: SkillPackSummary["modules"][number]): string {
  return module.description || module.summary || "这个子 skill 没有写简介，只会按文件内容进入对应的写作模块。";
}

function moduleUsage(module: SkillPackSummary["modules"][number]): string {
  const purposes = module.purposes?.length ? module.purposes : ["general"];
  return purposes.map(readablePurpose).join(" / ");
}

export default function ProjectSkillsPage() {
  const { project, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const [packs, setPacks] = useState<SkillPackSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [saving, setSaving] = useState(false);
  const enabled = useMemo(() => new Set(project?.enabled_skill_ids ?? []), [project?.enabled_skill_ids]);

  async function reload() {
    setLoading(true);
    setMessage("");
    try {
      setPacks(await listSkillPacks());
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  async function saveEnabled(nextIds: string[]) {
    if (!project) return;
    setSaving(true);
    setMessage("");
    try {
      await updateProject(projectId, { enabled_skill_ids: nextIds });
      await refresh();
      setMessage("已保存项目启用的 skill。下一次写作包和提示词预览会读取这些模块。");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function toggleSkill(skillId: string) {
    const next = new Set(enabled);
    if (next.has(skillId)) {
      next.delete(skillId);
    } else {
      next.add(skillId);
    }
    await saveEnabled(Array.from(next));
  }

  async function importPath() {
    const value = sourcePath.trim();
    if (!value) return;
    setLoading(true);
    setMessage("");
    try {
      const pack = await importSkillPackFromPath(value);
      setMessage(`已导入：${pack.name}`);
      setSourcePath("");
      await reload();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function uploadZip(file: File | null) {
    if (!file) return;
    setLoading(true);
    setMessage("");
    try {
      const pack = await uploadSkillPackZip(file);
      setMessage(`已上传：${pack.name}`);
      await reload();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="Skill 包"
        subtitle="把写作能力拆成可启用的模块。每个子 skill 都会说明用途，写作时再按需要抽取，不把所有内容塞进同一个提示词。"
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : null}

      <section className="ws-card">
        <div className="ws-section-head">
          <div>
            <p className="ws-card__title">导入 Skill 包</p>
            <p className="ws-card__hint">支持根目录包含 SKILL.md 的本地路径，或上传 zip。系统只读取 Markdown 和模板，不执行包内脚本。</p>
          </div>
          <span className="ws-toolbar__meta">{loading ? "处理中" : `${packs.length} 个包`}</span>
        </div>
        <div className="ws-form-row">
          <input
            className="ws-input"
            value={sourcePath}
            onChange={(event) => setSourcePath(event.target.value)}
            placeholder="例如 C:\\Users\\...\\Openwrite_skill"
          />
          <button className="ws-btn" type="button" disabled={loading || !sourcePath.trim()} onClick={() => void importPath()}>
            导入路径
          </button>
        </div>
        <label className="ws-character-mini">
          <strong>上传 zip</strong>
          <input
            className="ws-input"
            type="file"
            accept=".zip,application/zip"
            disabled={loading}
            onChange={(event) => void uploadZip(event.target.files?.[0] ?? null)}
          />
        </label>
        {message ? <p className="ws-card__hint">{message}</p> : null}
      </section>

      <section className="ws-prompt-section">
        <div className="ws-section-head">
          <div>
            <p className="ws-card__title">当前项目启用</p>
            <p className="ws-card__hint">启用的是整个 skill 包。包里的子 skill 会按“写作、审稿、对话、风格、连续性”等用途进入对应阶段。</p>
          </div>
          <span className="ws-toolbar__meta">{project?.enabled_skill_ids?.length ?? 0} 个启用</span>
        </div>
        {packs.length ? (
          <div className="ws-skill-pack-list">
            {packs.map((pack) => {
              const active = enabled.has(pack.skill_id);
              return (
                <article key={pack.skill_id} className="ws-card ws-skill-pack">
                  <div className="ws-section-head">
                    <div>
                      <p className="ws-card__title">{pack.name}</p>
                      <p className="ws-card__hint">
                        {pack.skill_id} · v{pack.version} · {moduleLabel(pack)}
                      </p>
                    </div>
                    <label className="ws-toggle">
                      <input
                        type="checkbox"
                        checked={active}
                        disabled={saving}
                        onChange={() => void toggleSkill(pack.skill_id)}
                      />
                      <span>{active ? "已启用" : "未启用"}</span>
                    </label>
                  </div>
                  {pack.description ? <p className="ws-skill-pack__desc">{pack.description}</p> : null}
                  {pack.modules.length ? (
                    <div className="ws-skill-module-list">
                      {pack.modules.map((module) => (
                        <div key={module.module_id} className="ws-skill-module">
                          <div className="ws-skill-module__head">
                            <div>
                              <p className="ws-skill-module__title">{module.title || module.module_id}</p>
                              <p className="ws-card__hint">{module.module_id}</p>
                            </div>
                            <span className="ws-skill-module__usage">{moduleUsage(module)}</span>
                          </div>
                          <p className="ws-skill-module__intro">{moduleIntro(module)}</p>
                          {module.summary && module.summary !== module.description ? (
                            <p className="ws-skill-module__summary">{module.summary}</p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="ws-card__hint">没有子 skill，写作包只会读取根 SKILL.md。</p>
                  )}
                </article>
              );
            })}
          </div>
        ) : (
          <div className="ws-empty">
            <p className="ws-empty__title">{loading ? "正在读取 skill 包" : "还没有导入 skill 包"}</p>
          </div>
        )}
      </section>
    </div>
  );
}
