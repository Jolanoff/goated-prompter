import { useEffect, useRef, useState } from "react";
import { orderDisplayPresets, presetDisplayLabel } from "./presetPresentation.js";
import { ui } from "./ui.js";
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
const activeStatuses = ["running", "pause_requested", "paused", "cancelling"];
const titleCase = (text) =>
  text.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const taskLabels = {
  Enhance: "Improve a prompt",
  Archviz: "Architecture & interiors",
  Photography: "Photography",
  Character: "Character",
  Product: "Product",
  "Image Edit": "Edit an image",
  "Style Transfer": "Transfer a style",
  "Dataset Caption": "Caption for a dataset",
  Video: "Video shot",
  Custom: "Custom instructions",
};
const referenceOrder = [
  "subject",
  "face",
  "outfit",
  "pose",
  "scene",
  "composition",
  "camera",
  "lighting",
  "colors",
  "materials",
  "mood",
];

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
      className={`text-[#ad97e8] ${small ? "size-10" : "size-[49px]"}`}
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
    <section className={`${ui.panel} ${className}`}>
      <header className={ui.panelHeader}>
        <div className={ui.panelIcon}>
          <Icon size={21} />
        </div>
        <div className={ui.panelHeading}>
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
    <label className={ui.toggleRow}>
      <input
        className={ui.toggleInput}
        type="checkbox"
        checked={!!checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
      />
      <span className={ui.switch} aria-hidden="true" />
      <span>
        <span className={ui.toggleLabel}>{label}</span>
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
  const attributes = [
    ...(bootstrap?.reference_attributes ||
      referenceAttributes.map((key) => ({
        key,
        label: key === "mood" ? "Mood / style" : titleCase(key),
      }))),
  ].sort((a, b) => referenceOrder.indexOf(a.key) - referenceOrder.indexOf(b.key));
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
  const displayedPresets = orderDisplayPresets(bootstrap?.presets.presets || []);
  const status = submitting
    ? "Starting"
    : job?.status === "cancelling"
      ? "Ending"
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
        setNotice("Your prompt is ready. Make it yours.");
      } else if (next.status === "cancelled") {
        setNotice("Generation ended.");
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
    setSettings((previous) => ({
      ...previous,
      [key]: value,
      ...(key === "mode" && {
        director_preset: bootstrap.presets.mode_directors[value],
      }),
    }));
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
      !directorDirty ||
      window.confirm("Discard unsaved instruction preset changes?")
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
        `${operation === "delete" ? "Delete" : "Reset"} "${presetDisplayLabel(editorDirector)}"? Unsaved changes will be discarded.`,
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
          ? "Instruction preset deleted."
          : "Instruction preset saved to the local JSON file.",
      );
    } catch (err) {
      if (err.activeJob) receiveJob(err.activeJob);
      setError(
        `Could not ${operation} instruction preset. Draft kept. ${err.message}`,
      );
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
      <label className={ui.field} key={key}>
        <span>{label || titleCase(key)}</span>
        {choices ? (
          <span className={ui.selectWrap}>
            <select
              className={ui.select}
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
            className={ui.input}
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
      noEngine
    )
      return;
    submissionRef.current = true;
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      if (!textOnly && missingReferences.length)
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

  async function endGeneration() {
    setActionBusy(true);
    setError("");
    try {
      receiveJob(
        await api(`/jobs/${job.id}/cancel`, {}),
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
    <div className="min-h-screen">
      <aside className={ui.sidebar}>
        <a
          className={ui.sidebarBrand}
          href="#"
          onClick={(event) => {
            event.preventDefault();
            navigate("builder");
          }}
          aria-label="Goated Prompter home"
        >
          <GoatMark />
          <span>
            GOATED<span className={ui.brandSub}>PROMPTER</span>
          </span>
        </a>
        <div className={ui.navCaption}>WORKSPACE</div>
        <nav aria-label="Workspace">
          <button
            className={ui.navItem}
            data-active={view === "builder"}
            onClick={() => navigate("builder")}
          >
            <SlidersHorizontal size={19} />
            Prompt Builder
          </button>
          <button
            className={ui.navItem}
            data-active={view === "saved"}
            onClick={() => navigate("saved")}
          >
            <Bookmark size={19} />
            Saved Prompts<span className={ui.navCount}>{saved.length}</span>
          </button>
          <button
            className={ui.navItem}
            data-active={view === "directors"}
            onClick={() => navigate("directors")}
            disabled={!bootstrap}
          >
            <WandSparkles size={19} />
            Instruction presets
          </button>
          <button
            className={ui.navItem}
            data-active={view === "settings"}
            onClick={() => navigate("settings")}
          >
            <Settings2 size={19} />
            Settings
          </button>
        </nav>
        <div className={ui.sidebarBottom}>
          <div className={ui.localLabel}>
            <span className={ui.statusDot} />
            YOUR LOCAL WORKSPACE
          </div>
          <p>
            Good prompts.
            <br />
            <span>Great possibilities.</span>
          </p>
          <svg
            className="absolute bottom-0 left-0 w-full"
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

      <div className={ui.mainShell}>
        <header className={ui.topbar}>
          <div className={ui.headerTitle}>
            <GoatMark small />
            <div>
              <h1>Goated Prompter</h1>
              <p>Sharper ideas. Better prompts.</p>
            </div>
          </div>
          <div className="flex items-center gap-[22px] mobile:gap-0">
            <span className={ui.connectionPill} data-offline={!bootstrap}>
              <span className={ui.statusDot} />
              {bootstrap ? "Local backend connected" : "Backend offline"}
            </span>
            <span className={ui.localOnly}>
              <Zap size={14} />
              LOCAL WORKSPACE
            </span>
          </div>
        </header>

        <main className={ui.main} data-builder={view === "builder"}>
          {bootstrap && (
            <div
              className={ui.builderSave}
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
                    className={ui.button}
                    onClick={() => saver.current.flush().catch(() => {})}
                  >
                    Retry builder save
                  </button>
                </>
              )}
            </div>
          )}
          {storageWarning && (
            <div className={ui.message} role="alert">
              {storageWarning}
            </div>
          )}
          {storageError && (
            <div className={ui.message} role="alert">
              <span>{storageError}</span>
              <button className={ui.retryButton} onClick={() => setStorageReload((value) => value + 1)}>
                Retry saved prompts
              </button>
            </div>
          )}
          {error && (
            <div className={ui.message} role="alert">
              <span>{error}</span>
              {!bootstrap && (
                <button className={ui.retryButton} onClick={connect}>Retry connection</button>
              )}
              <button
                className={ui.iconButton}
                onClick={() => setError("")}
                aria-label="Dismiss error"
              >
                <X size={16} />
              </button>
            </div>
          )}
          <div className={ui.toastRegion} data-builder={view === "builder" && !!bootstrap} role="status">
            {notice && (
              <div className={ui.toast}>
                <Check size={16} />
                {notice}
              </div>
            )}
          </div>

          {view === "saved" ? (
            <>
              <div className={ui.pageHeading}>
                <div>
                  <div className={ui.eyebrow}>YOUR COLLECTION</div>
                  <h2>
                    Prompts worth keeping<span>.</span>
                  </h2>
                  <p>
                    Saved in a local JSON file on this server. Ready for your
                    next creation.
                  </p>
                </div>
                <button className={ui.button} onClick={() => setView("builder")}>
                  <ArrowLeft size={16} />
                  Back to builder
                </button>
              </div>
              {!storageReady ? (
                <div className={ui.emptyState}>
                  <Bookmark size={34} />
                  <h3>Saved prompts are not ready yet</h3>
                  <p>
                    Loading from the local server. If the connection fails,
                    retry above.
                  </p>
                </div>
              ) : saved.length === 0 ? (
                <div className={ui.emptyState}>
                  <div className={ui.emptyIcon}>
                    <Bookmark size={30} />
                  </div>
                  <h3>A home for your best ideas.</h3>
                  <p>
                    Generate a prompt, then hit Save Prompt to keep it here.
                  </p>
                  <button
                    className={ui.primaryButton}
                    onClick={() => setView("builder")}
                  >
                    <Plus size={16} />
                    Create a prompt
                  </button>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-[18px] mobile:grid-cols-1">
                  {saved.map((record) => (
                    <article className={ui.savedCard} key={record.id}>
                      <div className={ui.savedMeta}>
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
                      <div className="flex gap-2 border-t border-line pt-[15px]">
                        <button
                          className={ui.button}
                          onClick={() => copy(record.prompt)}
                        >
                          <Copy size={15} />
                          Copy
                        </button>
                        <button
                          className={ui.button}
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
                          className={ui.deleteButton}
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
            <div className={ui.emptyState}>
              <GoatMark />
              <h2>Your workspace is getting ready</h2>
              <p>
                Connect to the Python backend to load your workspace controls and
                models.
              </p>
              <code>python local_app.py</code>
            </div>
          ) : view === "directors" ? (
            <>
              <div className={ui.pageHeading}>
                <div>
                  <div className={ui.eyebrow}>YOUR DIRECTION</div>
                  <h2>
                    Instruction presets<span>.</span>
                  </h2>
                  <p>
                    Reusable instructions that guide how your prompt task is written.
                  </p>
                </div>
              </div>
              <div className={ui.directorsGrid}>
                <Panel
                  icon={WandSparkles}
                  title="Instruction presets"
                  subtitle="Choose saved instructions to edit."
                >
                  <div className={ui.directorList}>
                    {displayedPresets.map((item) => (
                      <button
                        key={item.id}
                        className={`${ui.directorChoice} ${directorId === item.id ? "selected" : ""}`}
                        data-active={directorId === item.id}
                        disabled={actionBusy}
                        onClick={() => {
                          if (item.id !== directorId && discardDirector())
                            selectDirector(item);
                        }}
                      >
                        <strong>{presetDisplayLabel(item)}</strong>
                        <span>
                          {item.protected ? "Built-in" : "User"}
                          {item.modified ? " / Edited" : ""}
                        </span>
                      </button>
                    ))}
                  </div>
                  <button
                    className={ui.button}
                    disabled={busy || actionBusy}
                    onClick={() => {
                      if (discardDirector()) selectDirector(null);
                    }}
                  >
                    <Plus size={15} />
                    New instruction preset
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
                      title={
                        directorId ? "Edit instruction preset" : "New instruction preset"
                      }
                      subtitle={
                        directorDirty
                          ? "Unsaved changes"
                          : "Instructions saved separately from your builder."
                      }
                    >
                      <label className={ui.field}>
                        <span>Instruction preset name</span>
                        <input
                          className={ui.input}
                          required
                          maxLength={80}
                          readOnly={!!editorDirector?.protected}
                          value={editorDirector?.protected
                            ? presetDisplayLabel(editorDirector)
                            : directorDraft.name}
                          onChange={(event) =>
                            setDirectorDraft((draft) => ({
                              ...draft,
                              name: event.target.value,
                            }))
                          }
                        />
                      </label>
                      {editorDirector?.protected && (
                        <p className={ui.subtleNote}>
                          Built-in names cannot be changed. Instructions can be
                          edited and restored.
                        </p>
                      )}
                      <p className={ui.subtleNote}>
                        {editorDirector?.description === "User Director"
                          ? "User instruction preset"
                          : editorDirector?.description}
                      </p>
                      <label className={ui.field}>
                        <span>Preset instructions</span>
                        <textarea
                          className={ui.directorInput}
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
                      <div className={ui.inlineActions}>
                        <button
                          className={ui.primaryButton}
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
                            className={ui.button}
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
                            className={ui.button}
                            onClick={() => writeDirector("delete")}
                          >
                            <Trash2 size={14} />
                            Delete instruction preset
                          </button>
                        )}
                        {editorDirector?.protected &&
                          editorDirector.modified && (
                            <button
                              type="button"
                              className={ui.button}
                              onClick={() => writeDirector("reset")}
                            >
                              <RotateCcw size={14} />
                              Reset built-in
                            </button>
                          )}
                      </div>
                      <p className={`${ui.subtleNote} wrap-anywhere`}>
                        Stored JSON library: {bootstrap.presets.storage}
                      </p>
                    </Panel>
                  </fieldset>
                  {busy && (
                    <p className={ui.warningNote}>
                      Instruction presets are read-only while a generation job is active.
                    </p>
                  )}
                </form>
              </div>
              {bootstrap.presets.warnings?.map((warning, index) => (
                <p className={ui.warningNote} key={index}>
                  {warning}
                </p>
              ))}
            </>
          ) : view === "settings" ? (
            <>
              <div className={ui.pageHeading}>
                <div>
                  <div className={ui.eyebrow}>YOUR LOCAL SETUP</div>
                  <h2>
                    Settings<span>.</span>
                  </h2>
                  <p>
                    Model discovery and retention, saved in a local JSON file on
                    this server.
                  </p>
                </div>
                <button className={ui.button} onClick={() => setView("builder")}>
                  <ArrowLeft size={16} />
                  Back to builder
                </button>
              </div>
              <form onSubmit={saveSettings} className={ui.settingsForm}>
                <fieldset disabled={busy || settingsBusy || actionBusy}>
                  <Panel
                    icon={Layers3}
                    title="Local models"
                    subtitle={`Configured backend: ${bootstrap.backend}`}
                  >
                    <label className={ui.field}>
                      <span>Models directory</span>
                      <input
                        className={ui.input}
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
                    <p className={ui.subtleNote} id="folder-help">
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
                    <div className="mt-[22px] flex flex-wrap items-center gap-2">
                      <button className={ui.primaryButton} type="submit">
                        <Save size={14} />
                        {settingsBusy ? "Saving..." : "Save settings"}
                      </button>
                      <button
                        className={ui.button}
                        type="button"
                        onClick={() => modelAction()}
                      >
                        <RefreshCw size={14} />
                        Refresh models
                      </button>
                      <button
                        className={ui.button}
                        type="button"
                        onClick={() => modelAction(true)}
                      >
                        <Layers3 size={14} />
                        Unload model
                      </button>
                    </div>
                    {busy && (
                      <p className={ui.warningNote}>
                        Settings are read-only while a generation job is active.
                        Return to the builder to manage the job.
                      </p>
                    )}
                    <p className={`${ui.subtleNote} wrap-anywhere`}>
                      Scanned folder: {bootstrap.models.root}
                    </p>
                    <p className={ui.subtleNote}>
                      {profiles.length} ready prompt engines found.
                      {configuredBackend &&
                        " Generation uses your configured backend, even without local models."}
                    </p>
                    {bootstrap.models.profiles
                      .filter((item) => !item.vision_ready)
                      .map((item) => (
                        <p className={ui.warningNote} key={item.id}>
                          {item.label}: incomplete model. Add the model GGUF and
                          matching mmproj to the same folder, then refresh
                          models.
                        </p>
                      ))}
                    {bootstrap.models.warnings.map((warning, index) => (
                      <p className={ui.warningNote} key={index}>
                        {warning}
                      </p>
                    ))}
                  </Panel>
                </fieldset>
              </form>
            </>
          ) : (
            <>
              <div className={ui.pageHeading}>
                <div>
                  <div className={ui.eyebrow}>FROM A SPARK TO SOMETHING GREAT</div>
                  <h2>
                    Make your next idea <span>look better.</span>
                  </h2>
                  <p>
                    Your vision, refined. Built for your image and video
                    workflows.
                  </p>
                </div>
                <span className={ui.workspaceTag}>
                  <Layers3 size={14} />
                  Prompt workspace
                </span>
              </div>

              <fieldset disabled={busy}>
                <div className={ui.workspaceGrid}>
                  <div className={ui.column}>
                    <Panel
                      icon={FileText}
                      title="Describe your idea"
                      subtitle="Start with the subject, mood, setting, or a little bit of everything."
                      className={ui.ideaPanel}
                    >
                      <div className="relative">
                        <textarea
                          aria-label="Describe your idea"
                          className={ui.ideaInput}
                          value={settings.idea}
                          onChange={(event) =>
                            update("idea", event.target.value)
                          }
                          placeholder="A cinematic portrait of a wandering samurai in a misty forest at dawn..."
                        />
                        <span className={ui.charCount}>
                          {settings.idea.length.toLocaleString()} characters
                        </span>
                      </div>
                      <div className={ui.inputHint}>
                        <Sparkles size={13} />
                        <span>
                          Start with a rough idea, then choose a task and saved
                          instructions below.
                        </span>
                      </div>
                    </Panel>

                    <Panel
                      icon={SlidersHorizontal}
                      title="Prompt controls"
                      subtitle="Choose how your idea takes shape."
                    >
                      <div className={`${ui.fields} grid-cols-2`}>
                        {field(
                          "mode",
                          "Prompt task",
                          bootstrap.inputs.mode[0].map((value) => ({
                            value,
                            label: taskLabels[value] || value,
                          })),
                        )}
                        {field(
                          "director_preset",
                          "Instruction preset",
                          displayedPresets.map((item) => ({
                            value: item.id,
                            label: presetDisplayLabel(item),
                          })),
                        )}
                      </div>
                      <div className="border-t border-[#ffffff07] pt-[15px]">
                        <p className={ui.subtleNote}>
                          Changing the task selects its matching instruction preset.
                          You can then choose another preset without changing the task.
                        </p>
                        <span className={ui.directorDescription}>
                          {preset?.description === "User Director"
                            ? "User instruction preset"
                            : preset?.description}
                        </span>
                        <button
                          className={ui.textButton}
                          onClick={() => {
                            selectDirector(preset || bootstrap.presets.presets[0]);
                            navigate("directors");
                          }}
                        >
                          Manage instruction presets
                        </button>
                      </div>
                      {field("target_model", "Target model")}


                      <div className={`${ui.fields} ${ui.threeFields} mt-5`}>
                        {field("creativity", "Creativity")}
                        {field(
                          "prompt_length",
                          "Prompt length",
                          ["Short", "Medium", "Detailed", "Maximum Detail"].map(
                            (value) => ({ value, label: value }),
                          ),
                        )}
                        <label className={ui.field}>
                          <span>Prompt engine</span>
                          <span className={ui.selectWrap}>
                            <select
                              className={ui.select}
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
                      <p className={ui.subtleNote}>
                        Maximum Detail uses the largest output budget, not a
                        guaranteed word count. Actual length depends on the
                        model and your instructions.
                      </p>
                      {noEngine && (
                        <p className={ui.warningNote}>
                          No complete local model found.{" "}
                          <button
                            className={ui.textButton}
                            onClick={() => setView("settings")}
                          >
                            Set up models in Settings
                          </button>
                        </p>
                      )}
                    </Panel>

                    <Panel
                      icon={WandSparkles}
                      title="Generated prompt"
                      subtitle="Your next creation starts here. Edit it until it feels right."
                      action={
                        <span
                          className={ui.resultStatus}
                          data-working={active}
                        >
                          <span className={ui.statusDot} />
                          {active ? status : prompt ? "Ready" : "Awaiting idea"}
                        </span>
                      }
                      className={ui.outputPanel}
                    >
                      <div className="relative">
                        <textarea
                          className={ui.outputInput}
                          aria-label="Generated prompt"
                          value={prompt}
                          onChange={(event) =>
                            update("generated_prompt", event.target.value)
                          }
                          placeholder="A little direction. A lot of possibility.\n\nYour generated prompt will appear here."
                          spellCheck={false}
                        />
                        <span className={ui.charCount}>
                          {prompt.length.toLocaleString()} characters
                        </span>
                      </div>
                      <div className={ui.outputActions}>
                        <button
                          className={ui.button}
                          disabled={!prompt}
                          onClick={() => copy(prompt)}
                        >
                          <Copy size={16} />
                          Copy Prompt
                        </button>
                        <button
                          className={ui.saveButton}
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
                          className={ui.button}
                          disabled={!prompt}
                          onClick={() => update("generated_prompt", "")}
                        >
                          <Trash2 size={16} />
                          Clear
                        </button>
                      </div>
                    </Panel>
                  </div>
                  <div className={ui.column}>
                    <Panel
                      icon={ImagePlus}
                      title="Reference images"
                      subtitle="Bring your vision into focus. Up to four images."
                      action={
                        <span className={ui.countChip}>
                          {images.filter(Boolean).length} / 4
                        </span>
                      }
                    >
                      <div className="grid grid-cols-2 gap-[11px]">
                        {images.map((image, index) => (
                          <div
                            className={ui.imageSlot}
                            data-image={!!image}
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
                                  className={ui.imageRemove}
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
                                <div className={ui.imageCaption}>
                                  <span>IMAGE {index + 1}</span>
                                  <span title={image.name}>{image.name}</span>
                                </div>
                              </>
                            ) : (
                              <label className={ui.uploadLabel}>
                                <input
                                  type="file"
                                  aria-label={`Upload image ${index + 1}`}
                                  accept="image/png,image/jpeg,image/webp"
                                  onChange={(event) => {
                                    upload(event.target.files[0], index);
                                    event.target.value = "";
                                  }}
                                />
                                <span className="mb-[3px] text-[#b2a0d6] [&>svg]:inline [&>svg]:align-baseline">
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
                      <p className={ui.subtleNote}>
                        Images are not saved. References need reuploading after
                        reload; unavailable preserve mappings reset to Off.
                      </p>
                    </Panel>
                    <Panel
                      icon={Settings2}
                      title="Keep from reference images"
                      subtitle="Choose which image supplies each attribute to keep."
                    >
                      <div className={ui.referenceMap}>
                        {attributes.map(({ key: attribute, label }) => (
                          <label className={ui.referenceRow} key={attribute}>
                            <span>{label}</span>
                            <span className={ui.selectWrap}>
                              <select
                                className={ui.select}
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
                      <p className={ui.subtleNote}>
                        Off adds no explicit preserve constraint. Blend
                        uses all uploaded images and requires at least two.
                      </p>
                      {!!missingReferences.length && (
                        <p className={ui.warningNote} role="alert">
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
                        className={ui.notesInput}
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

              <div className={ui.generationBar}>
                <button
                  className={ui.generateButton}
                  disabled={
                    !!missingReferences.length ||
                    busy ||
                    !!uploading ||
                    actionBusy ||
                    settingsBusy ||
                    noEngine
                  }
                  onClick={() => generate(false)}
                >
                  {busy ? (
                    <LoaderCircle
                      size={25}
                      className={job?.status === "paused" || job?.status === "cancelling" ? "" : "animate-working"}
                    />
                  ) : (
                    <Sparkles size={25} />
                  )}
                  <span>
                    <strong>
                      {busy
                        ? status === "Pause requested"
                          ? "Finishing current stage"
                          : status
                        : "Generate prompt"}
                    </strong>
                    <small>
                      {busy
                        ? "Your idea is in good hands"
                        : images.some(Boolean)
                          ? "Create a prompt grounded in your references"
                          : "Turn your idea into a refined prompt"}
                    </small>
                  </span>
                </button>
                <button
                  className={ui.endButton}
                  disabled={!active || actionBusy}
                  onClick={endGeneration}
                >
                  <X size={23} />
                  <span>
                    <strong>End generation</strong>
                    <small>
                      {job?.status === "cancelling"
                        ? "Ending the active model request"
                        : "Stop this generation now"}
                    </small>
                  </span>
                </button>
              </div>
              <div className={ui.belowActions}>
                <span>
                  <LockKeyhole size={12} />
                  Settings and saved prompts stay in local JSON files on this
                  server.
                </span>
                <button
                  className={ui.textButton}
                  disabled={
                    busy ||
                    !!uploading ||
                    actionBusy ||
                    settingsBusy ||
                    noEngine ||
                    !settings.idea.trim()
                  }
                  onClick={() => generate(true)}
                >
                  Text-only preview
                  <ArrowUpRight size={13} />
                </button>
                <span className={ui.previewNote}>
                  Ignores reference images and the attributes selected to keep.
                </span>
              </div>
            </>
          )}
        </main>
      </div>

      <dialog
        className={ui.dialog}
        ref={dialogRef}
        onCancel={(event) => {
          if (dialogBusy) event.preventDefault();
          else setSaveKind(null);
        }}
        onClose={() => setSaveKind(null)}
      >
        <form onSubmit={save}>
          <div className="mb-[18px] flex items-center justify-between">
            <div className={ui.panelIcon}>
              <Bookmark size={22} />
            </div>
            <button
              type="button"
              className={ui.iconButton}
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
            <div className={ui.message} role="alert">
              {dialogError}
            </div>
          )}
          <label className={ui.field}>
            <span>Prompt name</span>
            <input
              className={ui.input}
              autoFocus
              required
              maxLength={80}
              disabled={dialogBusy}
              value={saveName}
              onChange={(event) => setSaveName(event.target.value)}
            />
          </label>
          <button
            className={ui.primaryButton}
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
