"use client";

import { useEffect, useRef, useState } from "react";
import { getToken } from "./api";
import type { StreamFrame } from "./types";

// Subscribes to the core's live SSE stream. EventSource can't send headers, so
// the auth token goes in the query string (the backend accepts it there). The
// browser reconnects on drop; the 5s poll in CommandCenter is the fallback.
// `enabled` is false for a subscriber, because the stream carries the founder's
// Store.
export function useTitanStream(enabled = true): { frame: StreamFrame | null; live: boolean } {
  const [frame, setFrame] = useState<StreamFrame | null>(null);
  const [live, setLive] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const token = getToken();
    const url = token ? `/api/stream?token=${encodeURIComponent(token)}` : "/api/stream";

    let closed = false;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      if (!closed) setLive(true);
    };
    es.onmessage = (ev) => {
      try {
        setFrame(JSON.parse(ev.data) as StreamFrame);
        if (!closed) setLive(true);
      } catch {
        /* ignore malformed frame */
      }
    };
    es.onerror = () => {
      if (!closed) setLive(false);
    };

    return () => {
      closed = true;
      es.close();
      esRef.current = null;
    };
  }, [enabled]);

  return { frame, live };
}
