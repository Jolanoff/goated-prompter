/** JSONL preserves originating idea and scene; TXT/copy remain final-prompt-only. */
export function datasetJsonl(draft) {
  return (draft?.results || []).map((item) => JSON.stringify({
    index: item.index, input: item.input || "", idea: item.idea || null, scene: item.scene || null,
    prompt: item.prompt, trigger: draft.trigger, target: draft.target,
    source: item.input || null,
  })).join("\n");
}
