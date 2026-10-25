"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { ApiError, api } from "@/lib/api/client";

/**
 * The dashboard's one write: a human review decision.
 *
 * It runs on the server, with the admin token, and never reaches the browser. A failure comes back as a
 * query parameter rather than a thrown error page, because losing the table you were reviewing is a
 * worse outcome than a red banner on it.
 */
export async function reviewTurnAction(formData: FormData): Promise<void> {
  const turnId = String(formData.get("turnId") ?? "");
  const reviewStatus = String(formData.get("reviewStatus") ?? "");
  const note = String(formData.get("note") ?? "").trim();
  if (!turnId || !reviewStatus) {
    redirect("/turns?reviewError=missing_fields");
  }
  try {
    await api.reviewTurn(turnId, { reviewStatus, ...(note ? { note } : {}) });
  } catch (error) {
    const code = error instanceof ApiError ? error.code : "unavailable";
    redirect(`/turns?reviewError=${encodeURIComponent(code)}`);
  }
  revalidatePath("/turns");
  redirect("/turns?review=ok");
}
