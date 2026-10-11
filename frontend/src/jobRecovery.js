import { api } from "./api.js";

/** After a start request fails, follow the job that occupies the engine, if any. */
export async function adoptActiveJob(error, receiveJob) {
  if (error.activeJob) {
    receiveJob(error.activeJob);
    return;
  }
  try {
    const data = await api("/bootstrap");
    if (data.active_job) receiveJob(data.active_job);
  } catch {
    /* Keep the original request error if recovery is unavailable. */
  }
}
