import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  Bookmark,
  Check,
  ChevronDown,
  Copy,
  FileText,
  ImagePlus,
  Layers3,
  LoaderCircle,
  LockKeyhole,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  WandSparkles,
  X,
  Zap,
} from "lucide-react";
import {
  builderSnapshot,
  hydrateBuilder,
  createBuilderSaver,
  referenceAttributes,
  referenceSources,
  JOB_KEY,
  loadSaved,
  SAVED_KEY,
} from "./storage.js";
const activeStatuses = ["running", "pause_requested", "paused"];
const titleCase = (text) =>
  text.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

async function api(path, body, method = "POST") {
  const response = await fetch(
    `/api${path}`,
    body === undefined
      ? {}
      : {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await response
    .json()
    .catch(() => ({ error: "The local server returned an invalid response." }));
  if (!response.ok) {
    const error = new Error(
      data.error || `Request failed (${response.status}).`,
    );
    error.status = response.status;
    error.activeJob = data.active_job;
    throw error;
  }
  return data;
}

function GoatMark({ small = false }) {
  return (
    <svg
      className={`goat-mark ${small ? "small" : ""}`}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="32" cy="32" r="31" fill="currentColor" opacity=".16" />
      <path
        d="M29 20C14 3 5 17 20 28M37 20C51 2 60 17 45 29"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <path d="m22 22 10-6 11 7-2 16-9 15-9-15-1-17Z" fill="currentColor" />
      <path d="m21 24-10-2 7 11 7-1m18-8 10-2-7 11-6-1" fill="currentColor" />
      <path
        d="m26 30 4 2m8-2-4 2m-4 8h5"
        stroke="#171421"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function Panel({
  icon: Icon,
  title,
  subtitle,
  action,
  children,
  className = "",
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-header">
        <div className="panel-icon">
          <Icon size={21} />
        </div>
        <div className="panel-heading">
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

function Toggle({ label, description, checked, onChange, disabled }) {
  return (
    <label className="toggle-row">
      <input
        type="checkbox"
        checked={!!checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
      />
      <span className="switch" aria-hidden="true" />
      <span>
        <span className="toggle-label">{label}</span>
        {description && <small>{description}</small>}
      </span>
    </label>
  );
}

function App() {
  const [bootstrap, setBootstrap] = useState(null);
  const [settings, setSettings] = useState({});
  const [settingsDraft, setSettingsDraft] = useState({});
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [images, setImages] = useState([null, null, null, null]);
  const [builderStatus, setBuilderStatus] = useState("");
  const [builderError, setBuilderError] = useState("");
  const hydrated = useRef(false);
  const saver = useRef(null);
  if (!saver.current)
    saver.current = createBuilderSaver(
      async (builder, keepalive) => {
        const response = await fetch("/api/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ builder }),
          keepalive,
        });
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `Request failed (${response.status}).`);
        }
      },
      (status, message) => {
        setBuilderStatus(status);
        setBuilderError(message);
      },
    );
  const [view, setView] = useState("builder");
  const [directorId, setDirectorId] = useState("");
  const [directorDraft, setDirectorDraft] = useState({
    name: "",
    instructions: "",
  });
  const [directorOriginal, setDirectorOriginal] = useState({
    name: "",
    instructions: "",
  });
  const directorDirty =
    directorDraft.name !== directorOriginal.name ||
    directorDraft.instructions !== directorOriginal.instructions;
  const editorDirector = bootstrap?.presets.presets.find(
    (item) => item.id === directorId,
  );
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saved, setSaved] = useState([]);
  const [storageReady, setStorageReady] = useState(false);
  const [storageWarning, setStorageWarning] = useState("");
  const [storageError, setStorageError] = useState("");
  const [storageReload, setStorageReload] = useState(0);
  const [promptsBusy, setPromptsBusy] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const [job, setJob] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState(0);
  const [actionBusy, setActionBusy] = useState(false);
  const [saveKind, setSaveKind] = useState(null);
  const [saveName, setSaveName] = useState("");
  const [dialogBusy, setDialogBusy] = useState(false);
  const dialogRef = useRef(null);
  const pendingPromptRef = useRef(null);
  const submissionRef = useRef(false);
  const latestJobRef = useRef(null);
  const connectionRef = useRef(0);
  const active = !!job && activeStatuses.includes(job.status);
  const busy = active || submitting;
  const locked = !!settings.lock_generated_prompt;
  const prompt = settings.generated_prompt || "";
  const configuredBackend = ["mock", "openai_compatible"].includes(
    bootstrap?.backend,
  );
  const profiles =
    bootstrap?.models.profiles.filter((item) => item.vision_ready) || [];
  const selectedProfile =
    profiles.find((item) => item.id === bootstrap?.settings.selected_profile) ||
    profiles[0];
  const noEngine = !configuredBackend && !selectedProfile;
  const attributes =
    bootstrap?.reference_attributes ||
    referenceAttributes.map((key) => ({
      key,
      label: key === "mood" ? "Mood / style" : titleCase(key),
    }));
  const sources = bootstrap?.reference_sources || referenceSources;
  const hasImages = images.some(Boolean);
  const imageCount = images.filter(Boolean).length;
  const sourceAvailable = (source) => {
    if (!source || source === "Off") return true;
    if (source === "Blend") return imageCount >= 2;
    const slot = Number(source.replace(/\D/g, "")) - 1;
    return slot >= 0 && slot < images.length && !!images[slot];
  };
  const hasInvalidReferenceMappings = referenceAttributes.some(
    (key) => !sourceAvailable(settings[`reference_${key}_source`]),
  );
  const missingReferences = attributes.filter(({ key }) => {
    const source = settings[`reference_${key}_source`];
    return source === "Blend"
      ? images.filter(Boolean).length < 2
      : source &&
          source !== "Off" &&
          !images[Number(source.replace(/\D/g, "")) - 1];
  });
  const preset = bootstrap?.presets.presets.find(
    (item) =>
      item.id === settings.director_preset ||
      item.label === settings.director_preset,
  );
  const status = submitting
    ? "Starting"
    : job?.status === "paused"
      ? "Paused"
      : job?.status === "pause_requested"
        ? "Pause requested"
        : active
          ? "Generating"
          : !bootstrap
            ? "Offline"
            : "Ready";

  function receiveJob(next) {
    const previous = latestJobRef.current;
    if (
      previous?.id === next.id &&
      ((previous.revision ?? -1) > (next.revision ?? -1) ||
        !activeStatuses.includes(previous.status))
    )
      return;
    latestJobRef.current = next;
    setJob(next);
    if (activeStatuses.includes(next.status)) {
      try {
        sessionStorage.setItem(JOB_KEY, next.id);
      } catch {
        /* Optional reload recovery. */
      }
    } else {
      try {
        sessionStorage.removeItem(JOB_KEY);
      } catch {
        /* Optional reload recovery. */
      }
      if (next.status === "succeeded") {
        setSettings((current) => ({
          ...current,
          generated_prompt: next.result.prompt,
        }));
        setNotice(
          next.result.backend === "locked"
            ? "Locked prompt kept exactly as written."
            : "Your prompt is ready. Make it yours.",
        );
      } else
        setError(next.error || "Generation failed. Check the backend console.");
    }
  }

  async function connect() {
    const attempt = ++connectionRef.current;
    setError("");
    try {
      const data = await api("/bootstrap");
      if (attempt !== connectionRef.current) return;
      setBootstrap(data);
      setSettingsDraft(data.settings);
      if (!hydrated.current) {
        const initial = hydrateBuilder(
          data.inputs,
          data.settings.builder,
          data.presets,
        );
        saver.current.hydrate(initial);
        // Job recovery can finish before bootstrap; retain its newer output.
        if (latestJobRef.current?.status === "succeeded") {
          initial.generated_prompt = latestJobRef.current.result.prompt;
        }
        hydrated.current = true;
        setSettings(initial);
      }
      if (data.active_job) receiveJob(data.active_job);
      if (!storageReady) setStorageReload((value) => value + 1);
    } catch (err) {
      if (attempt !== connectionRef.current) return;
      setError(
        `Cannot connect to the local backend. Run python local_app.py. ${err.message}`,
      );
    }
  }

  useEffect(() => {
    connect();
    try {
      const id = sessionStorage.getItem(JOB_KEY);
      if (id) receiveJob({ id, status: "running", revision: -1 });
    } catch {
      /* Generation works even when browser session storage is unavailable. */
    }
    return () => {
      connectionRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (hydrated.current) saver.current.stage(builderSnapshot(settings));
  }, [settings]);

  useEffect(() => {
    if (!hasInvalidReferenceMappings) return;
    setSettings((previous) => ({
      ...previous,
      ...Object.fromEntries(
        referenceAttributes.map((key) => {
          const field = `reference_${key}_source`;
          return [field, sourceAvailable(previous[field]) ? previous[field] : "Off"];
        }),
      ),
    }));
  }, [images, hasInvalidReferenceMappings]);

  useEffect(() => {
    if (!bootstrap?.presets || !hydrated.current) return;
    setSettings((previous) => {
      const { director_preset } = hydrateBuilder({}, previous, bootstrap.presets);
      return previous.director_preset === director_preset
        ? previous
        : { ...previous, director_preset };
    });
  }, [bootstrap?.presets]);

  useEffect(() => {
    const leave = () => {
      saver.current.flush(true).catch(() => {});
    };
    window.addEventListener("pagehide", leave);
    return () => {
      window.removeEventListener("pagehide", leave);
      saver.current.dispose();
    };
  }, []);

  useEffect(() => {
    if (!storageReload) return;
    let disposed = false;
    async function loadPrompts() {
      setStorageReady(false);
      setStorageError("");
      setStorageWarning("");
      try {
        let data = await api("/prompts");
        if (disposed) return;
        if (!Array.isArray(data.prompts))
          throw new Error("Invalid saved prompts response.");
        try {
          const storage = window.localStorage;
          const legacy = loadSaved(storage);
          if (legacy.length) {
            const imported = await api("/prompts/import", { prompts: legacy });
            if (disposed) return;
            // Only remove the browser copy after every field is confirmed on disk.
            if (
              !Array.isArray(imported.prompts) ||
              !legacy.every((record) =>
                imported.prompts.some(
                  (item) =>
                    Object.keys(item).length === Object.keys(record).length &&
                    Object.keys(record).every(
                      (key) =>
                        Object.hasOwn(item, key) && item[key] === record[key],
                    ),
                ),
              )
            )
              throw new Error(
                "The server did not confirm the exact imported records.",
              );
            data = imported;
            storage.removeItem(SAVED_KEY);
          }
        } catch (err) {
          if (disposed) return;
          setStorageWarning(
            `Browser migration could not finish. Browser data has been kept; server prompts remain available. ${err.message}`,
          );
        }
        if (disposed) return;
        setSaved(data.prompts);
        setStorageReady(true);
      } catch (err) {
        if (!disposed)
          setStorageError(
            `Could not load saved prompts from the local JSON file. ${err.message}`,
          );
      }
    }
    loadPrompts();
    return () => {
      disposed = true;
    };
  }, [storageReload]);

  useEffect(() => {
    if (!active || !job?.id) return;
    let disposed = false;
    let timer;
    async function poll() {
      try {
        const next = await api(`/jobs/${job.id}`);
        if (disposed) return;
        receiveJob(next);
        if (!activeStatuses.includes(next.status)) {
          return;
        }
      } catch (err) {
        if (disposed) return;
        if (err.status === 404) {
          setJob(null);
          latestJobRef.current = null;
          try {
            sessionStorage.removeItem(JOB_KEY);
          } catch {
            /* Optional reload recovery. */
          }
          setError(
            "This job is no longer available. The backend may have restarted; generate again.",
          );
          return;
        }
        setError(
          `Connection interrupted; still checking the current job. ${err.message}`,
        );
      }
      if (!disposed) timer = setTimeout(poll, 700);
    }
    poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [job?.id, active]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4500);
    return () => clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (saveKind) dialogRef.current?.showModal();
    else dialogRef.current?.close();
  }, [saveKind]);

  function update(key, value) {
    setSettings((previous) => ({ ...previous, [key]: value }));
  }

  function selectDirector(item) {
    const draft = {
      name: item?.name || item?.label || "",
      instructions: item?.instructions || "",
    };
    setDirectorId(item?.id || "");
    setDirectorDraft(draft);
    setDirectorOriginal(draft);
  }

  function discardDirector() {
    return (
      !directorDirty || window.confirm("Discard unsaved Director changes?")
    );
  }

  function navigate(next) {
    if (
      next === view ||
      (view === "directors" && (actionBusy || !discardDirector()))
    )
      return;
    if (view === "directors") setDirectorDraft(directorOriginal);
    if (next === "directors" && !directorId)
      selectDirector(preset || bootstrap?.presets.presets[0]);
    setView(next);
  }

  useEffect(() => {
    if (!directorDirty) return;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [directorDirty]);

  async function writeDirector(operation) {
    if (busy || actionBusy) return;
    if (
      operation !== "save" &&
      !window.confirm(
        `${operation === "delete" ? "Delete" : "Reset"} "${editorDirector.label}"? Unsaved changes will be discarded.`,
      )
    )
      return;
    setActionBusy(true);
    setError("");
    setNotice("");
    try {
      let result;
      if (operation === "save")
        result = await api(
          "/presets",
          {
            ...(directorId ? { id: directorId } : {}),
            name: directorDraft.name.trim(),
            instructions: directorDraft.instructions,
          },
          directorId ? "PUT" : "POST",
        );
      else
        result = await api(
          operation === "reset" ? "/presets/reset" : "/presets",
          { id: directorId },
          operation === "reset" ? "POST" : "DELETE",
        );
      const presets = await api("/presets");
      setBootstrap((previous) => ({ ...previous, presets }));
      const fallback =
        presets.presets.find(
          (item) =>
            item.id === presets.default || item.label === presets.default,
        ) || presets.presets[0];
      selectDirector(
        presets.presets.find(
          (item) => item.id === (result.director?.id || directorId),
        ) || fallback,
      );
      setNotice(
        operation === "delete"
          ? "Director deleted."
          : "Director saved to the local JSON file.",
      );
    } catch (err) {
      if (err.activeJob) receiveJob(err.activeJob);
      setError(`Could not ${operation} Director. Draft kept. ${err.message}`);
    } finally {
      setActionBusy(false);
    }
  }

  function field(key, label, optionsOverride) {
    const [type, options = {}] = bootstrap.inputs[key];
    const choices =
      optionsOverride ||
      (Array.isArray(type)
        ? type.map((value) => ({ value, label: value }))
        : null);
    return (
      <label className="field" key={key}>
        <span>{label || titleCase(key)}</span>
        {choices ? (
          <span className="select-wrap">
            <select
              aria-label={label || titleCase(key)}
              value={settings[key] ?? ""}
              onChange={(event) => update(key, event.target.value)}
            >
              {choices.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <ChevronDown size={15} />
          </span>
        ) : (
          <input
            aria-label={label || titleCase(key)}
            type={type === "INT" ? "number" : "text"}
            min={options.min}
            max={options.max}
            step={type === "INT" ? 1 : undefined}
            value={settings[key] ?? ""}
            onChange={(event) =>
              update(
                key,
                type === "INT" && event.target.value !== ""
                  ? Number(event.target.value)
                  : event.target.value,
              )
            }
          />
        )}
      </label>
    );
  }

  async function upload(file, slot) {
    if (!file || busy) return;
    if (
      !["image/png", "image/jpeg", "image/webp"].includes(file.type) ||
      file.size > 20 * 1024 * 1024
    ) {
      setError("Choose a PNG, JPG, or WEBP image no larger than 20 MiB.");
      return;
    }
    setUploading((count) => count + 1);
    try {
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error("Could not read this image."));
        reader.readAsDataURL(file);
      });
      setImages((previous) =>
        previous.map((image, index) =>
          index === slot ? { data, name: file.name } : image,
        ),
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading((count) => count - 1);
    }
  }

  async function generate(textOnly = false) {
    if (
      submissionRef.current ||
      busy ||
      uploading ||
      actionBusy ||
      settingsBusy ||
      (!locked && noEngine)
    )
      return;
    submissionRef.current = true;
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      if (!locked && !textOnly && missingReferences.length)
        throw new Error(
          "Reupload the mapped reference images or select Off before generating.",
        );
      saver.current.stage(builderSnapshot(settings));
      await saver.current.flush();
      const next = await api("/generate", {
        settings: {
          ...settings,
          linked_references: true,
          prompt_model: "Custom",
          director_profile: configuredBackend ? "" : selectedProfile?.id || "",
          director_keep_model_loaded: bootstrap.settings.keep_model_loaded,
        },
        images: images.map((image) => image?.data || null),
        text_only: textOnly,
      });
      receiveJob(next);
    } catch (err) {
      if (err.activeJob) receiveJob(err.activeJob);
      else {
        try {
          const data = await api("/bootstrap");
          if (data.active_job) receiveJob(data.active_job);
        } catch {
          /* Keep the original generation error if recovery is unavailable. */
        }
      }
      setError(err.message);
    } finally {
      setSubmitting(false);
      submissionRef.current = false;
    }
  }

  async function pauseResume() {
    setActionBusy(true);
    setError("");
    try {
      receiveJob(
        await api(
          `/jobs/${job.id}/${job.status === "running" ? "pause" : "resume"}`,
          {},
        ),
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setActionBusy(false);
    }
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      setNotice("Prompt copied to clipboard.");
    } catch {
      setError(
        "Clipboard access was blocked. You can select and copy the prompt text directly.",
      );
    }
  }

  async function deletePrompt(record) {
    if (!storageReady || promptsBusy || dialogBusy) return;
    if (!window.confirm(`Delete "${record.title}"? This cannot be undone.`))
      return;
    setPromptsBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await api(
        `/prompts/${encodeURIComponent(record.id)}`,
        {},
        "DELETE",
      );
      setSaved(data.prompts);
      setNotice("Prompt deleted from the local JSON file.");
    } catch (err) {
      setError(`Could not delete prompt. ${err.message}`);
    } finally {
      setPromptsBusy(false);
    }
  }

  function openSave() {
    pendingPromptRef.current = null;
    setDialogError("");
    setSaveKind("prompt");
    setSaveName(
      settings.idea.trim().split("\n")[0].slice(0, 70) || "Untitled prompt",
    );
  }

  async function save(event) {
    event.preventDefault();
    if (!saveName.trim() || dialogBusy || !storageReady || promptsBusy) return;
    setDialogBusy(true);
    setDialogError("");
    setError("");
    setNotice("");
    try {
      if (
        pendingPromptRef.current?.title !== saveName.trim() ||
        pendingPromptRef.current?.prompt !== prompt ||
        pendingPromptRef.current?.target !== settings.target_model
      )
        pendingPromptRef.current = {
          id: crypto.randomUUID(),
          title: saveName.trim(),
          prompt,
          createdAt: new Date().toISOString(),
          target: settings.target_model,
        };
      const data = await api("/prompts", pendingPromptRef.current);
      setSaved(data.prompts);
      setNotice("Prompt saved to the local JSON file.");
      setSaveKind(null);
    } catch (err) {
      setDialogError(`Could not save. ${err.message}`);
    } finally {
      setDialogBusy(false);
    }
  }

  async function modelAction(unload = false) {
    if (busy || actionBusy || settingsBusy) return;
    setActionBusy(true);
    setError("");
    try {
      if (unload) setNotice((await api("/unload", {})).message);
      else {
        const models = await api("/models?refresh=true");
        setBootstrap((previous) => ({ ...previous, models }));
        setNotice("Model folders rescanned.");
      }
    } catch (err) {
      if (err.activeJob) receiveJob(err.activeJob);
      setError(
        `Could not ${unload ? "unload the model" : "refresh models"}. Check the backend connection${unload ? " and wait for any active job to finish" : " and the saved folder's accessibility"}, then retry. ${err.message}`,
      );
    } finally {
      setActionBusy(false);
    }
  }

  async function saveSettings(event, profileId) {
    event?.preventDefault();
    if (busy || settingsBusy || actionBusy) return;
    setSettingsBusy(true);
    setError("");
    setNotice("");
    let persisted = false;
    try {
      const payload =
        profileId !== undefined
          ? { selected_profile: profileId }
          : {
              models_directory: settingsDraft.models_directory.trim(),
              keep_model_loaded: settingsDraft.keep_model_loaded,
              selected_profile:
                settingsDraft.models_directory.trim() !==
                bootstrap.settings.models_directory
                  ? ""
                  : bootstrap.settings.selected_profile,
            };
      const savedSettings = await api("/settings", payload, "PUT");
      persisted = true;
      setBootstrap((previous) => ({
        ...previous,
        settings: savedSettings,
        models:
          profileId === undefined
            ? { ...previous.models, profiles: [], warnings: [] }
            : previous.models,
      }));
      if (profileId === undefined) {
        setSettingsDraft(savedSettings);
        const data = await api("/bootstrap");
        setBootstrap(data);
        setSettingsDraft(data.settings);
        if (data.active_job) receiveJob(data.active_job);
      }
      setNotice(
        profileId === undefined
          ? "Settings saved. Model folders rescanned."
          : "Prompt engine saved.",
      );
    } catch (err) {
      if (err.activeJob) receiveJob(err.activeJob);
      setError(
        persisted
          ? `Settings saved, but models could not be refreshed. Use Refresh models in Settings. ${err.message}`
          : `Could not save settings. Check that the models directory exists on the server and is accessible, then retry. ${err.message}`,
      );
    } finally {
      setSettingsBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="sidebar-brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            navigate("builder");
          }}
          aria-label="Goated Prompter home"
        >
          <GoatMark />
          <span>
            GOATED<span className="brand-sub">PROMPTER</span>
          </span>
        </a>
        <div className="nav-caption">WORKSPACE</div>
        <nav aria-label="Workspace">
          <button
            className={view === "builder" ? "nav-item selected" : "nav-item"}
            onClick={() => navigate("builder")}
          >
            <SlidersHorizontal size={19} />
            Prompt Builder
          </button>
          <button
            className={view === "saved" ? "nav-item selected" : "nav-item"}
            onClick={() => navigate("saved")}
          >
            <Bookmark size={19} />
            Saved Prompts<span className="nav-count">{saved.length}</span>
          </button>
          <button
            className={view === "directors" ? "nav-item selected" : "nav-item"}
            onClick={() => navigate("directors")}
            disabled={!bootstrap}
          >
            <WandSparkles size={19} />
            Directors
          </button>
          <button
            className={view === "settings" ? "nav-item selected" : "nav-item"}
            onClick={() => navigate("settings")}
          >
            <Settings2 size={19} />
            Settings
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="local-label">
            <span className="status-dot" />
            YOUR LOCAL WORKSPACE
          </div>
          <p>
            Good prompts.
            <br />
            <span>Great possibilities.</span>
          </p>
          <svg
            className="mountains"
            viewBox="0 0 240 145"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="m0 120 49-56 22 24 40-76 34 54 22-17 73 80v16H0Z"
              fill="#262036"
            />
            <path
              d="m37 140 74-128-18 87 31-20 22 64m-40-81 39 4 22-17-17 58 90 32"
              fill="#3c3055"
            />
            <path d="m0 142 77-39 42 22 43-27 78 41v6H0Z" fill="#17151f" />
            <path
              d="m111 12 9 37-12-7-15 57M49 64l-4 35 13-13 13 2"
              stroke="#71608f"
              strokeOpacity=".6"
            />
          </svg>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="header-title">
            <GoatMark small />
            <div>
              <h1>Goated Prompter</h1>
              <p>Sharper ideas. Better prompts.</p>
            </div>
          </div>
          <div className="header-right">
            <span className={`connection-pill ${bootstrap ? "" : "offline"}`}>
              <span className="status-dot" />
              {bootstrap ? "Local backend connected" : "Backend offline"}
            </span>
            <span className="local-only">
              <Zap size={14} />
              LOCAL WORKSPACE
            </span>
          </div>
        </header>

        <main className={view === "builder" ? "builder-main" : ""}>
          {bootstrap && (
            <div
              className="builder-save"
              aria-live="polite"
              aria-label="Builder save status"
            >
              <span>{builderStatus}</span>
              {builderError && (
                <>
                  <span role="alert">
                    Could not save builder. Draft kept in this page.{" "}
                    {builderError}
                  </span>
                  <button
                    className="button"
                    onClick={() => saver.current.flush().catch(() => {})}
                  >
                    Retry builder save
                  </button>
                </>
              )}
            </div>
          )}
          {storageWarning && (
            <div className="message error" role="alert">
              {storageWarning}
            </div>
          )}
          {storageError && (
            <div className="message error" role="alert">
              <span>{storageError}</span>
              <button onClick={() => setStorageReload((value) => value + 1)}>
                Retry saved prompts
              </button>
            </div>
          )}
          {error && (
            <div className="message error" role="alert">
              <span>{error}</span>
              {!bootstrap && (
                <button onClick={connect}>Retry connection</button>
              )}
              <button
                className="icon-button"
                onClick={() => setError("")}
                aria-label="Dismiss error"
              >
                <X size={16} />
              </button>
            </div>
          )}
          <div className="toast-region" role="status">
            {notice && (
              <div className="toast">
                <Check size={16} />
                {notice}
              </div>
            )}
          </div>

          {view === "saved" ? (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">YOUR COLLECTION</div>
                  <h2>
                    Prompts worth keeping<span>.</span>
                  </h2>
                  <p>
                    Saved in a local JSON file on this server. Ready for your
                    next creation.
                  </p>
                </div>
                <button className="button" onClick={() => setView("builder")}>
                  <ArrowLeft size={16} />
                  Back to builder
                </button>
              </div>
              {!storageReady ? (
                <div className="empty-state">
                  <Bookmark size={34} />
                  <h3>Saved prompts are not ready yet</h3>
                  <p>
                    Loading from the local server. If the connection fails,
                    retry above.
                  </p>
                </div>
              ) : saved.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-icon">
                    <Bookmark size={30} />
                  </div>
                  <h3>A home for your best ideas.</h3>
                  <p>
                    Generate a prompt, then hit Save Prompt to keep it here.
                  </p>
                  <button
                    className="button primary-small"
                    onClick={() => setView("builder")}
                  >
                    <Plus size={16} />
                    Create a prompt
                  </button>
                </div>
              ) : (
                <div className="saved-grid">
                  {saved.map((record) => (
                    <article className="panel saved-card" key={record.id}>
                      <div className="saved-meta">
                        <span>{record.target || "Prompt"}</span>
                        <time dateTime={record.createdAt}>
                          {new Date(record.createdAt).toLocaleDateString(
                            undefined,
                            { month: "short", day: "numeric", year: "numeric" },
                          )}
                        </time>
                      </div>
                      <h3>{record.title}</h3>
                      <pre tabIndex={0}>{record.prompt}</pre>
                      <div className="saved-actions">
                        <button
                          className="button"
                          onClick={() => copy(record.prompt)}
                        >
                          <Copy size={15} />
                          Copy
                        </button>
                        <button
                          className="button"
                          disabled={busy}
                          onClick={() => {
                            update("generated_prompt", record.prompt);
                            setView("builder");
                          }}
                        >
                          <ArrowUpRight size={15} />
                          Open
                        </button>
                        <button
                          className="icon-button delete-button"
                          aria-label={`Delete ${record.title}`}
                          disabled={!storageReady || promptsBusy || dialogBusy}
                          onClick={() => deletePrompt(record)}
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </>
          ) : !bootstrap ? (
            <div className="empty-state">
              <GoatMark />
              <h2>Your workspace is getting ready</h2>
              <p>
                Connect to the Python backend to load the node's controls and
                models.
              </p>
              <code>python local_app.py</code>
            </div>
          ) : view === "directors" ? (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">YOUR DIRECTION</div>
                  <h2>
                    Directors<span>.</span>
                  </h2>
                  <p>Saved instructions, ready for every generation.</p>
                </div>
              </div>
              <div className="directors-grid">
                <Panel
                  icon={WandSparkles}
                  title="Director library"
                  subtitle="Choose a saved Director to edit."
                >
                  <div className="director-list">
                    {bootstrap.presets.presets.map((item) => (
                      <button
                        key={item.id}
                        className={`director-choice ${directorId === item.id ? "selected" : ""}`}
                        disabled={actionBusy}
                        onClick={() => {
                          if (item.id !== directorId && discardDirector())
                            selectDirector(item);
                        }}
                      >
                        <strong>{item.label}</strong>
                        <span>
                          {item.protected ? "Built-in" : "User"}
                          {item.modified ? " / Edited" : ""}
                        </span>
                      </button>
                    ))}
                  </div>
                  <button
                    className="button"
                    disabled={busy || actionBusy}
                    onClick={() => {
                      if (discardDirector()) selectDirector(null);
                    }}
                  >
                    <Plus size={15} />
                    New director
                  </button>
                </Panel>
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    writeDirector("save");
                  }}
                >
                  <fieldset disabled={busy || actionBusy}>
                    <Panel
                      icon={FileText}
                      title={directorId ? "Edit Director" : "New Director"}
                      subtitle={
                        directorDirty
                          ? "Unsaved changes"
                          : "Instructions saved separately from your builder."
                      }
                    >
                      <label className="field">
                        <span>Director name</span>
                        <input
                          required
                          maxLength={80}
                          readOnly={!!editorDirector?.protected}
                          value={directorDraft.name}
                          onChange={(event) =>
                            setDirectorDraft((draft) => ({
                              ...draft,
                              name: event.target.value,
                            }))
                          }
                        />
                      </label>
                      {editorDirector?.protected && (
                        <p className="subtle-note">
                          Built-in names cannot be changed. Instructions can be
                          edited and restored.
                        </p>
                      )}
                      <p className="subtle-note">
                        {editorDirector?.description}
                      </p>
                      <label className="field">
                        <span>Director instructions</span>
                        <textarea
                          className="director-input"
                          required
                          value={directorDraft.instructions}
                          onChange={(event) =>
                            setDirectorDraft((draft) => ({
                              ...draft,
                              instructions: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <div className="inline-actions">
                        <button
                          className="button primary-small"
                          disabled={
                            !directorDirty ||
                            !directorDraft.name.trim() ||
                            !directorDraft.instructions.trim()
                          }
                        >
                          <Save size={14} />
                          Save changes
                        </button>
                        {editorDirector && (
                          <button
                            type="button"
                            className="button"
                            onClick={() => {
                              if (discardDirector()) {
                                setDirectorDraft(directorOriginal);
                                update("director_preset", directorId);
                                setView("builder");
                              }
                            }}
                          >
                            Use in builder
                          </button>
                        )}
                        {editorDirector && !editorDirector.protected && (
                          <button
                            type="button"
                            className="button"
                            onClick={() => writeDirector("delete")}
                          >
                            <Trash2 size={14} />
                            Delete Director
                          </button>
                        )}
                        {editorDirector?.protected &&
                          editorDirector.modified && (
                            <button
                              type="button"
                              className="button"
                              onClick={() => writeDirector("reset")}
                            >
                              <RotateCcw size={14} />
                              Reset built-in
                            </button>
                          )}
                      </div>
                      <p className="subtle-note path-note">
                        Stored JSON library: {bootstrap.presets.storage}
                      </p>
                    </Panel>
                  </fieldset>
                  {busy && (
                    <p className="warning-note">
                      Directors are read-only while a generation job is active.
                    </p>
                  )}
                </form>
              </div>
              {bootstrap.presets.warnings?.map((warning, index) => (
                <p className="warning-note" key={index}>
                  {warning}
                </p>
              ))}
            </>
          ) : view === "settings" ? (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">YOUR LOCAL SETUP</div>
                  <h2>
                    Settings<span>.</span>
                  </h2>
                  <p>
                    Model discovery and retention, saved in a local JSON file on
                    this server.
                  </p>
                </div>
                <button className="button" onClick={() => setView("builder")}>
                  <ArrowLeft size={16} />
                  Back to builder
                </button>
              </div>
              <form onSubmit={saveSettings} className="settings-form">
                <fieldset disabled={busy || settingsBusy || actionBusy}>
                  <Panel
                    icon={Layers3}
                    title="Local models"
                    subtitle={`Configured backend: ${bootstrap.backend}`}
                  >
                    <label className="field">
                      <span>Models directory</span>
                      <input
                        required
                        value={settingsDraft.models_directory || ""}
                        aria-describedby="folder-help"
                        onChange={(event) =>
                          setSettingsDraft((previous) => ({
                            ...previous,
                            models_directory: event.target.value,
                          }))
                        }
                      />
                    </label>
                    <p className="subtle-note" id="folder-help">
                      Enter an existing folder path on the server. This folder
                      is scanned directly and recursively; no LLM folder is
                      appended. Put each model GGUF and its matching mmproj GGUF
                      in the same subfolder. A folder containing the pair
                      directly also works. Only complete vision-ready profiles
                      appear in Prompt engine.
                    </p>
                    <Toggle
                      label="Keep model loaded"
                      description="Retain the model between generations for faster reuse."
                      checked={settingsDraft.keep_model_loaded}
                      onChange={(value) =>
                        setSettingsDraft((previous) => ({
                          ...previous,
                          keep_model_loaded: value,
                        }))
                      }
                    />
                    <div className="inline-actions">
                      <button className="button primary-small" type="submit">
                        <Save size={14} />
                        {settingsBusy ? "Saving..." : "Save settings"}
                      </button>
                      <button
                        className="button"
                        type="button"
                        onClick={() => modelAction()}
                      >
                        <RefreshCw size={14} />
                        Refresh models
                      </button>
                      <button
                        className="button"
                        type="button"
                        onClick={() => modelAction(true)}
                      >
                        <Layers3 size={14} />
                        Unload model
                      </button>
                    </div>
                    {busy && (
                      <p className="warning-note">
                        Settings are read-only while a generation job is active.
                        Return to the builder to manage the job.
                      </p>
                    )}
                    <p className="subtle-note path-note">
                      Scanned folder: {bootstrap.models.root}
                    </p>
                    <p className="subtle-note">
                      {profiles.length} ready prompt engines found.
                      {configuredBackend &&
                        " Generation uses your configured backend, even without local models."}
                    </p>
                    {bootstrap.models.profiles
                      .filter((item) => !item.vision_ready)
                      .map((item) => (
                        <p className="warning-note" key={item.id}>
                          {item.label}: incomplete model. Add the model GGUF and
                          matching mmproj to the same folder, then refresh
                          models.
                        </p>
                      ))}
                    {bootstrap.models.warnings.map((warning, index) => (
                      <p className="warning-note" key={index}>
                        {warning}
                      </p>
                    ))}
                  </Panel>
                </fieldset>
              </form>
            </>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">FROM A SPARK TO SOMETHING GREAT</div>
                  <h2>
                    Make your next idea <span>look better.</span>
                  </h2>
                  <p>
                    Your vision, refined. Built for your image and video
                    workflows.
                  </p>
                </div>
                <span className="workspace-tag">
                  <Layers3 size={14} />
                  Prompt workspace
                </span>
              </div>

              <fieldset className="workspace-fieldset" disabled={busy}>
                <div className="workspace-grid">
                  <div className="column main-column">
                    <Panel
                      icon={FileText}
                      title="Describe your idea"
                      subtitle="Start with the subject, mood, setting, or a little bit of everything."
                      className="idea-panel"
                    >
                      <div className="textarea-wrap">
                        <textarea
                          aria-label="Describe your idea"
                          className="idea-input"
                          value={settings.idea}
                          onChange={(event) =>
                            update("idea", event.target.value)
                          }
                          placeholder="A cinematic portrait of a wandering samurai in a misty forest at dawn..."
                        />
                        <span className="char-count">
                          {settings.idea.length.toLocaleString()} characters
                        </span>
                      </div>
                      <div className="input-hint">
                        <Sparkles size={13} />
                        <span>
                          A rough idea is all you need. Let your Director handle
                          the details.
                        </span>
                      </div>
                    </Panel>

                    <Panel
                      icon={SlidersHorizontal}
                      title="Prompt controls"
                      subtitle="Choose how your idea takes shape."
                    >
                      <div className="fields two-fields">
                        {field("mode", "Mode")}
                        {field("target_model", "Target model")}
                      </div>
                      <div className="fields three-fields">
                        {field("creativity", "Creativity")}
                        {field(
                          "prompt_length",
                          "Prompt length",
                          ["Short", "Medium", "Detailed", "Maximum Detail"].map(
                            (value) => ({ value, label: value }),
                          ),
                        )}
                        <label className="field">
                          <span>Prompt engine</span>
                          <span className="select-wrap">
                            <select
                              aria-label="Prompt engine"
                              value={
                                configuredBackend
                                  ? "configured"
                                  : selectedProfile?.id || ""
                              }
                              disabled={
                                settingsBusy ||
                                actionBusy ||
                                configuredBackend ||
                                noEngine
                              }
                              onChange={(event) =>
                                saveSettings(null, event.target.value)
                              }
                            >
                              {configuredBackend ? (
                                <option value="configured">
                                  Configured backend ({bootstrap.backend})
                                </option>
                              ) : profiles.length ? (
                                profiles.map((item) => (
                                  <option key={item.id} value={item.id}>
                                    {item.label}
                                  </option>
                                ))
                              ) : (
                                <option value="">No ready local engines</option>
                              )}
                            </select>
                            <ChevronDown size={15} />
                          </span>
                        </label>
                      </div>
                      <p className="subtle-note">
                        Maximum Detail uses the largest output budget, not a
                        guaranteed word count. Actual length depends on the
                        model and your instructions.
                      </p>
                      {noEngine && (
                        <p className="warning-note">
                          No complete local model found.{" "}
                          <button
                            className="text-button"
                            onClick={() => setView("settings")}
                          >
                            Set up models in Settings
                          </button>
                        </p>
                      )}
                      <div className="director-field">
                        {field(
                          "director_preset",
                          "Director",
                          bootstrap.presets.presets.map((item) => ({
                            value: item.id,
                            label: item.label,
                          })),
                        )}
                        <span className="director-description">
                          {preset?.description ||
                            "Select a Director to guide the prompt."}
                        </span>
                        <button
                          className="text-button"
                          onClick={() => {
                            selectDirector(preset || bootstrap.presets.presets[0]);
                            navigate("directors");
                          }}
                        >
                          Manage Directors
                        </button>
                      </div>
                    </Panel>

                    <Panel
                      icon={WandSparkles}
                      title="Generated prompt"
                      subtitle="Your next creation starts here. Edit it until it feels right."
                      action={
                        <span
                          className={`result-status ${active ? "working" : ""}`}
                        >
                          <span className="status-dot" />
                          {active ? status : prompt ? "Ready" : "Awaiting idea"}
                        </span>
                      }
                      className="output-panel"
                    >
                      <div className="textarea-wrap output-wrap">
                        <textarea
                          aria-label="Generated prompt"
                          value={prompt}
                          onChange={(event) =>
                            update("generated_prompt", event.target.value)
                          }
                          placeholder="A little direction. A lot of possibility.\n\nYour generated prompt will appear here."
                          spellCheck={false}
                        />
                        <span className="char-count">
                          {prompt.length.toLocaleString()} characters
                        </span>
                      </div>
                      <div className="output-actions">
                        <button
                          className="button"
                          disabled={!prompt}
                          onClick={() => copy(prompt)}
                        >
                          <Copy size={16} />
                          Copy Prompt
                        </button>
                        <button
                          className="button save-button"
                          disabled={
                            !prompt.trim() ||
                            !storageReady ||
                            promptsBusy ||
                            dialogBusy
                          }
                          onClick={openSave}
                        >
                          <Bookmark size={16} />
                          Save Prompt
                        </button>
                        <button
                          className="button"
                          disabled={!prompt || locked}
                          onClick={() => update("generated_prompt", "")}
                        >
                          <Trash2 size={16} />
                          Clear
                        </button>
                      </div>
                      <div className="lock-row">
                        <Toggle
                          label="Lock output"
                          checked={locked}
                          onChange={(value) =>
                            update("lock_generated_prompt", value)
                          }
                        />
                        <span>
                          <LockKeyhole size={12} />
                          Reuse this exact text without inference
                        </span>
                      </div>
                    </Panel>
                  </div>
                  <div className="column reference-column">
                    <Panel
                      icon={ImagePlus}
                      title="Reference images"
                      subtitle="Bring your vision into focus. Up to four images."
                      action={
                        <span className="count-chip">
                          {images.filter(Boolean).length} / 4
                        </span>
                      }
                    >
                      <div className="image-slots">
                        {images.map((image, index) => (
                          <div
                            className={`image-slot ${image ? "has-image" : ""}`}
                            key={index}
                            onDragOver={(event) => event.preventDefault()}
                            onDrop={(event) => {
                              event.preventDefault();
                              if (event.dataTransfer.files.length !== 1)
                                setError(
                                  "Drop one image into each slot. The limit is four references.",
                                );
                              else upload(event.dataTransfer.files[0], index);
                            }}
                          >
                            {image ? (
                              <>
                                <img
                                  src={image.data}
                                  alt={`Reference ${index + 1}: ${image.name}`}
                                />
                                <button
                                  className="image-remove"
                                  aria-label={`Remove image ${index + 1}`}
                                  onClick={() =>
                                    setImages((previous) =>
                                      previous.map((item, slot) =>
                                        slot === index ? null : item,
                                      ),
                                    )
                                  }
                                >
                                  <X size={15} />
                                </button>
                                <div className="image-caption">
                                  <span>IMAGE {index + 1}</span>
                                  <span title={image.name}>{image.name}</span>
                                </div>
                              </>
                            ) : (
                              <label className="upload-label">
                                <input
                                  type="file"
                                  aria-label={`Upload image ${index + 1}`}
                                  accept="image/png,image/jpeg,image/webp"
                                  onChange={(event) => {
                                    upload(event.target.files[0], index);
                                    event.target.value = "";
                                  }}
                                />
                                <span className="upload-icon">
                                  <ImagePlus size={24} />
                                </span>
                                <strong>Add image {index + 1}</strong>
                                <span>Drop here or click to browse</span>
                                <small>PNG, JPG, WEBP</small>
                              </label>
                            )}
                          </div>
                        ))}
                      </div>
                      <p className="subtle-note">
                        Images are not saved. References need reuploading after
                        reload; unavailable preserve mappings reset to Off.
                      </p>
                    </Panel>
                    <Panel
                      icon={Settings2}
                      title="Preserve references"
                      subtitle="One source per attribute. Off leaves it unpreserved."
                    >
                      <div className="reference-map">
                        {attributes.map(({ key: attribute, label }) => (
                          <label className="reference-row" key={attribute}>
                            <span>{label}</span>
                            <span className="select-wrap">
                              <select
                                aria-label={`${titleCase(attribute)} source`}
                                value={hasImages
                                  ? settings[`reference_${attribute}_source`]
                                  : "Off"}
                                disabled={!hasImages}
                                onChange={(event) =>
                                  update(
                                    `reference_${attribute}_source`,
                                    event.target.value,
                                  )
                                }
                              >
                                {sources.map((source) => (
                                  <option
                                    key={source}
                                    disabled={!sourceAvailable(source)}
                                  >
                                    {source}
                                  </option>
                                ))}
                              </select>
                              <ChevronDown size={13} />
                            </span>
                          </label>
                        ))}
                      </div>
                      <p className="subtle-note">
                        Each selected source preserves that attribute. Blend
                        uses all uploaded images and requires at least two.
                      </p>
                      {!!missingReferences.length && (
                        <p className="warning-note" role="alert">
                          Missing references for{" "}
                          {missingReferences
                            .map(({ label }) => label)
                            .join(", ")}
                          . Reupload the mapped images or select Off. Blend
                          needs at least two images. Text-only preview ignores
                          these mappings.
                        </p>
                      )}
                    </Panel>

                    <Panel
                      icon={FileText}
                      title="Workflow rules / notes"
                      subtitle="Extra instructions, constraints, and finishing touches."
                    >
                      <textarea
                        className="notes-input"
                        aria-label="Workflow rules"
                        placeholder="e.g. Avoid text and watermarks. Keep natural lighting and focus on realistic textures..."
                        value={settings.custom_instructions}
                        onChange={(event) =>
                          update("custom_instructions", event.target.value)
                        }
                      />
                    </Panel>
                  </div>
                </div>
              </fieldset>

              <div className="generation-bar">
                <button
                  className="generate-button"
                  disabled={
                    (!locked && !!missingReferences.length) ||
                    busy ||
                    !!uploading ||
                    actionBusy ||
                    settingsBusy ||
                    (!locked && noEngine)
                  }
                  onClick={() => generate(false)}
                >
                  {busy ? (
                    <LoaderCircle
                      size={25}
                      className={job?.status === "paused" ? "" : "spinning"}
                    />
                  ) : locked ? (
                    <LockKeyhole size={24} />
                  ) : (
                    <Sparkles size={25} />
                  )}
                  <span>
                    <strong>
                      {busy
                        ? status === "Pause requested"
                          ? "Finishing current stage"
                          : status
                        : locked
                          ? "Use locked prompt"
                          : "Generate prompt"}
                    </strong>
                    <small>
                      {busy
                        ? "Your idea is in good hands"
                        : locked
                          ? "Keep the exact output, no inference"
                          : images.some(Boolean)
                            ? "Create a prompt grounded in your references"
                            : "Turn your idea into a refined prompt"}
                    </small>
                  </span>
                </button>
                <button
                  className={`pause-button ${job?.status === "paused" || job?.status === "pause_requested" ? "resume" : ""}`}
                  disabled={!active || actionBusy}
                  onClick={pauseResume}
                >
                  {job?.status === "paused" ||
                  job?.status === "pause_requested" ? (
                    <Play size={23} />
                  ) : (
                    <Pause size={23} />
                  )}
                  <span>
                    <strong>
                      {job?.status === "paused" ||
                      job?.status === "pause_requested"
                        ? "Resume generation"
                        : "Pause generation"}
                    </strong>
                    <small>
                      {job?.status === "pause_requested"
                        ? "Pause requested; waiting for current call"
                        : "Pauses after the active model call"}
                    </small>
                  </span>
                </button>
              </div>
              <div className="below-actions">
                <span>
                  <LockKeyhole size={12} />
                  Settings and saved prompts stay in local JSON files on this
                  server.
                </span>
                <button
                  className="text-button"
                  disabled={
                    busy ||
                    !!uploading ||
                    actionBusy ||
                    settingsBusy ||
                    (!locked && noEngine) ||
                    !settings.idea.trim()
                  }
                  onClick={() => generate(true)}
                >
                  Text-only preview
                  <ArrowUpRight size={13} />
                </button>
                <span className="preview-note">
                  Ignores references and Preserve, just like the node.
                </span>
              </div>
            </>
          )}
        </main>
      </div>

      <dialog
        ref={dialogRef}
        onCancel={(event) => {
          if (dialogBusy) event.preventDefault();
          else setSaveKind(null);
        }}
        onClose={() => setSaveKind(null)}
      >
        <form onSubmit={save}>
          <div className="dialog-heading">
            <div className="panel-icon">
              <Bookmark size={22} />
            </div>
            <button
              type="button"
              className="icon-button"
              disabled={dialogBusy}
              onClick={() => setSaveKind(null)}
              aria-label="Close save dialog"
            >
              <X size={19} />
            </button>
          </div>
          <h2>Keep this one.</h2>
          <p>
            Give your prompt a name. It will be saved in a local JSON file on
            this server.
          </p>
          {dialogError && (
            <div className="message error" role="alert">
              {dialogError}
            </div>
          )}
          <label className="field">
            <span>Prompt name</span>
            <input
              autoFocus
              required
              maxLength={80}
              disabled={dialogBusy}
              value={saveName}
              onChange={(event) => setSaveName(event.target.value)}
            />
          </label>
          <button
            className="button primary-small"
            disabled={dialogBusy || !saveName.trim()}
          >
            <Save size={16} />
            {dialogBusy ? "Saving..." : "Save"}
          </button>
        </form>
      </dialog>
    </div>
  );
}

export default App;
