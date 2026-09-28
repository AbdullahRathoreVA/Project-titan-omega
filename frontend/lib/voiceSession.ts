// Client for the voice session store, so the Voice Agents screen shows real
// conversations.
//
// Every call here fails silently. This is telemetry: a guest gets 403 on the
// whole /api/voice prefix (transcripts are founder-only) and an offline
// visitor gets nothing, and neither may break the conversation being
// recorded. If recording fails the chat carries on and the screen just shows
// one fewer session.
//
// The server enforces the state machine. This sends the transitions a
// conversation actually makes; an illegal one comes back 409 and is ignored,
// not retried.

import { apiBase, authHeaders } from "./api";

// A subscriber's conversations are recorded under their own account
// (/api/me/voice), the founder's under /api/voice.
async function post<T>(path: string, body?: unknown): Promise<T | null> {
  try {
    const r = await fetch(`${apiBase()}/voice${path}`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body ?? {}),
    });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export type VoiceState =
  | "idle" | "listening" | "thinking" | "speaking"
  | "interrupted" | "escalated" | "ended";

/** One conversation. Reused across turns so the screen shows a session, not a
 *  new node per sentence. */
export class VoiceSession {
  private id: string | null = null;
  private opening: Promise<void> | null = null;

  constructor(
    private channel: string = "web",
    private agent: string = "titan-assistant",
  ) {}

  /**
   * Opened lazily on the first real turn, so an idle chat panel nobody typed
   * into doesn't show up as a session.
   */
  private async ensure(language: string): Promise<void> {
    if (this.id) return;
    if (!this.opening) {
      this.opening = (async () => {
        const s = await post<{ id: string }>("/sessions", {
          channel: this.channel,
          agent: this.agent,
          language,
        });
        this.id = s?.id ?? null;
      })();
    }
    await this.opening;
  }

  /**
   * The first turn opens the session; wait for the id before sending
   * `thinking`, or the first answer's latency would never be measured.
   */
  private async opened(): Promise<boolean> {
    if (this.opening) await this.opening;
    return this.id !== null;
  }

  async state(state: VoiceState, reason = ""): Promise<void> {
    if (!(await this.opened())) return;
    await post(`/sessions/${this.id}/state`, { state, reason });
  }

  async turn(
    role: "user" | "agent",
    text: string,
    language: string,
    confidence?: number,
  ): Promise<void> {
    await this.ensure(language);
    if (!this.id) return;
    await post(`/sessions/${this.id}/turn`, {
      role,
      text,
      language,
      // Only pass a confidence the recogniser actually reported; a
      // self-assigned score isn't evidence.
      ...(typeof confidence === "number" ? { confidence } : {}),
    });
  }

  async tool(name: string, argsSummary = ""): Promise<void> {
    if (!(await this.opened())) return;
    await post(`/sessions/${this.id}/tool`, { name, args_summary: argsSummary });
  }

  async end(): Promise<void> {
    if (!(await this.opened())) return;
    await post(`/sessions/${this.id}/end`);
    this.id = null;
    this.opening = null;
  }

  /**
   * For a page that's going away: a reload or closed tab never unmounts the
   * panel, so without this the session would stay on the live screen
   * forever. `keepalive` lets the request outlive the page, and unlike
   * sendBeacon it can carry the Authorization header.
   */
  endOnExit(): void {
    if (!this.id) return;
    try {
      void fetch(`${apiBase()}/voice/sessions/${this.id}/end`, {
        method: "POST",
        keepalive: true,
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: "{}",
      });
    } catch {
      // Best effort, like every call here.
    }
    this.id = null;
    this.opening = null;
  }

  get sessionId(): string | null {
    return this.id;
  }
}
