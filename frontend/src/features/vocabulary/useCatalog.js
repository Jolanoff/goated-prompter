import { useCallback, useEffect, useState } from "react";
import { api } from "../../api.js";

/** The Vocabulary catalog, read fresh whenever the view becomes visible (or reload is called). */
export function useCatalog(visible) {
  const [catalog, setCatalog] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const reload = useCallback(() => {
    setLoading(true);
    return api("/vocabulary/catalog", undefined, "GET")
      .then((data) => { setCatalog(data); setError(""); })
      .catch((failure) => setError(`Could not load the vocabulary. ${failure.message}`))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { if (visible) void reload(); }, [visible, reload]);
  return { catalog, error, loading: loading && !catalog, reload };
}
