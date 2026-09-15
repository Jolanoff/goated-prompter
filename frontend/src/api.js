/** Shared JSON transport. Workflow state belongs to the caller. */
export async function api(path, body, method = "POST") {
  const response = await fetch(`/api${path}`, body === undefined ? {} : {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({ error: "The local server returned an invalid response." }));
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status}).`);
    error.status = response.status;
    error.activeJob = data.active_job;
    throw error;
  }
  return data;
}
