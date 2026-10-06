// Messages to the Python side. Replies come back as promises.
const handler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.audius;

export async function call(cmd, args = {}) {
  if (!handler) {
    console.warn("no native bridge for", cmd);
    return { error: "no bridge" };
  }
  try {
    const reply = await handler.postMessage({ cmd, ...args });
    if (reply && reply.error) console.warn(cmd, reply.error);
    return reply;
  } catch (e) {
    console.error(cmd, e);
    return { error: String(e) };
  }
}

export const send = (cmd, args) => { call(cmd, args); };

let gid = 0;
export const newGesture = () => `g${Date.now().toString(36)}-${(gid++).toString(36)}`;

// Coalesce rapid updates (drags) to one message per animation frame, in order.
export function frameSender(fn) {
  let pending = null;
  let scheduled = false;
  const flush = () => {
    scheduled = false;
    if (pending) {
      const a = pending;
      pending = null;
      fn(a);
    }
  };
  const push = (args) => {
    pending = args;
    if (!scheduled) {
      scheduled = true;
      requestAnimationFrame(flush);
    }
  };
  push.flush = flush;
  return push;
}
