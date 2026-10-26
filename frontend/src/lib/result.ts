import { ApiError, ApiUnavailable } from "@/lib/api/client";

/**
 * One page, one failure. A server component that awaited three calls and threw on the first would
 * render an error page with no context; this keeps the shape of the failure so the page can show what
 * failed and why, and keep the parts that worked.
 */
export type Result<T> = { ok: true; value: T } | { ok: false; message: string; requestId: string | null };

export async function settle<T>(promise: Promise<T>): Promise<Result<T>> {
  try {
    return { ok: true, value: await promise };
  } catch (error) {
    if (error instanceof ApiError) {
      return { ok: false, message: `${error.code}: ${error.message}`, requestId: error.requestId };
    }
    if (error instanceof ApiUnavailable) {
      return { ok: false, message: error.message, requestId: null };
    }
    return { ok: false, message: error instanceof Error ? error.message : "unknown error", requestId: null };
  }
}
