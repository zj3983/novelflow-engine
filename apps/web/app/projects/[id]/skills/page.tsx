"use client";

import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
import { userFacingErrorMessage } from "../../../../lib/user-facing-error";
  importSkillPackFromPath,
  listSkillPacks,
  uninstallSkillModule,
  uninstallSkillPack,
  updateProject,
  uploadSkillPackZip,
  type SkillPackSummary,
} from "../../../../lib/api";

function moduleLabel(pack: SkillPackSummary): string {
  return `${(pack.module_count || 0) + 1} 个可控模块`;
}

const ROOT_MODULE_ID = "root";

function moduleKey(skillId: string, moduleId: string): string {
  return `${skillId}::${moduleId}`;
}

function moduleIdsForPack(pack: SkillPackSummary): string[] {
  return [ROOT_MODULE_ID, ...pack.modules.map((module) => module.module_id)];
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
  const [uninstallingSkillId, setUninstallingSkillId] = useState<string | null>(null);
  const [uninstallingModuleKey, setUninstallingModuleKey] = useState<string | null>(null);
  const enabled = useMemo(() => new Set(project?.enabled_skill_ids ?? []), [project?.enabled_skill_ids]);
  const legacyModuleMode = project?.skill_module_selection_mode === "legacy_all"
    || (project?.skill_module_selection_mode == null && project?.enabled_skill_module_ids == null);
  const enabledModules = useMemo(
    () => new Set(project?.enabled_skill_module_ids ?? []),
    [project?.enabled_skill_module_ids],
  );

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

  async function saveSelection(nextPackIds: string[], nextModuleIds: string[]) {
    if (!project) return;
    setSaving(true);
    setMessage("");
    try {
      await updateProject(projectId, {
        enabled_skill_ids: nextPackIds,
        enabled_skill_module_ids: nextModuleIds,
      });
      await refresh();
      setMessage("已保存模块选择。下一次写作包和提示词预览只会读取已打开的模块。");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function toggleModule(pack: SkillPackSummary, moduleId: string) {
    if (!project) return;
    const nextModules = new Set<string>();
    if (legacyModuleMode) {
      for (const installedPack of packs) {
        if (!enabled.has(installedPack.skill_id)) continue;
        for (const installedModuleId of moduleIdsForPack(installedPack)) {
          nextModules.add(moduleKey(installedPack.skill_id, installedModuleId));
        }
      }
    } else {
      enabledModules.forEach((value) => nextModules.add(value));
    }
    const key = moduleKey(pack.skill_id, moduleId);
    if (nextModules.has(key)) {
      nextModules.delete(key);
    } else {
      nextModules.add(key);
    }
    const nextPacks = new Set(project.enabled_skill_ids ?? []);
    for (const installedPack of packs) {
      const hasSelectedModule = moduleIdsForPack(installedPack).some((installedModuleId) =>
        nextModules.has(moduleKey(installedPack.skill_id, installedModuleId)),
      );
      if (hasSelectedModule) {
        nextPacks.add(installedPack.skill_id);
      } else {
        nextPacks.delete(installedPack.skill_id);
      }
    }
    await saveSelection(Array.from(nextPacks), Array.from(nextModules));
  }

  function isModuleSelected(pack: SkillPackSummary, moduleId: string): boolean {
    if (!enabled.has(pack.skill_id)) return false;
    return legacyModuleMode || enabledModules.has(moduleKey(pack.skill_id, moduleId));
  }

  async function importPath() {
    const value = sourcePath.trim();
    if (!value) return;
    setLoading(true);
    setMessage("");
    try {
      const pack = await importSkillPackFromPath(value);
      setMessage(`已导入：${pack.name}。当前项目未启用，需要时再打开开关。`);
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
      setMessage(`已上传：${pack.name}。当前项目未启用，需要时再打开开关。`);
      await reload();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function uninstallPack(pack: SkillPackSummary) {
    const confirmed = window.confirm(
      `确定卸载“${pack.name}”吗？它会从全局技能库删除，并从所有项目的启用列表移除，但不会删除正文、大纲或角色卡。`,
    );
    if (!confirmed) return;
    setUninstallingSkillId(pack.skill_id);
    setMessage("");
    try {
      const result = await uninstallSkillPack(pack.skill_id);
      await Promise.all([reload(), refresh()]);
      setMessage(`已卸载：${pack.name}，清理了 ${result.affected_project_count} 个项目的启用记录。`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setUninstallingSkillId(null);
    }
  }

  async function uninstallModule(pack: SkillPackSummary, module: SkillPackSummary["modules"][number]) {
    const key = moduleKey(pack.skill_id, module.module_id);
    const confirmed = window.confirm(
      `确定卸载“${module.title || module.module_id}”吗？只会删除这个子 skill，其他模块和正文不会受到影响。`,
    );
    if (!confirmed) return;
    setUninstallingModuleKey(key);
    setMessage("");
    try {
      const result = await uninstallSkillModule(pack.skill_id, module.module_id);
      await Promise.all([reload(), refresh()]);
      setMessage(`已卸载子 skill：${module.title || module.module_id}，清理了 ${result.affected_project_count} 个项目的启用记录。`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setUninstallingModuleKey(null);
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
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{userFacingErrorMessage(error)}</p>
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
            <p className="ws-card__hint">每个包和子 skill 分开控制。只有打开的模块才会进入写作包和提示词。</p>
          </div>
          <span className="ws-toolbar__meta">
            {legacyModuleMode
              ? `${project?.enabled_skill_ids?.length ?? 0} 个旧包配置`
              : `${project?.enabled_skill_module_ids?.length ?? 0} 个模块启用`}
          </span>
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
                    <div className="ws-form-row">
                      <span className="ws-toolbar__meta">{active ? "有模块启用" : "未启用"}</span>
                      <button
                        className="ws-btn ws-btn--danger ws-btn--sm"
                        type="button"
                        disabled={loading || saving || Boolean(uninstallingSkillId)}
                        onClick={() => void uninstallPack(pack)}
                      >
                        {uninstallingSkillId === pack.skill_id ? "卸载中" : "卸载"}
                      </button>
                    </div>
                  </div>
                  {pack.description ? <p className="ws-skill-pack__desc">{pack.description}</p> : null}
                  <div className="ws-skill-module-list">
                    <div className="ws-skill-module">
                      <div className="ws-skill-module__head">
                        <div>
                          <p className="ws-skill-module__title">根 Skill（SKILL.md）</p>
                          <p className="ws-card__hint">root</p>
                        </div>
                        <label className="ws-toggle">
                          <input
                            type="checkbox"
                            checked={isModuleSelected(pack, ROOT_MODULE_ID)}
                            disabled={saving || Boolean(uninstallingSkillId)}
                            onChange={() => void toggleModule(pack, ROOT_MODULE_ID)}
                          />
                          <span>{isModuleSelected(pack, ROOT_MODULE_ID) ? "已启用" : "未启用"}</span>
                        </label>
                      </div>
                      <p className="ws-skill-module__intro">包的总入口说明。关闭后不会读取根 SKILL.md。</p>
                    </div>
                    {pack.modules.map((module) => (
                      <div key={module.module_id} className="ws-skill-module">
                        <div className="ws-skill-module__head">
                          <div>
                            <p className="ws-skill-module__title">{module.title || module.module_id}</p>
                            <p className="ws-card__hint">{module.module_id}</p>
                          </div>
                          <label className="ws-toggle">
                            <input
                              type="checkbox"
                              checked={isModuleSelected(pack, module.module_id)}
                              disabled={saving || Boolean(uninstallingSkillId)}
                              onChange={() => void toggleModule(pack, module.module_id)}
                            />
                            <span>{isModuleSelected(pack, module.module_id) ? "已启用" : "未启用"}</span>
                          </label>
                          <button
                            className="ws-btn ws-btn--danger ws-btn--sm"
                            type="button"
                            disabled={
                              loading || saving || Boolean(uninstallingSkillId) || Boolean(uninstallingModuleKey)
                            }
                            onClick={() => void uninstallModule(pack, module)}
                          >
                            {uninstallingModuleKey === moduleKey(pack.skill_id, module.module_id) ? "卸载中" : "卸载"}
                          </button>
                        </div>
                        <p className="ws-skill-module__usage">用途：{userFacingErrorMessage(moduleUsage(module))}</p>
                        <p className="ws-skill-module__intro">{moduleIntro(module)}</p>
                        {module.summary && module.summary !== module.description ? (
                          <p className="ws-skill-module__summary">{module.summary}</p>
                        ) : null}
                      </div>
                    ))}
                  </div>
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
