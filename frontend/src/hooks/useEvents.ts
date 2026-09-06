import { useEffect, useRef } from "react";
import { useAuthStore } from "../stores/auth";
import type { MailEvent } from "../api/types";

/**
 * 订阅后端 SSE 实时事件流（§18）。EventSource 断线自动重连。
 */
export function useEventStream(onEvent: (e: MailEvent) => void) {
  const token = useAuthStore((s) => s.token);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    if (!token) return;
    const es = new EventSource(`/api/v1/events/stream?token=${encodeURIComponent(token)}`);
    es.onmessage = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data) as MailEvent;
        if (data.type && data.type !== "keepalive") handlerRef.current(data);
      } catch {
        /* ignore malformed */
      }
    };
    return () => es.close();
  }, [token]);
}
