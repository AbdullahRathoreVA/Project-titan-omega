// Titan Telegram Relay — free Cloudflare Worker.
//
// Why this exists: Hugging Face's network blocks outbound connections to
// api.telegram.org, so the Space can neither poll nor reply directly. This
// Worker sits in between: Telegram webhooks it, it asks Titan for the reply
// (inbound calls to the Space work fine), and it sends the reply to Telegram.
//
// Setup: see TELEGRAM_SETUP.md in the repo root. Worker variables needed:
//   BOT_TOKEN    — from @BotFather
//   TITAN_URL    — https://careermind2026-project-titan-omega.hf.space
//   TITAN_SECRET — same value as the Space's TITAN_WEBHOOK_SECRET
//   TG_SECRET    — any random string; also passed as secret_token in setWebhook

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Titan Telegram relay: online");
    }
    if (env.TG_SECRET && request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TG_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    const update = await request.json().catch(() => null);
    const msg = update?.message || update?.edited_message;
    const chatId = msg?.chat?.id;
    const text = msg?.text;
    if (!chatId || !text) return new Response("ok");

    let reply = "Titan core unreachable — try again in a minute.";
    try {
      const r = await fetch(`${env.TITAN_URL}/api/telegram/handle`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Webhook-Secret": env.TITAN_SECRET,
        },
        body: JSON.stringify({
          text,
          chat_id: String(chatId),
          sender: msg.from?.first_name || "",
        }),
      });
      if (r.ok) reply = (await r.json()).reply || reply;
    } catch {
      // keep the fallback reply
    }

    await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: reply.slice(0, 3900) }),
    }).catch(() => {});

    return new Response("ok");
  },
};
