"use client";

import { useEffect, useRef, useState } from "react";
import { getToken } from "./api";
import type { StreamFrame } from "./types";

// Subscribes to the core's live SSE stream. EventSource can't send headers, so
// the auth token rides in the query string (the core whitelists it there). The
// browser auto-reconnects on drop; the 5s poll in CommandCenter is the fallback.
export function useTitanStream(): { frame: StreamFrame | null; live: boolean } {
  const [frame, setFrame] = useState<StreamFrame | null>(null);
  const [live, setLive] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
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
  }, []);

  return { frame, live };
}
