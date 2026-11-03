// Limit tools on unmentioned turns in listen-in rooms.
//
// Discord threads don't inherit a channel's tool policy, and a per-room policy
// would also restrict mentions, so the limit follows the turn instead. Each
// inbound message is classified at dispatch, in order per session, and a turn
// takes its classification when it starts.
const MAX_TRACKED = 1000;
const ALLOWED_TOOLS = new Set(["message", "web_search", "web_fetch", "x_search"]);
const BLOCK_REASON = "Not available in a listen-in room. Use message to post, or stay silent.";

const queued = new Map(); // sessionKey -> oldest-first roomEvent flags awaiting a turn
const running = new Map(); // sessionKey -> roomEvent flag of the turn in progress

function remember(map, key, value) {
  map.delete(key);
  map.set(key, value);
  if (map.size > MAX_TRACKED) map.delete(map.keys().next().value);
}

export default {
  id: "agentbarn-listen-in",
  name: "Agent Barn listen-in guard",
  description: "Limit tools on unmentioned turns in listen-in rooms",
  register(api) {
    api.on("reply_dispatch", (event) => {
      const sessionKey = event.sessionKey;
      if (!sessionKey) return undefined;
      const flags = queued.get(sessionKey) || [];
      flags.push(event.ctx?.InboundEventKind === "room_event");
      remember(queued, sessionKey, flags);
      return undefined;
    });

    api.on("before_agent_run", (_event, ctx) => {
      if (ctx.trigger !== "user" || !ctx.sessionKey) return undefined;
      remember(running, ctx.sessionKey, queued.get(ctx.sessionKey)?.shift() === true);
      return undefined;
    });

    api.on("before_tool_call", (event, ctx) => {
      if (running.get(ctx.sessionKey) !== true || ALLOWED_TOOLS.has(event.toolName)) return undefined;
      return { block: true, blockReason: BLOCK_REASON };
    });
  },
};
