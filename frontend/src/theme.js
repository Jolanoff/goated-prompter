export const THEME_KEY = "goated-prompter.theme";

// Dark is the product default, independently of the operating-system setting.
export function readTheme(storage) {
  try { return storage?.getItem(THEME_KEY) === "light" ? "light" : "dark"; }
  catch { return "dark"; }
}

export function saveTheme(storage, theme) {
  try { storage?.setItem(THEME_KEY, theme === "light" ? "light" : "dark"); }
  catch { /* The switch still works when browser storage is unavailable. */ }
}
