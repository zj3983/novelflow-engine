import { apiBase, fetchJson } from "./api-client";
import type { SkillPackSummary, UninstallSkillPackResponse } from "./api";

export async function listSkillPacks(): Promise<SkillPackSummary[]> {
  return await fetchJson(`${apiBase()}/skill-packs`, { method: "GET" });
}

export async function fetchSkillPack(skillId: string): Promise<SkillPackSummary> {
  return await fetchJson(`${apiBase()}/skill-packs/${encodeURIComponent(skillId)}`, { method: "GET" });
}

export async function importSkillPackFromPath(sourcePath: string): Promise<SkillPackSummary> {
  return await fetchJson(`${apiBase()}/skill-packs/import`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath }),
  });
}

export async function uploadSkillPackZip(file: File): Promise<SkillPackSummary> {
  return await fetchJson(`${apiBase()}/skill-packs/upload`, {
    method: "POST",
    headers: { "content-type": "application/zip" },
    body: await file.arrayBuffer(),
  });
}

export async function uninstallSkillPack(skillId: string): Promise<UninstallSkillPackResponse> {
  return await fetchJson(`${apiBase()}/skill-packs/${encodeURIComponent(skillId)}`, { method: "DELETE" });
}

export async function uninstallSkillModule(
  skillId: string,
  moduleId: string,
): Promise<UninstallSkillPackResponse> {
  return await fetchJson(
    `${apiBase()}/skill-packs/${encodeURIComponent(skillId)}/modules/${encodeURIComponent(moduleId)}`,
    { method: "DELETE" },
  );
}
