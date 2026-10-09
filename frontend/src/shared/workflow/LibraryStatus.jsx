import { useEffect, useState } from "react";
import { api } from "../../api.js";

/** Shows how many user library prompts exist for the selected target. */
export default function LibraryStatus({ target, className = "" }) {
  const [status, setStatus] = useState(null);
  useEffect(() => {
    let active = true;
    if (!target) return undefined;
    api(`/library?target=${encodeURIComponent(target)}`)
      .then((data) => { if (active) setStatus(data); })
      .catch(() => { if (active) setStatus(null); });
    return () => { active = false; };
  }, [target]);
  if (!status) return null;
  return <small className={`text-xs leading-relaxed text-muted ${className}`} aria-label="Prompt library status" title={status.path}>
    {status.count
      ? `Prompt library: ${status.count} prompt${status.count === 1 ? "" : "s"} for ${status.target} (data/prompt_library/${status.file})`
      : `Prompt library: empty. Add prompts you like to data/prompt_library/${status.file}`}
  </small>;
}
