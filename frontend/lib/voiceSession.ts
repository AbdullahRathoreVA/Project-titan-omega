// Client for the voice session store, so the Voice Agents screen shows real
// conversations instead of an empty orbit.
//
// **Every call here fails silently.** This is telemetry: a guest gets 403 on
// the whole /api/voice prefix because transcripts are founder-only, and an
// offline visitor gets nothing at all. Neither may break the conversation the
// session is describing — the same rule analytics.record follows server-side.
// If recording fails the chat carries on exactly as before, and the screen
// simply has one fewer session on it.
//
// The state machine is enforced by the server, not here. This sends the
// transitions a conversation genuinely makes; an illegal one comes back 409
// and is swallowed rather than retried into a lie.

const BASE = "/api/voice";

function token(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("titan_token") || sessionStorage.getItem("titan_token") || "";
}

async function post<T>(path: string, body?: unknown): Promise<T | null> {
  try {
    const r = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token()}`,
      },
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

  /** Opened lazily on the first real turn — an idle chat panel nobody typed
   *  into should not appear on the live screen as a session. */
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

  async state(state: VoiceState, reason = ""): Promise<void> {
    if (!this.id) return;
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
      // Only pass a confidence the recogniser actually reported. Titan never
      // invents one — a self-assigned score is not evidence.
      ...(typeof confidence === "number" ? { confidence } : {}),
    });
  }

  async tool(name: string, argsSummary = ""): Promise<void> {
    if (!this.id) return;
    await post(`/sessions/${this.id}/tool`, { name, args_summary: argsSummary });
  }

  async end(): Promise<void> {
    if (!this.id) return;
    await post(`/sessions/${this.id}/end`);
    this.id = null;
    this.opening = null;
  }

  get sessionId(): string | null {
    return this.id;
  }
}
