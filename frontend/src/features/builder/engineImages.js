// Whether the active prompt engine can read Builder reference images.

/** Empty slots used in place of uploads while a text-only engine is active. */
export const noImages = Object.freeze([null, null, null, null]);

/** Configured endpoints declare `backend_vision`; local profiles need a matching mmproj. */
export function engineAcceptsImages({ configuredBackend, models, selectedProfile }) {
  if (configuredBackend) return models?.backend_vision !== false;
  return selectedProfile ? selectedProfile.vision_ready === true : true;
}

/** Engine picker label; text-only engines are marked so disabled images are explained. */
export function engineOptionLabel(profile) {
  return profile.vision_ready ? profile.label : `${profile.label} (text only)`;
}
