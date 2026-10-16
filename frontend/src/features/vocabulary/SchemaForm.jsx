import { useId, useState } from "react";
import { ui } from "../../ui.js";
import { fieldLabel, pathMatches, replaceKey, resolveSchema, schemaDefault, variantIndex } from "./creatorModel.js";

function KeyEditor({ name, onRename, disabled }) {
  const [text, setText] = useState(name);
  return <input className={ui.input} aria-label={`Rename ${name}`} value={text} disabled={disabled}
    onChange={(event) => setText(event.target.value)} onBlur={() => { onRename(text); setText(name === text ? text : name); }} />;
}

export default function SchemaForm({ schema: source, root, value, onChange, path = [], title = "", issues = [], references = [], packs = [], categories = [], depth = 0 }) {
  const id = useId();
  const [newKey, setNewKey] = useState("");
  const schema = resolveSchema(source, root);
  const errors = issues.filter((issue) => pathMatches(issue, path) && issue.path.length === path.length);
  const children = (child, item, change, key, childTitle) => <SchemaForm key={String(key)} schema={child} root={root} value={item}
    onChange={change} path={[...path, key]} title={childTitle} issues={issues} references={references} packs={packs} categories={categories} depth={depth + 1} />;
  const feedback = <>{schema.description && <p className="creator-help">{schema.description}</p>}{errors.map((error, index) =>
    <p className="creator-field-error" role="alert" key={index}>{error.message}</p>)}</>;
  if (schema.const !== undefined) return <div className="creator-constant"><span>{title}</span><span>{String(schema.const)} (schema version)</span>{feedback}</div>;
  if (schema.oneOf) {
    const index = variantIndex(schema, value, root);
    return <fieldset className="creator-group"><legend>{title}</legend><label className={ui.field}><span>Value format</span>
      <select className={ui.select} aria-label={`${title} format`} value={index} onChange={(event) => onChange(schemaDefault(schema.oneOf[Number(event.target.value)], root))}>
        {schema.oneOf.map((part, number) => { const option = resolveSchema(part, root); return <option key={number} value={number}>
          {option.type === "object" ? (option.required || ["Object"]).map(fieldLabel).join(" / ") : option.type === "array" ? "Multiple values" : option.type === "integer" ? "Exact count" : "Single value"}</option>; })}
      </select></label>{feedback}{<SchemaForm schema={schema.oneOf[index]} root={root} value={value} onChange={onChange} path={path} title={title}
        issues={issues} references={references} packs={packs} categories={categories} depth={depth + 1} />}</fieldset>;
  }
  if (schema.type === "object") {
    const object = value && typeof value === "object" && !Array.isArray(value) ? value : {};
    const properties = schema.properties || {};
    const missing = Object.keys(properties).filter((key) => !Object.hasOwn(object, key));
    const dictionary = typeof schema.additionalProperties === "object";
    const names = path.at(-1) === "requires" ? packs.map((pack) => ({ id: pack.id, name: `${pack.name || pack.id} ${pack.version || ""}` })) : [];
    return <fieldset className={`creator-group creator-depth-${Math.min(depth, 3)}`}><legend>{title}</legend>{feedback}
      {Object.entries(object).map(([key, item]) => <div className="creator-property" key={key}>
        <div className="creator-property-heading">{dictionary && <KeyEditor key={key} name={key} onRename={(name) => onChange(replaceKey(object, key, name))} />}
          {!schema.required?.includes(key) && <button type="button" className={ui.textButton} aria-label={`Remove ${title} ${key}`} onClick={() =>
            onChange(Object.fromEntries(Object.entries(object).filter(([name]) => name !== key)))}>Remove {fieldLabel(key)}</button>}</div>
        {children(properties[key] || schema.additionalProperties || {}, item, (next) => onChange({ ...object, [key]: next }), key, fieldLabel(key))}
      </div>)}
      {!!missing.length && <label className={ui.field}><span>Add {title.toLowerCase()} field</span><select className={ui.select} aria-label={`Add ${title} field`} value=""
        onChange={(event) => { const key = event.target.value; if (key) onChange({ ...object, [key]: schemaDefault(properties[key], root) }); }}>
        <option value="">Choose a field…</option>{missing.map((key) => <option key={key} value={key}>{fieldLabel(key)}{schema.required?.includes(key) ? " (required)" : ""}</option>)}
      </select></label>}
      {dictionary && <div className="creator-dictionary-add"><label className={ui.field}><span>New {title.toLowerCase()} key</span>
        <input className={ui.input} aria-label={`New ${title} key`} value={newKey} list={`${id}-keys`} onChange={(event) => setNewKey(event.target.value)} />
        <datalist id={`${id}-keys`}>{names.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</datalist></label>
        <button type="button" className={ui.button} disabled={!newKey || Object.hasOwn(object, newKey)} onClick={() => {
          onChange({ ...object, [newKey]: path.at(-1) === "requires" ? `>=${packs.find((pack) => pack.id === newKey)?.version || "1.0.0"}` : schemaDefault(schema.additionalProperties, root) }); setNewKey("");
        }}>Add {title.toLowerCase()} key</button></div>}
    </fieldset>;
  }
  if (schema.type === "array") {
    const list = Array.isArray(value) ? value : [];
    return <fieldset className="creator-group"><legend>{title}</legend>{feedback}
      {!list.length && <p className="creator-help">No values yet.</p>}
      {list.map((item, index) => <div className="creator-repeat" key={index}>{children(schema.items, item, (next) =>
        onChange(list.map((previous, number) => number === index ? next : previous)), index, `${title} ${index + 1}`)}
        <button type="button" className={ui.textButton} aria-label={`Remove ${title} ${index + 1}`} onClick={() => onChange(list.filter((_, number) => number !== index))}>Remove</button>
      </div>)}
      <button type="button" className={ui.button} disabled={schema.maxItems !== undefined && list.length >= schema.maxItems}
        onClick={() => onChange([...list, schemaDefault(schema.items, root)])}>Add {title.toLowerCase()}</button>
    </fieldset>;
  }
  if (schema.type === "boolean") return <div className={ui.field}>
    <label className={ui.toggleRow}><input id={id} type="checkbox" className={ui.toggleInput} role="switch" aria-label={title}
      aria-invalid={errors.length ? true : undefined} checked={value === true} onChange={(event) => onChange(event.target.checked)} />
      <span className={ui.switch} /><span className={ui.toggleLabel}>{title}</span></label>{feedback}</div>;
  const isReference = source.$ref === "#/$defs/entryId" && path.at(-1) !== "id";
  const referenceKind = path.includes("extends") ? "all" : path.at(-1) === "posture" ? "posture" : "capability";
  const choices = isReference ? references.filter((entry) => referenceKind === "all" || entry[referenceKind]) : path.at(-1) === "category" ? categories.map((category) => ({ ...category, id: category.id })) : [];
  const inputProps = { id, className: ui.input, value: value ?? "", "aria-label": title, "aria-invalid": errors.length ? true : undefined,
    onChange: (event) => onChange(schema.type === "integer" ? (event.target.value === "" ? "" : Number(event.target.value)) : event.target.value),
    maxLength: schema.maxLength, minLength: schema.minLength };
  return <div className={ui.field}><label htmlFor={id}>{title}</label>
    {schema.enum ? <select {...inputProps} className={ui.select}>{schema.enum.map((option) => <option value={option} key={option}>{fieldLabel(option)}</option>)}</select>
      : /description|notes/i.test(title) ? <textarea {...inputProps} className="control textarea" rows={3} />
        : <input {...inputProps} type={schema.type === "integer" ? "number" : "text"} min={schema.minimum} max={schema.maximum} step={schema.type === "integer" ? 1 : undefined}
          list={choices.length ? `${id}-choices` : undefined} />}
    {!!choices.length && <datalist id={`${id}-choices`}>{choices.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}{entry.pack ? ` — ${entry.pack} (${entry.rating})` : ""}</option>)}</datalist>}
    {isReference && <small className="creator-help">Type to search {referenceKind === "all" ? "entries" : referenceKind === "posture" ? "postures" : "capabilities"}. Cross-pack references need a declared dependency.</small>}
    {feedback}
  </div>;
}
