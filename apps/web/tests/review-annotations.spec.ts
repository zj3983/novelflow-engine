import { expect, test } from "@playwright/test";
import { buildReviewAnnotations } from "../lib/review-annotations";
import { explainReviewAnchor } from "../lib/review-annotations";

test("simile findings locate the exact same six markers as the reviewer", () => {
  const body = "😀门口。\n\n阀门如同铁墙。他仿佛石头。她像是睡了。它犹如钟摆。她宛如冰山。风就像利刃。普通的像字不标。";
  const result = buildReviewAnnotations(body, { writing_review: { blocking: [{ code: "style.simile_stacking", message: "显式比喻过密" }] } });
  expect(result.anchors.map(anchor => body.slice(anchor.start, anchor.end))).toEqual(["如同", "仿佛", "像是", "犹如", "宛如", "就像"]);
  expect(buildReviewAnnotations(body, {}).anchors).toHaveLength(0);
});

test("exact evidence may have multiple matches but missing evidence is not guessed", () => {
  const result = buildReviewAnnotations("甲握住箱子。乙握住箱子。", { review_result: { issues: [
    { code: "prose.repeat", message: "动作重复", evidence: "握住箱子" },
    { code: "canon.unknown", message: "伤势冲突", evidence: "不存在的句子" },
  ] } });
  expect(result.anchors).toHaveLength(2);
  expect(result.unlocated).toContain("伤势冲突");
});

test("whole-chapter length has no invented offending sentence", () => {
  const result = buildReviewAnnotations("原文保持不动。", { writing_review: { blocking: [
    { code: "chapter.length_too_long", message: "正文约6597字，超过5700字。" },
  ] } });
  expect(result.anchors).toHaveLength(0);
  expect(result.global).toEqual(["正文约6597字，超过5700字。"]);
});

test("legacy simplified reports still locate similes and disclose unknown locations", () => {
  const result = buildReviewAnnotations("阀门如同铁墙。", { simplified_review: { issues: [
    { message: "正文使用了11处显式比喻，密度过高。" }, { message: "人物动机不足。" },
  ] } });
  expect(result.anchors).toHaveLength(1);
  expect(result.unlocated).toEqual(["人物动机不足。"]);
});

test("overlapping evidence and deterministic marks do not duplicate text", () => {
  const body = "阀门如同铁墙。";
  const result = buildReviewAnnotations(body, { writing_review: { blocking: [
    { code: "style.simile_stacking", message: "比喻过密" },
    { code: "prose.evidence", message: "句子重复", evidence: body },
  ] } });
  expect(result.anchors).toHaveLength(1);
  expect(body.slice(result.anchors[0].start, result.anchors[0].end)).toBe(body);
  expect(result.anchors[0].messages).toEqual(["句子重复", "比喻过密"]);
});

test("canonical evidence takes priority over a legacy copy without evidence", () => {
  const result = buildReviewAnnotations("他握住箱子。", {
    writing_review: { blocking: [{ code: "canon.damage", message: "伤势冲突" }] },
    review_result: { issues: [{ code: "canon.damage", message: "伤势冲突", evidence: "握住箱子" }] },
  });
  expect(result.anchors).toHaveLength(1);
  expect(result.unlocated).toEqual([]);
});

test("prose review examples locate exact quoted phrases without guessing missing examples", () => {
  const body = "他说：凡有动静，未查先填表，无证不动手。";
  const result = buildReviewAnnotations(body, { simplified_review: { issues: [
    { message: "清单式短句“凡有动静，未查先填表，无证不动手”，不要写成“这里没有的示例”。" },
  ] } });
  expect(result.anchors).toHaveLength(1);
  expect(body.slice(result.anchors[0].start, result.anchors[0].end)).toBe("凡有动静，未查先填表，无证不动手");
});

test("all nested findings and every occurrence are marked beyond the three-item summary", () => {
  const body = "此刻他查看数据，记录异常。此刻她确定基准。";
  const messages = ["套话问题", "解释腔问题", "术语问题"];
  const result = buildReviewAnnotations(body, {
    simplified_review: { issues: [{ message: messages[0] }] },
    prose_style_review: {
      issues: messages,
      annotations: [
        { message: messages[0], quotes: ["此刻"] },
        { message: messages[1], quotes: ["数据", "异常"] },
        { message: messages[2], quotes: ["基准"] },
      ],
    },
    writing_review: { soft_issues: [{ message: "正文重复", evidence: "记录异常" }] },
  });
  expect(result.anchors.map(item => body.slice(item.start, item.end))).toEqual(["此刻", "数据", "记录异常", "此刻", "基准"]);
  expect(result.unlocated).toEqual([]);
  expect(result.anchors[2].messages).toEqual(expect.arrayContaining([messages[1], "正文重复"]));
});

test("complete canonical findings are used without losing later evidence for the same issue", () => {
  const body = "甲乙丙丁戊";
  const result = buildReviewAnnotations(body, { review_result: {
    issues: [{ code: "first", message: "第一项" }],
    findings: [
      { code: "first", message: "第一项", evidence: "甲" },
      { code: "second", message: "第二项", evidence: "乙" },
      { code: "third", message: "第三项", evidence: "丙" },
      { code: "fourth", message: "第四项", evidence: "丁" },
      { code: "fifth", message: "第五项", evidence: "戊" },
    ],
  } });
  expect(result.anchors).toHaveLength(5);
  expect(result.unlocated).toEqual([]);
});

test("inactive AI cuts and suggested replacements are not flagged as actual findings", () => {
  const result = buildReviewAnnotations("这就是基准。", { ai_flavor_review: {
    pass: true, issues: [], hits: { abstract_terms: ["基准"] },
    cuts: [{ target_text: "基准", reason: "参考建议" }],
  } });
  expect(result.anchors).toHaveLength(0);
});

test("each annotation retains the matching reviewer fix instruction", () => {
  const body = "此刻他核对数据。";
  const result = buildReviewAnnotations(body, { prose_style_review: {
    issues: ["AI高频套话进入正文：此刻。", "正文有机械切段或解释腔，读起来像模型在拆规则：数据。"],
    revision_plan: ["删去多余时间词。", "让动作展示结果。"],
    annotations: [
      { message: "AI高频套话进入正文：此刻。", quotes: ["此刻"] },
      { message: "正文有机械切段或解释腔，读起来像模型在拆规则：数据。", quotes: ["数据"] },
    ],
  } });
  expect(result.anchors[0].issues[0].suggestion).toBe("删去多余时间词。");
  expect(result.anchors[1].issues[0].suggestion).toBe("让动作展示结果。");
  const explanation = explainReviewAnchor(body, result.anchors[1]);
  expect(explanation.quote).toBe("数据");
  expect(explanation.issues[0].problem).toContain("说明");
  expect(explanation.issues[0].suggestion).toBe("让动作展示结果。");
});

test("technical word flags explain the rule without declaring the word wrong", () => {
  const body = "他记下基准。";
  const result = buildReviewAnnotations(body, { prose_style_review: {
    issues: ["正文带出后台硬词，不像番茄白话文：基准。"],
    annotations: [{ message: "正文带出后台硬词，不像番茄白话文：基准。", quotes: ["基准"] }],
  } });
  const explanation = explainReviewAnchor(body, result.anchors[0]);
  expect(explanation.issues[0].problem).toContain("基准");
  expect(explanation.issues[0].suggestion).toContain("保留");
});

test("contextual model reasons are displayed verbatim instead of keyword explanations", () => {
  const body = "他说，先记录异常数据，再核对压力。";
  const reason = "前一句已经完整交代了记录步骤，这里重复了同一要求，打断了门人对故障原因的追问。";
  const result = buildReviewAnnotations(body, { contextual_prose_review: { issues: [{
    code: "contextual_prose.1", source: "contextual_prose", message: `重复交代步骤：${reason}`,
    evidence: body, suggestion: "直接回应门人的追问，保留必要的检修术语。",
  }] } });
  const explanation = explainReviewAnchor(body, result.anchors[0]);
  expect(explanation.issues[0].problem).toBe(reason);
  expect(explanation.issues[0].label).toBe("重复交代步骤");
});
