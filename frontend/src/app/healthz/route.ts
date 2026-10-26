/**
 * The container's healthcheck. Deliberately does not touch the API: a dashboard process that is up
 * should not be restarted because the database had a bad second, and the page itself shows the API's
 * state when you open it.
 */
export function GET(): Response {
  return Response.json({ status: "ok", service: "hermes-dashboard" });
}
