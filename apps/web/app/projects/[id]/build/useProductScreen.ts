"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { performProductAction, ProductRequestError, type ProductCommon } from "./product-api";
import type { ProductActionHandler } from "./ProductControls";

export function useProductScreen<T extends ProductCommon>(projectId: string, load: () => Promise<T>) {
  const router = useRouter();
  const [view, setView] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editors, setEditors] = useState<Record<string, boolean>>({});
  const dirty = Object.values(editors).some(Boolean);
  const [error, setError] = useState<ProductRequestError | null>(null);
  const [message, setMessage] = useState("");
  const sequence = useRef(0);
  const actionSequence = useRef(0);
  const active = useRef(true);
  const setDirty = (value: boolean, key = "content") => {
    if (value) sequence.current += 1;
    setEditors((current) => ({ ...current, [key]: value }));
  };
  useEffect(() => { active.current = true; return () => { active.current = false; sequence.current += 1; }; }, []);
  const reload = useCallback(async (foreground = true) => {
    const request = ++sequence.current;
    if (foreground) { setLoading(true); setReady(false); }
    try {
      const next = await load();
      if (active.current && request === sequence.current) { setView(next); setError(null); setReady(true); }
    } catch (reason) {
      if (active.current && request === sequence.current) setError(reason instanceof ProductRequestError ? reason : new ProductRequestError("暂时无法读取内容，请重试。"));
    } finally { if (active.current && request === sequence.current) setLoading(false); }
  }, [load]);
  useEffect(() => { actionSequence.current += 1; setBusy(false); void reload(); return () => { sequence.current += 1; actionSequence.current += 1; }; }, [reload]);
  useEffect(() => {
    if (!view?.refresh_after_ms || busy || dirty) return;
    const timer = window.setTimeout(() => void reload(false), Math.max(500, view.refresh_after_ms));
    return () => window.clearTimeout(timer);
  }, [view, reload, busy, dirty]);
  const onAction: ProductActionHandler = async (action, values) => {
    if (!action.enabled || busy || loading || !ready) return false;
    if (action.href) { router.push(action.href); return true; }
    const actionId = ++actionSequence.current;
    sequence.current += 1;
    setBusy(true); setError(null); setMessage("");
    try {
      const result = await performProductAction(projectId, action.token, values);
      if (!active.current || actionId !== actionSequence.current) return false;
      setMessage(result.message ?? "");
      if (result.redirect) router.push(result.redirect);
      await reload(false);
      return true;
    } catch (reason) {
      if (active.current && actionId === actionSequence.current) setError(reason instanceof ProductRequestError ? reason : new ProductRequestError("这次操作未能完成，请重试。"));
      return false;
    } finally { if (active.current && actionId === actionSequence.current) setBusy(false); }
  };
  return { view, loading, unavailable: !ready, busy, dirty, setDirty, error, message, reload, onAction };
}
