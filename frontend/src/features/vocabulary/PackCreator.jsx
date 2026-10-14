import { useRef, useState } from "react";
import { FilePlus2, Plus, Save, Upload } from "lucide-react";
import { api } from "../../api.js";
import { ui } from "../../ui.js";
import { EntryDetails, RetrievalResults } from "./VocabularyExplorer.jsx";
import { moveEntry, pathMatches, uniqueEntryId } from "./creatorModel.js";
import SchemaForm from "./SchemaForm.jsx";
import { usePackCreator } from "./usePackCreator.js";

export function CreatorView({ visible, packs, state: c }) {
  const [selection, setSelection] = useState(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState("manifest");
  const [filename, setFilename] = useState("additional.json");
  const [sample, setSample] = useState({ request: "", characters: "", nsfw: false });
  const [testedSample, setTestedSample] = useState("");
  const [reference, setReference] = useState(null);
  const referenceRequest = useRef(0);
  const document = c.document;
  const rows = Object.entries(document.files).flatMap(([file, content]) => (content.entries || []).map((entry, index) => ({ file, index, entry })));
  const selected = rows.find((row) => row.file === selection?.file && row.index === selection?.index);
  const issues = c.validation?.issues || [];
  const categories = [...new Map([...c.references.categories, ...(document.manifest.categories || [])].map((item) => [item.id, item])).values()];
  const localRefs = rows.map(({ entry }) => ({ ...entry, pack: document.manifest.id, rating: entry.rating || document.manifest.rating,
    capability: !!entry.components?.capability, posture: !!entry.components?.spatial?.participants?.self }));
  const refs = [...c.references.entries.filter((entry) => !localRefs.some((local) => local.id === entry.id)), ...localRefs];
  const manifestSchema = c.schemas && { ...c.schemas.manifest, properties: Object.fromEntries(Object.entries(c.schemas.manifest.properties).filter(([key]) => key !== "files")),
    required: c.schemas.manifest.required.filter((key) => key !== "files") };
  const installed = packs.find((pack) => pack.id === document.manifest.id);

  function select(row) { setSelection(row); setPage("entry"); setReference(null); }
  function editEntry(next) {
    const copy = structuredClone(document); copy.files[selected.file].entries[selected.index] = next; c.change(copy);
  }
  function addEntry() {
    const file = Object.keys(document.files)[0]; if (!file) return;
    const copy = structuredClone(document);
    const index = copy.files[file].entries.length;
    copy.files[file].entries.push({ id: uniqueEntryId(document), category: categories[0]?.id || "capability", name: "New entry", components: {} });
    c.change(copy); select({ file, index });
  }
  function duplicate() {
    const copy = structuredClone(document), entry = structuredClone(selected.entry);
    entry.id = uniqueEntryId(document, `${entry.id}_copy`); entry.name = `${entry.name} copy`.slice(0, 120);
    const index = copy.files[selected.file].entries.length;
    copy.files[selected.file].entries.push(entry); c.change(copy); select({ file: selected.file, index });
  }
  function removeEntry() {
    c.confirm(`Remove ${selected.entry.name || selected.entry.id} from this draft?`, () => {
      const copy = structuredClone(document); copy.files[selected.file].entries.splice(selected.index, 1);
      c.change(copy); setSelection(null); setPage("manifest");
    });
  }
  function addFile() {
    if (!filename || !new RegExp(c.schemas.manifest.properties.files.items.pattern).test(filename) || Object.hasOwn(document.files, filename) || filename === "manifest.json") return;
    c.change({ ...document, manifest: { ...document.manifest, files: [...(document.manifest.files || Object.keys(document.files)), filename] },
      files: { ...document.files, [filename]: { spec: 1, entries: [] } } }); setFilename("");
  }
  function removeFile(name) {
    c.confirm(`Remove ${name} and its ${document.files[name].entries.length} entries from the draft?`, () => {
      c.change({ ...document, manifest: { ...document.manifest, files: (document.manifest.files || Object.keys(document.files)).filter((file) => file !== name) },
        files: Object.fromEntries(Object.entries(document.files).filter(([file]) => file !== name)) }); setSelection(null);
    });
  }
  function jump(issue) {
    const [, file, , index] = issue.path;
    if (issue.path[0] === "files" && Number.isInteger(index)) select({ file, index }); else setPage("manifest");
  }
  async function openReference(target) {
    const local = rows.find((row) => row.entry.id === target.id);
    if (local) { select(local); return; }
    const sequence = ++referenceRequest.current; setReference({ loading: true });
    try {
      const detail = await api(`/vocabulary/entries/${encodeURIComponent(target.id)}${target.origin ? `?origin=${target.origin}` : ""}`);
      if (sequence === referenceRequest.current) setReference({ detail });
    } catch (error) { if (sequence === referenceRequest.current) setReference({ error: error.message }); }
  }
  return <section className="vocabulary-creator" hidden={!visible} aria-label="Visual pack creator">
    <header className="creator-intro"><div><h3>Create a vocabulary pack</h3><p>Build definitions visually. Validate against real vocabulary rules. Install only when you choose.</p></div>
      <span className="creator-save-state" role="status">{c.readOnly ? "Read-only bundled pack" : c.dirty ? "Unsaved changes" : c.saved ? "Draft saved" : "New pack"}</span></header>
    {c.loading && <p role="status">Loading creator schemas and references…</p>}
    {c.error && <div className={ui.message} role="alert"><span>{c.error}</span><button className={ui.button} onClick={c.reload}>Reload creator</button></div>}
    {c.notice && <p className="vocabulary-notice" role="status">{c.notice}</p>}
    {c.pending && <div className="creator-confirm" role="alertdialog" aria-label="Confirm creator action"><p>{c.pending.label}</p>
      <button className={ui.dangerButton} onClick={c.accept}>Confirm</button><button className={ui.button} onClick={c.cancel}>Cancel</button></div>}
    <fieldset disabled={c.busy || c.loading} className="creator-controls">
      <div className="creator-toolbar"><button className={ui.button} onClick={c.startNew}><FilePlus2 size={15} />New pack</button>
        <label className="creator-import"><Upload size={15} />Import ZIP<input type="file" accept=".zip,application/zip" aria-label="Import creator ZIP"
          onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) c.importZIP(file); }} /></label>
        <label className={ui.field}><span>Reopen a draft</span><select className={ui.select} aria-label="Reopen draft" value="" onChange={(event) => {
          if (event.target.value) c.openDraft(event.target.value); }}><option value="">Choose saved draft…</option>
          {c.drafts.map((draft) => <option key={draft.id} value={draft.id} disabled={!!draft.error}>{draft.name} {draft.pack_id ? `(${draft.pack_id})` : ""}</option>)}</select></label>
        <label className={ui.field}><span>Open an existing pack</span><select className={ui.select} aria-label="Open pack in creator" value="" onChange={(event) => {
          const pack = packs.find((item) => `${item.origin}:${item.id}` === event.target.value); if (pack) c.openPack(pack); }}><option value="">Choose pack…</option>
          {packs.map((pack) => <option key={`${pack.origin}:${pack.id}`} value={`${pack.origin}:${pack.id}`}>{pack.name || pack.id}{pack.bundled ? " (read-only)" : ""}</option>)}</select></label>
      </div>
      {c.schemas && <><div className="creator-workspace"><aside className="creator-rail" aria-label="Draft navigation">
        <button className={ui.button} aria-pressed={page === "manifest"} onClick={() => { setPage("manifest"); setReference(null); }}>Pack details & files</button>
        <div className="creator-entry-heading"><h4>Entries <small>{rows.length}</small></h4><button className={ui.button} disabled={c.readOnly || !Object.keys(document.files).length} onClick={addEntry}><Plus size={14} />Add entry</button></div>
        <input className={ui.input} aria-label="Search draft entries" placeholder="Search names, IDs or categories" value={search} onChange={(event) => setSearch(event.target.value)} />
        <ul>{rows.filter(({ entry }) => [entry.id, entry.name, entry.category].some((value) => String(value).toLowerCase().includes(search.toLowerCase()))).map((row) =>
          <li key={`${row.file}:${row.index}`}><button className="vocabulary-entry-choice" aria-pressed={page === "entry" && selected === row} onClick={() => select(row)}>
            <span><strong>{row.entry.name || "Unnamed entry"}</strong><small>{row.entry.id}</small><small>{row.entry.category} · {row.file}</small></span>
            {issues.some((issue) => pathMatches(issue, ["files", row.file, "entries", row.index])) && <span className="creator-field-error">!</span>}</button></li>)}
        </ul>{!rows.length && <p className="creator-help">Add your first entry. No vocabulary is installed until you explicitly install the finished pack.</p>}
      </aside>
      <div className="creator-editor"><fieldset disabled={c.readOnly} className="creator-controls">
        {c.readOnly && <p className="vocabulary-guidance">Bundled definitions are read-only. New packs can reference and inherit them without changing their files.</p>}
        {page === "manifest" ? <>
          <h3>Pack details</h3><SchemaForm schema={manifestSchema} root={c.schemas.manifest} value={Object.fromEntries(Object.entries(document.manifest).filter(([key]) => key !== "files"))} title="Manifest" path={["manifest"]}
            onChange={(manifest) => c.change({ ...document, manifest: { ...manifest, files: document.manifest.files } })} issues={issues} packs={packs} references={refs} categories={categories} />
          <section className="creator-files"><h4>Entry files</h4><p className="creator-help">Entries can be organized into several plain JSON files. Use the entry’s file selector to move it.</p>
            <ul>{Object.keys(document.files).map((file) => <li key={file}><span>{file} ({document.files[file].entries.length} entries)</span><button className={ui.textButton}
              disabled={Object.keys(document.files).length === 1} onClick={() => removeFile(file)}>Remove {file}</button></li>)}</ul>
            <label className={ui.field}><span>New entry filename</span><input className={ui.input} aria-label="New entry filename" value={filename} onChange={(event) => setFilename(event.target.value)} /></label>
            <button className={ui.button} onClick={addFile} disabled={!filename || Object.hasOwn(document.files, filename) || filename === "manifest.json" || !new RegExp(c.schemas.manifest.properties.files.items.pattern).test(filename)}>Add entry file</button>
          </section>
        </> : selected ? <><header className="creator-entry-header"><h3>{selected.entry.name || "Entry details"}</h3><div>
          <button className={ui.button} onClick={duplicate}>Duplicate entry</button><button className={ui.textButton} onClick={removeEntry}>Remove entry</button></div></header>
          <label className={ui.field}><span>Entry file</span><select className={ui.select} aria-label="Entry file" value={selected.file} onChange={(event) => {
            const file = event.target.value, index = document.files[file].entries.length; c.change(moveEntry(document, selected.file, selected.index, file)); select({ file, index });
          }}>{Object.keys(document.files).map((file) => <option key={file} value={file}>{file}</option>)}</select></label>
          {rows.filter((row) => row.entry.id === selected.entry.id).length > 1 && <p className="creator-field-error" role="alert">Duplicate entry ID. Choose a unique ID before validation or export.</p>}
          <SchemaForm schema={c.schemas.entry.$defs.entry} root={c.schemas.entry} value={selected.entry} title="Entry" path={["files", selected.file, "entries", selected.index]}
            onChange={editEntry} issues={issues} references={refs} packs={packs} categories={categories} />
        </> : <p>Select an entry or add a new one.</p>}
      </fieldset></div></div>
      <section className="creator-validation" aria-label="Draft validation"><div className="creator-action-row">
        <button className={ui.primaryButton} disabled={c.readOnly} onClick={c.save}><Save size={15} />Save draft</button>
        <button className={ui.button} disabled={c.readOnly} onClick={c.validate}>Validate pack</button>
        <button className={ui.button} disabled={c.readOnly} onClick={c.exportZIP}>Export ZIP</button>
        <button className={ui.button} disabled={c.readOnly || !!installed?.bundled} onClick={() => c.install(installed?.origin === "installed" ? installed.id : null)}>
          {installed?.origin === "installed" ? "Update installed pack" : "Install completed pack"}</button>
      </div><p className="creator-help">Drafts may be incomplete. Export, preview and installation require a valid pack. Dependencies are resolved in isolation, including disabled packs; installation still enforces normal enabled-pack rules.</p>
        {c.validation && <><h4>{c.validation.valid ? "Pack is valid" : `${issues.length} validation issues`}</h4>
          <ul className="creator-issues">{issues.map((issue, index) => <li key={index}><button className={ui.textButton} onClick={() => jump(issue)}>{issue.path.map(String).join(" / ") || "Pack"}</button><p>{issue.message}</p></li>)}</ul></>}
      </section>
      <section className="vocabulary-retrieval" aria-label="Draft retrieval inspection"><h3>Test draft retrieval</h3><p>Uses the Explorer’s deterministic inspector with this draft and its dependencies. No installation, LLM or scene generation.</p>
        <label className={ui.field}><span>Sample request</span><textarea className="control textarea" aria-label="Draft sample request" maxLength={4000} rows={3} value={sample.request} onChange={(event) => setSample({ ...sample, request: event.target.value })} /></label>
        <details><summary>Optional character descriptions</summary><label className={ui.field}><span>One character per line</span><textarea className="control textarea" aria-label="Draft inspection characters" rows={2} value={sample.characters} onChange={(event) => setSample({ ...sample, characters: event.target.value })} /></label></details>
        <div className="creator-action-row"><label className={ui.toggleRow}><input type="checkbox" className={ui.toggleInput} role="switch" aria-label="Allow Adult rating in draft preview" checked={sample.nsfw} onChange={(event) => setSample({ ...sample, nsfw: event.target.checked })} /><span className={ui.switch} /><span className={ui.toggleLabel}>Allow Adult rating</span></label>
          <button className={ui.button} disabled={c.readOnly || !sample.request.trim()} onClick={() => { setTestedSample(JSON.stringify(sample)); c.preview({ ...sample, characters: sample.characters.split("\n").map((line) => line.trim()).filter(Boolean) }); }}>Inspect draft retrieval</button></div>
        <p className="creator-help">This rating filter is not Dataset content approval. The normal SFW/NSFW eligibility rules are unchanged. A valid definition is not necessarily a retrieved scene candidate.</p>
        {c.validation?.retrieval && testedSample === JSON.stringify(sample) && <RetrievalResults result={c.validation.retrieval} onNavigate={openReference} packs={[...packs, { id: document.manifest.id, valid: true, origin: "draft" }]} />}
        {reference && <div className="vocabulary-detail-panel">{reference.loading ? <p role="status">Loading reference…</p> : reference.error ? <p role="alert">{reference.error}</p> : <EntryDetails detail={reference.detail} onNavigate={openReference} onBack={() => setReference(null)} />}</div>}
      </section>
      <details className="creator-advanced"><summary>Advanced JSON view</summary><p className="creator-help">The exact draft document. All schema-supported fields can be edited visually above.</p>
        <textarea className="control textarea" aria-label="Advanced draft JSON" readOnly value={JSON.stringify(document, null, 2)} rows={16} /></details>
      </>}
    </fieldset>
    <p className="vocabulary-footer">AI-assisted pack authoring remains available through <code>vocabulary/SKILL.md</code>. Import the resulting ZIP here to inspect and edit it.</p>
  </section>;
}

export default function PackCreator({ visible, packs, onInstalled }) {
  const state = usePackCreator(visible, onInstalled);
  return <CreatorView key={state.edition} visible={visible} packs={packs} state={state} />;
}
