/** Minimal Cloudflare Worker entry point for the static reference surface. */
import handler from "vinext/server/app-router-entry";

type WorkerEnv = NonNullable<Parameters<typeof handler.fetch>[1]>;
type WorkerContext = NonNullable<Parameters<typeof handler.fetch>[2]>;

const worker = {
  async fetch(
    request: Request,
    env: WorkerEnv,
    ctx: WorkerContext,
  ): Promise<Response> {
    return handler.fetch(request, env, ctx);
  },
};

export default worker;
