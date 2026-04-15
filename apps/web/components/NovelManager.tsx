"use client";

import { useEffect, useState } from "react";

import {
  fetchOutline,
  fetchWorldBible,
  fetchNovelStatus,
  generateOutline,
  updateOutline,
  updateWorldBible,
  updateNovelStatus,
  type NovelOutlineResponse,
  type WorldBibleResponse,
  type NovelStatusResponse,
  type NovelStatusType,
} from "../lib/api";

interface NovelManagerProps {
  storyId: string;
}

const STATUS_LABELS: Record<NovelStatusType, string> = {
  draft: "草稿",
  outlining: "大纲阶段",
  writing: "写作中",
  reviewing: "审核中",
  completed: "已完成",
  paused: "已暂停",
};

const STATUS_COLORS: Record<NovelStatusType, string> = {
  draft: "bg-gray-500",
  outlining: "bg-blue-500",
  writing: "bg-green-500",
  reviewing: "bg-yellow-500",
  completed: "bg-purple-500",
  paused: "bg-red-500",
};

export function NovelManager({ storyId }: NovelManagerProps) {
  const [activeTab, setActiveTab] = useState<"outline" | "world" | "status">("outline");

  const [outline, setOutline] = useState<NovelOutlineResponse | null>(null);
  const [worldBible, setWorldBible] = useState<WorldBibleResponse | null>(null);
  const [novelStatus, setNovelStatus] = useState<NovelStatusResponse | null>(null);

  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Outline edit state
  const [outlineEditMode, setOutlineEditMode] = useState(false);
  const [editingOutline, setEditingOutline] = useState<NovelOutlineResponse | null>(null);

  // World bible edit state
  const [worldEditMode, setWorldEditMode] = useState(false);
  const [editingWorld, setEditingWorld] = useState<WorldBibleResponse | null>(null);

  useEffect(() => {
    if (!storyId) return;
    loadAll();
  }, [storyId]);

  // Auto-dismiss success/error after 3s
  useEffect(() => {
    if (success || error) {
      const timer = setTimeout(() => {
        setSuccess(null);
        setError(null);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [success, error]);

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const [outlineData, worldData, statusData] = await Promise.all([
        fetchOutline(storyId).catch(() => null),
        fetchWorldBible(storyId).catch(() => null),
        fetchNovelStatus(storyId).catch(() => null),
      ]);
      setOutline(outlineData);
      setWorldBible(worldData);
      setNovelStatus(statusData);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerateOutline() {
    setGenerating(true);
    setError(null);
    try {
      const result = await generateOutline(storyId, outline?.total_chapters || 30);
      setOutline(result);
      // Reload status as it may have been updated
      const statusData = await fetchNovelStatus(storyId);
      setNovelStatus(statusData);
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  }

  function startEditOutline() {
    if (!outline) return;
    setEditingOutline(JSON.parse(JSON.stringify(outline)));
    setOutlineEditMode(true);
  }

  function cancelEditOutline() {
    setOutlineEditMode(false);
    setEditingOutline(null);
  }

  async function saveOutlineEdit() {
    if (!editingOutline) return;
    console.log('[NovelManager] saveOutlineEdit start, storyId:', storyId, 'chapters:', editingOutline.chapters.length);
    setSaving(true);
    setError(null);
    try {
      const payload = {
        chapters: editingOutline.chapters.map(ch => ({
          chapter_number: ch.chapter_number,
          chapter_title: ch.chapter_title,
          summary: ch.summary,
          key_characters: ch.key_characters,
          primary_conflict: ch.primary_conflict,
          cadence: ch.cadence,
          word_count_estimate: ch.word_count_estimate,
          arc_phase: ch.arc_phase,
        })),
        overall_arc: editingOutline.overall_arc,
        act_breaks: editingOutline.act_breaks,
        notes: editingOutline.notes,
      };
      console.log('[NovelManager] calling updateOutline, payload size:', JSON.stringify(payload).length);
      const result = await updateOutline(storyId, payload);
      console.log('[NovelManager] updateOutline success:', result.story_id);
      setOutline(result);
      setSuccess("大纲保存成功");
      setOutlineEditMode(false);
      setEditingOutline(null);
    } catch (e) {
      console.error('[NovelManager] saveOutlineEdit error:', e);
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      console.log('[NovelManager] saveOutlineEdit finally');
      setSaving(false);
    }
  }

  function startEditWorld() {
    if (!worldBible) return;
    setEditingWorld(JSON.parse(JSON.stringify(worldBible)));
    setWorldEditMode(true);
  }

  function cancelEditWorld() {
    setWorldEditMode(false);
    setEditingWorld(null);
  }

  async function saveWorldEdit() {
    if (!editingWorld) return;
    console.log('[NovelManager] saveWorldEdit start, storyId:', storyId);
    setSaving(true);
    setError(null);
    try {
      const result = await updateWorldBible(storyId, {
        world_name: editingWorld.world_name,
        overview: editingWorld.overview,
        power_system: editingWorld.power_system,
        locations: editingWorld.locations,
        factions: editingWorld.factions,
        world_facts: editingWorld.world_facts,
        timeline_events: editingWorld.timeline_events,
        cultural_notes: editingWorld.cultural_notes,
        glossary: editingWorld.glossary,
      });
      console.log('[NovelManager] updateWorldBible success:', result.world_name);
      setWorldBible(result);
      setSuccess("世界设定保存成功");
      setWorldEditMode(false);
      setEditingWorld(null);
    } catch (e) {
      console.error('[NovelManager] saveWorldEdit error:', e);
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      console.log('[NovelManager] saveWorldEdit finally');
      setSaving(false);
    }
  }

  async function handleStatusChange(newStatus: NovelStatusType) {
    if (!novelStatus) return;
    try {
      const result = await updateNovelStatus(storyId, { status: newStatus });
      setNovelStatus(result);
      setSuccess("状态已更新");
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新状态失败");
    }
  }

  function renderOutline() {
    if (!outline) {
      return (
        <div className="text-center py-8">
          <p className="text-gray-500 mb-4">还没有大纲，点击下方按钮生成。</p>
          <button
            className="btn"
            onClick={handleGenerateOutline}
            disabled={generating}
          >
            {generating ? "生成中..." : "生成大纲"}
          </button>
        </div>
      );
    }

    // ── Edit mode ──
    if (outlineEditMode && editingOutline) {
      return (
        <div>
          {/* Overall arc */}
          <div className="mb-4">
            <label className="font-semibold text-sm text-gray-700 mb-1 block">故事主线</label>
            <textarea
              className="w-full border rounded p-2 text-sm"
              rows={3}
              value={editingOutline.overall_arc}
              onChange={e => setEditingOutline(prev => prev ? {
                ...prev,
                overall_arc: e.target.value,
              } : null)}
            />
          </div>

          {/* Chapters */}
          <div className="mb-4">
            <label className="font-semibold text-sm text-gray-700 mb-2 block">章节列表</label>
            <div className="max-h-96 overflow-y-auto">
              {editingOutline.chapters.map((ch, idx) => (
                <div key={ch.chapter_number} className="mb-3 p-3 border rounded">
                  <div className="flex gap-2 mb-2">
                    <span className="text-sm font-medium text-gray-500 w-8">#{ch.chapter_number}</span>
                    <input
                      className="flex-1 border rounded px-2 py-1 text-sm font-medium"
                      value={ch.chapter_title}
                      onChange={e => {
                        setEditingOutline(prev => {
                          if (!prev) return prev;
                          const chapters = [...prev.chapters];
                          chapters[idx] = { ...chapters[idx], chapter_title: e.target.value };
                          return { ...prev, chapters };
                        });
                      }}
                    />
                    <span className={`px-2 py-0.5 rounded text-xs self-center ${
                      ch.cadence === "urgent" ? "bg-red-100 text-red-700" :
                      ch.cadence === "breathing" ? "bg-green-100 text-green-700" :
                      "bg-gray-100 text-gray-700"
                    }`}>
                      {ch.cadence === "urgent" ? "紧张" : ch.cadence === "breathing" ? "舒缓" : "平稳"}
                    </span>
                  </div>
                  <textarea
                    className="w-full border rounded px-2 py-1 text-sm"
                    rows={2}
                    value={ch.summary}
                    onChange={e => {
                      setEditingOutline(prev => {
                        if (!prev) return prev;
                        const chapters = [...prev.chapters];
                        chapters[idx] = { ...chapters[idx], summary: e.target.value };
                        return { ...prev, chapters };
                      });
                    }}
                  />
                  <input
                    className="w-full border rounded px-2 py-1 text-xs mt-2"
                    placeholder="主要冲突"
                    value={ch.primary_conflict}
                    onChange={e => {
                      setEditingOutline(prev => {
                        if (!prev) return prev;
                        const chapters = [...prev.chapters];
                        chapters[idx] = { ...chapters[idx], primary_conflict: e.target.value };
                        return { ...prev, chapters };
                      });
                    }}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            <button
              className="px-4 py-1.5 bg-blue-500 text-white rounded text-sm hover:bg-blue-600 disabled:opacity-50"
              onClick={saveOutlineEdit}
              disabled={saving}
            >
              {saving ? "保存中..." : "保存修改"}
            </button>
            <button
              className="px-4 py-1.5 bg-gray-200 text-gray-700 rounded text-sm hover:bg-gray-300"
              onClick={cancelEditOutline}
            >
              取消
            </button>
          </div>
        </div>
      );
    }

    // ── View mode ──
    return (
      <div>
        {/* Status bar */}
        <div className="mb-4 p-3 bg-gray-50 rounded">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-sm text-gray-500">总章节</span>
              <p className="text-xl font-bold">{outline.total_chapters}</p>
            </div>
            <div>
              <span className="text-sm text-gray-500">已保存</span>
              <p className="text-xl font-bold">{outline.saved ? "✅ 是" : "❌ 否"}</p>
            </div>
            <div>
              <span className="text-sm text-gray-500">更新时间</span>
              <p className="text-sm">{outline.updated_at ? new Date(outline.updated_at).toLocaleString("zh-CN") : "未知"}</p>
            </div>
          </div>
        </div>

        {/* Overall arc */}
        {outline.overall_arc && (
          <div className="mb-4 p-3 bg-blue-50 rounded">
            <h3 className="font-semibold text-blue-800 mb-1">故事主线</h3>
            <p className="text-sm text-blue-700">{outline.overall_arc}</p>
          </div>
        )}

        {/* Act breaks */}
        {outline.act_breaks.length > 0 && (
          <div className="mb-4">
            <h3 className="font-semibold mb-2">三幕结构</h3>
            <div className="flex gap-2">
              {outline.act_breaks.map((act) => (
                <div key={act.act} className="flex-1 p-2 bg-gray-100 rounded text-center">
                  <p className="text-xs text-gray-500">第{act.act}幕</p>
                  <p className="text-sm font-medium">第{act.start}-{act.end}章</p>
                  <p className="text-xs text-gray-600">{act.theme}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Chapter list */}
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="text-left py-2 px-1">#</th>
                <th className="text-left py-2 px-1">标题</th>
                <th className="text-left py-2 px-1 hidden md:table-cell">阶段</th>
                <th className="text-left py-2 px-1 hidden lg:table-cell">冲突</th>
                <th className="text-left py-2 px-1">节奏</th>
              </tr>
            </thead>
            <tbody>
              {outline.chapters.map((ch) => (
                <tr key={ch.chapter_number} className="border-b hover:bg-gray-50">
                  <td className="py-2 px-1 text-gray-500">{ch.chapter_number}</td>
                  <td className="py-2 px-1 font-medium">{ch.chapter_title}</td>
                  <td className="py-2 px-1 text-xs hidden md:table-cell">{ch.arc_phase}</td>
                  <td className="py-2 px-1 text-xs hidden lg:table-cell">{ch.primary_conflict}</td>
                  <td className="py-2 px-1">
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      ch.cadence === "urgent" ? "bg-red-100 text-red-700" :
                      ch.cadence === "breathing" ? "bg-green-100 text-green-700" :
                      "bg-gray-100 text-gray-700"
                    }`}>
                      {ch.cadence === "urgent" ? "紧张" : ch.cadence === "breathing" ? "舒缓" : "平稳"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Action buttons */}
        <div className="mt-4 flex gap-2">
          <button
            className="px-4 py-1.5 bg-blue-500 text-white rounded text-sm hover:bg-blue-600"
            onClick={startEditOutline}
          >
            编辑大纲
          </button>
          <button
            className="px-4 py-1.5 bg-gray-100 text-gray-700 rounded text-sm hover:bg-gray-200"
            onClick={handleGenerateOutline}
            disabled={generating}
          >
            {generating ? "重新生成中..." : "重新生成"}
          </button>
        </div>
      </div>
    );
  }

  function renderWorldBible() {
    if (!worldBible) {
      return <p className="text-gray-500">加载中...</p>;
    }

    // ── Edit mode ──
    if (worldEditMode && editingWorld) {
      return (
        <div>
          {/* World name */}
          <div className="mb-4">
            <label className="font-semibold text-sm text-gray-700 mb-1 block">世界名称</label>
            <input
              className="w-full border rounded px-2 py-1 text-sm"
              value={editingWorld.world_name}
              onChange={e => setEditingWorld(prev => prev ? {
                ...prev,
                world_name: e.target.value,
              } : null)}
            />
          </div>

          {/* Overview */}
          <div className="mb-4">
            <label className="font-semibold text-sm text-gray-700 mb-1 block">世界概述</label>
            <textarea
              className="w-full border rounded p-2 text-sm"
              rows={3}
              value={editingWorld.overview}
              onChange={e => setEditingWorld(prev => prev ? {
                ...prev,
                overview: e.target.value,
              } : null)}
            />
          </div>

          {/* Power System */}
          <div className="mb-4">
            <label className="font-semibold text-sm text-gray-700 mb-2 block">力量体系</label>
            <div className="border rounded p-3 space-y-2">
              <input
                className="w-full border rounded px-2 py-1 text-sm"
                placeholder="体系名称"
                value={editingWorld.power_system.name}
                onChange={e => setEditingWorld(prev => prev ? {
                  ...prev,
                  power_system: { ...prev.power_system, name: e.target.value },
                } : null)}
              />
              <textarea
                className="w-full border rounded px-2 py-1 text-sm"
                placeholder="体系描述"
                rows={2}
                value={editingWorld.power_system.description}
                onChange={e => setEditingWorld(prev => prev ? {
                  ...prev,
                  power_system: { ...prev.power_system, description: e.target.value },
                } : null)}
              />
              <div>
                <label className="text-xs text-gray-500 mb-1 block">境界等级（逗号分隔）</label>
                <input
                  className="w-full border rounded px-2 py-1 text-sm"
                  value={editingWorld.power_system.levels.join(", ")}
                  onChange={e => setEditingWorld(prev => prev ? {
                    ...prev,
                    power_system: { ...prev.power_system, levels: e.target.value.split(",").map(s => s.trim()).filter(Boolean) },
                  } : null)}
                />
              </div>
            </div>
          </div>

          {/* Locations */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <label className="font-semibold text-sm text-gray-700">地点</label>
              <button
                className="text-xs text-blue-500 hover:underline"
                onClick={() => setEditingWorld(prev => prev ? {
                  ...prev,
                  locations: [...prev.locations, { name: "", description: "", type: "", importance: 1, connections: [] }],
                } : null)}
              >
                + 添加
              </button>
            </div>
            <div className="space-y-2">
              {editingWorld.locations.map((loc, idx) => (
                <div key={idx} className="border rounded p-3">
                  <div className="flex gap-2 mb-2">
                    <input
                      className="flex-1 border rounded px-2 py-1 text-sm font-medium"
                      placeholder="名称"
                      value={loc.name}
                      onChange={e => setEditingWorld(prev => {
                        if (!prev) return prev;
                        const locations = [...prev.locations];
                        locations[idx] = { ...locations[idx], name: e.target.value };
                        return { ...prev, locations };
                      })}
                    />
                    <input
                      className="border rounded px-2 py-1 text-sm w-24"
                      placeholder="类型"
                      value={loc.type}
                      onChange={e => setEditingWorld(prev => {
                        if (!prev) return prev;
                        const locations = [...prev.locations];
                        locations[idx] = { ...locations[idx], type: e.target.value };
                        return { ...prev, locations };
                      })}
                    />
                    <button
                      className="text-red-400 text-sm hover:text-red-600"
                      onClick={() => setEditingWorld(prev => {
                        if (!prev) return prev;
                        const locations = [...prev.locations];
                        locations.splice(idx, 1);
                        return { ...prev, locations };
                      })}
                    >
                      ✕
                    </button>
                  </div>
                  <input
                    className="w-full border rounded px-2 py-1 text-xs"
                    placeholder="描述"
                    value={loc.description}
                    onChange={e => setEditingWorld(prev => {
                      if (!prev) return prev;
                      const locations = [...prev.locations];
                      locations[idx] = { ...locations[idx], description: e.target.value };
                      return { ...prev, locations };
                    })}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Factions */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <label className="font-semibold text-sm text-gray-700">势力</label>
              <button
                className="text-xs text-blue-500 hover:underline"
                onClick={() => setEditingWorld(prev => prev ? {
                  ...prev,
                  factions: [...prev.factions, { name: "", description: "", type: "", goals: [], allies: [], enemies: [], notable_members: [] }],
                } : null)}
              >
                + 添加
              </button>
            </div>
            <div className="space-y-2">
              {editingWorld.factions.map((faction, idx) => (
                <div key={idx} className="border rounded p-3">
                  <div className="flex gap-2 mb-2">
                    <input
                      className="flex-1 border rounded px-2 py-1 text-sm font-medium"
                      placeholder="势力名称"
                      value={faction.name}
                      onChange={e => setEditingWorld(prev => {
                        if (!prev) return prev;
                        const factions = [...prev.factions];
                        factions[idx] = { ...factions[idx], name: e.target.value };
                        return { ...prev, factions };
                      })}
                    />
                    <input
                      className="border rounded px-2 py-1 text-sm w-24"
                      placeholder="类型"
                      value={faction.type}
                      onChange={e => setEditingWorld(prev => {
                        if (!prev) return prev;
                        const factions = [...prev.factions];
                        factions[idx] = { ...factions[idx], type: e.target.value };
                        return { ...prev, factions };
                      })}
                    />
                    <button
                      className="text-red-400 text-sm hover:text-red-600"
                      onClick={() => setEditingWorld(prev => {
                        if (!prev) return prev;
                        const factions = [...prev.factions];
                        factions.splice(idx, 1);
                        return { ...prev, factions };
                      })}
                    >
                      ✕
                    </button>
                  </div>
                  <input
                    className="w-full border rounded px-2 py-1 text-xs"
                    placeholder="描述"
                    value={faction.description}
                    onChange={e => setEditingWorld(prev => {
                      if (!prev) return prev;
                      const factions = [...prev.factions];
                      factions[idx] = { ...factions[idx], description: e.target.value };
                      return { ...prev, factions };
                    })}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* World Facts */}
          <div className="mb-4">
            <label className="font-semibold text-sm text-gray-700 mb-1 block">世界规则（每行一条）</label>
            <textarea
              className="w-full border rounded p-2 text-sm"
              rows={3}
              value={editingWorld.world_facts.join("\n")}
              onChange={e => setEditingWorld(prev => prev ? {
                ...prev,
                world_facts: e.target.value.split("\n").map(s => s.trim()).filter(Boolean),
              } : null)}
            />
          </div>

          {/* Cultural Notes */}
          <div className="mb-4">
            <label className="font-semibold text-sm text-gray-700 mb-1 block">文化备注（每行一条）</label>
            <textarea
              className="w-full border rounded p-2 text-sm"
              rows={2}
              value={editingWorld.cultural_notes.join("\n")}
              onChange={e => setEditingWorld(prev => prev ? {
                ...prev,
                cultural_notes: e.target.value.split("\n").map(s => s.trim()).filter(Boolean),
              } : null)}
            />
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            <button
              className="px-4 py-1.5 bg-blue-500 text-white rounded text-sm hover:bg-blue-600 disabled:opacity-50"
              onClick={saveWorldEdit}
              disabled={saving}
            >
              {saving ? "保存中..." : "保存修改"}
            </button>
            <button
              className="px-4 py-1.5 bg-gray-200 text-gray-700 rounded text-sm hover:bg-gray-300"
              onClick={cancelEditWorld}
            >
              取消
            </button>
          </div>
        </div>
      );
    }

    // ── View mode ──
    return (
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold text-lg">{worldBible.world_name}</h3>
          <button
            className="px-3 py-1 bg-blue-500 text-white rounded text-sm hover:bg-blue-600"
            onClick={startEditWorld}
          >
            编辑
          </button>
        </div>

        {/* Overview */}
        {worldBible.overview && (
          <div className="mb-4 p-3 bg-blue-50 rounded">
            <h4 className="font-medium text-blue-800 mb-1">世界概述</h4>
            <p className="text-sm text-blue-700">{worldBible.overview}</p>
          </div>
        )}

        {/* Power System */}
        {worldBible.power_system.name && (
          <div className="mb-4">
            <h4 className="font-medium mb-1">力量体系：{worldBible.power_system.name}</h4>
            {worldBible.power_system.description && (
              <p className="text-sm text-gray-600 mb-2">{worldBible.power_system.description}</p>
            )}
            {worldBible.power_system.levels.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {worldBible.power_system.levels.map((level, i) => (
                  <span key={i} className="px-2 py-1 bg-purple-100 text-purple-700 rounded text-xs">
                    {level}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Locations */}
        {worldBible.locations.length > 0 && (
          <div className="mb-4">
            <h4 className="font-medium mb-1">地点</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {worldBible.locations.map((loc) => (
                <div key={loc.name} className="p-2 bg-gray-50 rounded">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{loc.name}</span>
                    <span className="text-xs text-gray-500">{loc.type}</span>
                  </div>
                  {loc.description && (
                    <p className="text-xs text-gray-600 mt-1">{loc.description}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Factions */}
        {worldBible.factions.length > 0 && (
          <div className="mb-4">
            <h4 className="font-medium mb-1">势力</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {worldBible.factions.map((faction) => (
                <div key={faction.name} className="p-2 bg-gray-50 rounded">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{faction.name}</span>
                    <span className="text-xs text-gray-500">{faction.type}</span>
                  </div>
                  {faction.description && (
                    <p className="text-xs text-gray-600 mt-1">{faction.description}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* World Facts */}
        {worldBible.world_facts.length > 0 && (
          <div className="mb-4">
            <h4 className="font-medium mb-1">世界规则</h4>
            <ul className="list-disc list-inside text-sm text-gray-700">
              {worldBible.world_facts.map((fact, i) => (
                <li key={i}>{fact}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Glossary */}
        {Object.keys(worldBible.glossary).length > 0 && (
          <div className="mb-4">
            <h4 className="font-medium mb-1">术语表</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {Object.entries(worldBible.glossary).map(([term, def]) => (
                <div key={term} className="p-2 bg-gray-50 rounded">
                  <span className="font-medium text-sm">{term}</span>
                  <p className="text-xs text-gray-600">{def}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  function renderStatus() {
    if (!novelStatus) {
      return <p className="text-gray-500">加载中...</p>;
    }

    return (
      <div>
        {/* Status badge */}
        <div className="mb-4 p-3 bg-gray-50 rounded">
          <div className="flex items-center gap-2 mb-3">
            <span className={`px-2 py-1 rounded text-white text-sm ${STATUS_COLORS[novelStatus.status]}`}>
              {STATUS_LABELS[novelStatus.status]}
            </span>
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div>
              <span className="text-xs text-gray-500">计划章节</span>
              <p className="text-xl font-bold">{novelStatus.total_chapters_planned}</p>
            </div>
            <div>
              <span className="text-xs text-gray-500">已写章节</span>
              <p className="text-xl font-bold">{novelStatus.total_chapters_written}</p>
            </div>
            <div>
              <span className="text-xs text-gray-500">总字数</span>
              <p className="text-xl font-bold">{novelStatus.total_word_count.toLocaleString()}</p>
            </div>
            <div>
              <span className="text-xs text-gray-500">最新章节</span>
              <p className="text-xl font-bold">第{novelStatus.last_written_chapter}章</p>
            </div>
          </div>
        </div>

        {/* Progress bar */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm text-gray-500">完成进度</span>
            <span className="text-sm font-medium">
              {novelStatus.total_chapters_planned > 0
                ? Math.round((novelStatus.total_chapters_written / novelStatus.total_chapters_planned) * 100)
                : 0}%
            </span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-green-500 h-2 rounded-full transition-all"
              style={{
                width: `${novelStatus.total_chapters_planned > 0
                  ? Math.min(100, (novelStatus.total_chapters_written / novelStatus.total_chapters_planned) * 100)
                  : 0}%`,
              }}
            />
          </div>
        </div>

        {/* Status changer */}
        <div>
          <h4 className="font-medium mb-2">更改状态</h4>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(STATUS_LABELS) as NovelStatusType[]).map((s) => (
              <button
                key={s}
                className={`px-3 py-1 rounded text-sm ${
                  novelStatus.status === s
                    ? `${STATUS_COLORS[s]} text-white`
                    : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                }`}
                onClick={() => handleStatusChange(s)}
              >
                {STATUS_LABELS[s]}
              </button>
            ))}
          </div>
        </div>

        {/* Timestamps */}
        <div className="mt-4 text-xs text-gray-500">
          <p>创建时间：{novelStatus.created_at ? new Date(novelStatus.created_at).toLocaleString("zh-CN") : "未知"}</p>
          <p>更新时间：{novelStatus.updated_at ? new Date(novelStatus.updated_at).toLocaleString("zh-CN") : "未知"}</p>
        </div>
      </div>
    );
  }

  if (!storyId) {
    return <p className="text-gray-500">请先选择或创建一个故事。</p>;
  }

  return (
    <div className="novel-manager">
      <header className="panel__header flex items-center justify-between">
        <span>小说管理</span>
        <span className="text-xs text-gray-500">{storyId}</span>
      </header>

      {/* Toast notifications */}
      {(success || error) && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-2 rounded-lg text-sm shadow-lg transition-all ${
          success ? "bg-green-500 text-white" : "bg-red-500 text-white"
        }`}>
          {success || error}
        </div>
      )}

      <div className="panel__body">
        {/* Tabs */}
        <div className="flex gap-2 mb-4">
          <button
            className={`px-3 py-1 rounded text-sm ${activeTab === "outline" ? "bg-blue-500 text-white" : "bg-gray-100"}`}
            onClick={() => setActiveTab("outline")}
          >
            大纲
          </button>
          <button
            className={`px-3 py-1 rounded text-sm ${activeTab === "world" ? "bg-blue-500 text-white" : "bg-gray-100"}`}
            onClick={() => setActiveTab("world")}
          >
            世界设定
          </button>
          <button
            className={`px-3 py-1 rounded text-sm ${activeTab === "status" ? "bg-blue-500 text-white" : "bg-gray-100"}`}
            onClick={() => setActiveTab("status")}
          >
            小说状态
          </button>
        </div>

        {/* Content */}
        {loading ? (
          <p className="text-gray-500">加载中...</p>
        ) : error ? (
          <p className="text-red-500">错误：{error}</p>
        ) : (
          <>
            {activeTab === "outline" && renderOutline()}
            {activeTab === "world" && renderWorldBible()}
            {activeTab === "status" && renderStatus()}
          </>
        )}
      </div>
    </div>
  );
}
