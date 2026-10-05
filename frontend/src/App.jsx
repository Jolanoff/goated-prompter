import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";
import { presetDisplayLabel } from "./presetPresentation.js";
import { ui } from "./ui.js";
import { api } from "./api.js";
import { activeJobStatuses as activeStatuses, useJobPolling } from "./useJobPolling.js";
import { readTheme, saveTheme } from "./theme.js";
import CreativeWorkspace from "./workflows/CreativeWorkspace.jsx";
import MiniMaxTab from "./workflows/MiniMaxTab.jsx";
import DatasetTab from "./workflows/DatasetTab.jsx";
import SavedPromptsTab from "./workflows/SavedPromptsTab.jsx";
import SettingsTab from "./workflows/SettingsTab.jsx";
import DirectorsTab from "./workflows/DirectorsTab.jsx";
import BuilderTab from "./workflows/BuilderTab.jsx";
import ReferenceImages from "./workflows/ReferenceImages.jsx";
import { GoatMark } from "./components/StudioPrimitives.jsx";
import JobLogModal from "./JobLogModal.jsx";
import {
  Bookmark,
  Check,
  Database,
  FileText,
  Film,
  Moon,
  Save,
  ScrollText,
  Settings2,
  SlidersHorizontal,
  Sun,
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
const titleCase = (text) =>
  text.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
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
const workspaceViews = [
  { id: "builder", label: "Prompt Builder", icon: SlidersHorizontal },
  { id: "refine", label: "Refine", icon: WandSparkles },
  { id: "minimax", label: "MiniMax H3", icon: Film },
  { id: "dataset", label: "Dataset", icon: Database },
  { id: "saved", label: "Saved Prompts", icon: Bookmark },
  { id: "directors", label: "Instruction presets", icon: FileText },
  { id: "settings", label: "Settings", icon: Settings2 },
];

function App() {
  const [theme, setTheme] = useState(() => {
    try { return readTheme(window.localStorage); }
    catch { return "dark"; }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { saveTheme(window.localStorage, theme); }
    catch { /* Browser storage is optional. */ }
  }, [theme]);
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
  const [logOpen, setLogOpen] = useState(false);
  const dialogRef = useRef(null);
  const saveNameRef = useRef(null);
  const pendingPromptRef = useRef(null);
  const saveSourceRef = useRef(null);
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
  const sourceAvailable = useCallback((source) => {
    if (!source || source === "Off") return true;
    if (source === "Blend") return imageCount >= 2;
    const slot = Number(source.replace(/\D/g, "")) - 1;
    return slot >= 0 && slot < images.length && !!images[slot];
  }, [imageCount, images]);
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
        if (!next.kind || next.kind === "builder") {
          setSettings((current) => ({ ...current, generated_prompt: next.result.prompt }));
        }
        if (next.result.history_error) setError(next.result.history_error);
        setNotice(next.kind === "refine" ? "Refinement saved as a new version."
          : next.kind === "dataset" ? `${next.result.completed} dataset prompts are ready.`
          : next.kind === "dataset_scenes" ? `${next.result.scene_plan.length} scene ideas are ready to review or generate.`
          : next.kind === "dataset_review" ? `Deep review completed for ${next.result.reviewed} prompts.`
          : "Your prompt is ready. Make it yours.");
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
        if (latestJobRef.current?.status === "succeeded" && (!latestJobRef.current.kind || latestJobRef.current.kind === "builder")) {
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

  const initialConnect = useEffectEvent(connect);
  useEffect(() => {
    initialConnect();
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
  }, [images, hasInvalidReferenceMappings, sourceAvailable]);

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

  useJobPolling(job?.id, active, receiveJob, () => {
    setJob(null);
    latestJobRef.current = null;
    try { sessionStorage.removeItem(JOB_KEY); } catch { /* Optional recovery. */ }
    setError("This job is no longer available. The backend may have restarted; generate again.");
  }, (err) => setError(`Connection interrupted; still checking the current job. ${err.message}`));

  async function releaseJobs(kind) {
    const result = await api(`/jobs?kind=${encodeURIComponent(kind)}`, undefined, "DELETE");
    if (result.released.includes(latestJobRef.current?.id)) {
      latestJobRef.current = null;
      setJob(null);
      setLogOpen(false);
    }
  }

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4500);
    return () => clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (saveKind) {
      dialogRef.current?.showModal();
      saveNameRef.current?.focus();
    }
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

  async function startWorkflow(operation, payload) {
    if (submissionRef.current || busy || uploading || actionBusy || settingsBusy || noEngine) return false;
    submissionRef.current = true;
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      const next = await api(`/workspace/${operation}`, {
        ...payload,
        settings: {
          ...payload.settings,
          director_profile: configuredBackend ? "" : selectedProfile?.id || "",
        },
      });
      receiveJob(next);
      return true;
    } catch (err) {
      if (err.activeJob) receiveJob(err.activeJob);
      else {
        try {
          const data = await api("/bootstrap");
          if (data.active_job) receiveJob(data.active_job);
        } catch { /* Keep the original request error. */ }
      }
      throw err;
    } finally {
      submissionRef.current = false;
      setSubmitting(false);
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
    requestPromptSave(prompt, settings.target_model, settings.idea.trim().split("\n")[0].slice(0, 70) || "Untitled prompt");
  }

  function requestPromptSave(text, target, title) {
    if (!text.trim() || !storageReady || promptsBusy || dialogBusy) return;
    saveSourceRef.current = { prompt: text, target };
    pendingPromptRef.current = null;
    setDialogError("");
    setSaveKind("prompt");
    setSaveName(title.slice(0, 70));
  }

  async function save(event) {
    event.preventDefault();
    if (!saveName.trim() || dialogBusy || !storageReady || promptsBusy) return;
    setDialogBusy(true);
    setDialogError("");
    setError("");
    setNotice("");
    try {
      const source = saveSourceRef.current;
      if (
        pendingPromptRef.current?.title !== saveName.trim() ||
        pendingPromptRef.current?.prompt !== source.prompt ||
        pendingPromptRef.current?.target !== source.target
      )
        pendingPromptRef.current = {
          id: crypto.randomUUID(),
          title: saveName.trim(),
          ...source,
          createdAt: new Date().toISOString(),
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
      <a className="skip-link" href="#workspace-content">Skip to workspace</a>
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
            Goated<span className={ui.brandSub}>Prompter</span>
          </span>
        </a>
        <div className={ui.navCaption}>Workspace</div>
        <nav aria-label="Workspace">
          {workspaceViews.map(({ id, label, icon: Icon }) => (
            <button key={id} className={ui.navItem} data-active={view === id}
              aria-label={label} aria-current={view === id ? "page" : undefined}
              onClick={() => navigate(id)}
              disabled={!bootstrap && !["builder", "saved", "settings"].includes(id)}>
              <Icon size={19} aria-hidden="true" />
              <span className="nav-text">{label}</span>
              {id === "saved" && <span className={ui.navCount} aria-hidden="true">{saved.length}</span>}
            </button>
          ))}
        </nav>
        <div className={ui.sidebarBottom}>
          <div className={ui.localLabel}>
            <span className={ui.statusDot} />
            Your local studio
          </div>
          <p>
            Ideas, prompts, and creative direction. All in one place.
          </p>
        </div>
        <button className={`${ui.navItem} sidebar-log mobile:hidden`} onClick={() => setLogOpen(true)}
          aria-label="View LLM activity log" title="View LLM activity log">
          <ScrollText size={19} aria-hidden="true" /><span className="nav-text">View log</span>
        </button>
      </aside>

      <div className={ui.mainShell}>
        <header className={ui.topbar}>
          <div className={ui.headerTitle}>
            <GoatMark small />
            <div>
              <h1><span>Workspace /</span>{workspaceViews.find((item) => item.id === view)?.label}</h1>
            </div>
          </div>
          <div className="flex items-center gap-3 mobile:gap-2">
            <button className={ui.iconButton} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}>
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
              <button className={`${ui.button} hidden mobile:inline-flex`} onClick={() => setLogOpen(true)} aria-label="View LLM activity log">
                <ScrollText size={14} /><span className="mobile:hidden">View log</span>
              </button>
            <span className={ui.connectionPill} data-offline={!bootstrap}>
              <span className={ui.statusDot} />
              {bootstrap ? "Local backend connected" : "Backend offline"}
            </span>
            <span className={ui.localOnly}>
              <Zap size={14} />
              Local workspace
            </span>
          </div>
        </header>

        <main id="workspace-content" tabIndex={-1} className={ui.main} data-builder={view === "builder"} data-view={view}>
          {bootstrap && (
            <div
              className={ui.builderSave}
              hidden={view !== "builder" && !builderError}
              aria-live="polite"
              aria-label="Builder save status"
            >
              {builderStatus === "Saved" && <Check size={13} className="text-success" aria-hidden="true" />}
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

          {bootstrap && (
            <CreativeWorkspace view={view} job={job} busy={busy || actionBusy || settingsBusy || !!uploading}
              active={active} noEngine={noEngine} builderPrompt={prompt} builderIdea={settings.idea}
              builderTarget={settings.target_model} inputs={bootstrap.inputs}
              onSavePrompt={requestPromptSave} canSavePrompt={storageReady && !promptsBusy && !dialogBusy && !saveKind}
              engineLabel={configuredBackend ? `Configured backend (${bootstrap.backend})` : selectedProfile?.label}
              onGenerate={startWorkflow} onCancel={endGeneration} onCopy={copy}
              onNavigate={navigate} onReceiveJob={receiveJob}
              onUsePrompt={(text, target) => {
                setSettings((current) => ({ ...current, generated_prompt: text, target_model: target }));
                navigate("builder");
              }} />
          )}
          {bootstrap && <MiniMaxTab visible={view === "minimax"} job={job}
            busy={busy || actionBusy || settingsBusy || !!uploading} active={active} noEngine={noEngine}
            engineLabel={configuredBackend ? `Configured backend (${bootstrap.backend})` : selectedProfile?.label}
               presets={bootstrap.presets.presets} onGenerate={startWorkflow} onCancel={endGeneration} onCopy={copy} onReleaseJobs={releaseJobs} />}
          {bootstrap && <DatasetTab visible={view === "dataset"} job={job}
            busy={busy || actionBusy || settingsBusy || !!uploading} active={active} noEngine={noEngine}
            engineLabel={configuredBackend ? `Configured backend (${bootstrap.backend})` : selectedProfile?.label}
            presets={bootstrap.presets.presets} targets={bootstrap.inputs.target_model[0]}
            lengths={bootstrap.inputs.prompt_length[0]} onGenerate={startWorkflow}
             onCancel={endGeneration} onCopy={copy} onReleaseJobs={releaseJobs} />}
          {active && view !== "builder" && view !== "refine" && view !== "minimax" && view !== "dataset" && (
            <div className={`${ui.panel} mb-5 flex flex-wrap items-center justify-between gap-3`} role="status">
              <span>{job.progress || "Generating prompt…"}</span>
              <button className={ui.button} onClick={endGeneration} disabled={actionBusy || job.status === "cancelling"}>End generation</button>
            </div>
          )}

          {view === "refine" || view === "minimax" || view === "dataset" ? null : view === "saved" ? (
            <SavedPromptsTab records={saved} ready={storageReady} busy={busy}
              deletingDisabled={!storageReady || promptsBusy || dialogBusy}
              onBack={() => setView("builder")} onCopy={copy} onDelete={deletePrompt}
              onOpen={(record) => {
                setSettings((current) => ({ ...current, generated_prompt: record.prompt,
                  target_model: record.target || current.target_model }));
                setView("builder");
              }} />
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
            <DirectorsTab library={bootstrap.presets} directorId={directorId}
              draft={directorDraft} dirty={directorDirty} editorDirector={editorDirector}
              busy={busy} actionBusy={actionBusy} onWrite={writeDirector}
              onSelect={(item) => { if (discardDirector()) selectDirector(item); }}
              onChange={(key, value) => setDirectorDraft((draft) => ({ ...draft, [key]: value }))}
              onUse={() => {
                if (discardDirector()) {
                  setDirectorDraft(directorOriginal);
                  update("director_preset", directorId);
                  setView("builder");
                }
              }} />
          ) : view === "settings" ? (
            <SettingsTab backend={bootstrap.backend} models={bootstrap.models}
              draft={settingsDraft} profiles={profiles} configuredBackend={configuredBackend}
              busy={busy} saving={settingsBusy} actionBusy={actionBusy}
              onSave={saveSettings} onModelAction={modelAction} onBack={() => setView("builder")}
              onChange={(key, value) => setSettingsDraft((previous) => ({ ...previous, [key]: value }))} />
          ) : (
            <BuilderTab settings={settings} inputs={bootstrap.inputs} presets={bootstrap.presets.presets}
              preset={preset} engine={{ backend: bootstrap.backend, configuredBackend, selectedProfile, profiles, noEngine }}
              job={job} busy={busy} active={active} status={status} actionBusy={actionBusy}
              settingsBusy={settingsBusy} uploading={uploading} hasImages={hasImages}
              hasMissingReferences={!!missingReferences.length} canSave={storageReady && !promptsBusy && !dialogBusy}
              onChange={update} onCopy={copy} onSave={openSave} onGenerate={generate} onCancel={endGeneration}
              onNavigate={navigate} onSelectEngine={(id) => saveSettings(null, id)}
              onManagePresets={() => {
                selectDirector(preset || bootstrap.presets.presets[0]);
                navigate("directors");
              }}>
              <ReferenceImages images={images} settings={settings} attributes={attributes} sources={sources}
                missingReferences={missingReferences} sourceAvailable={sourceAvailable} onChange={update}
                onUpload={upload} onError={setError}
                onRemove={(index) => setImages((previous) => previous.map((item, slot) => slot === index ? null : item))} />
            </BuilderTab>
          )}
        </main>
      </div>

      <JobLogModal open={logOpen} job={job}
        engineLabel={configuredBackend ? `Configured backend (${bootstrap?.backend})` : selectedProfile?.label}
        onClose={() => setLogOpen(false)} />

      <dialog
        className={ui.dialog}
        aria-labelledby="save-prompt-title"
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
          <h2 id="save-prompt-title">Save your prompt</h2>
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
              ref={saveNameRef}
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
