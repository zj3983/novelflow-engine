"use client";

import { useEffect, useState } from "react";

import {
  fetchOutline,
  fetchWorldBible,
  fetchNovelStatus,
  generateOutline,
  updateNovelStatus,
  type NovelOutlineResponse,
  type WorldBibleResponse,
  type NovelStatusResponse,
  type NovelStatusType,
} from "../../lib/api";

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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!storyId) return;
    loadAll();
  }, [storyId]);

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

  async function handleStatusChange(newStatus: NovelStatusType) {
    if (!novelStatus) return;
    try {
      const result = await updateNovelStatus(storyId, { status: newStatus });
      setNovelStatus(result);
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

        {/* Generate button */}
        <div className="mt-4">
          <button
            className="btn btn--ghost"
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

    return (
      <div>
        <h3 className="font-semibold text-lg mb-2">{worldBible.world_name}</h3>

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
