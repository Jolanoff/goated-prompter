import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { presetDisplayLabel } from "../../presetPresentation.js";

/** Instruction-preset editor: selection, unsaved-draft guard and library writes. */
export function useDirectorEditor({ presets, setBootstrap, busy, actionBusy, setActionBusy, setError, setNotice,
  receiveJob }) {
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
  const editorDirector = presets?.find(
    (item) => item.id === directorId,
  );

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
      const library = await api("/presets");
      setBootstrap((previous) => ({ ...previous, presets: library }));
      const fallback =
        library.presets.find(
          (item) =>
            item.id === library.default || item.label === library.default,
        ) || library.presets[0];
      selectDirector(
        library.presets.find(
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

  return { directorId, directorDraft, setDirectorDraft, directorOriginal, directorDirty, editorDirector,
    selectDirector, discardDirector, writeDirector };
}
