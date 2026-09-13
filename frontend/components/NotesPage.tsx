"use client";

import { ArrowsInSimple, ArrowsOutSimple, CheckCircle, FileText, MagnifyingGlass, Plus, Trash } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Note, type NoteDraft } from "@/lib/api";

const emptyDraft: NoteDraft = { title: "", description: "", script: "" };

export default function NotesPage({ active, onCount }: { active: boolean; onCount: (count: number) => void }) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.getNotes();
      setNotes(result.items);
      onCount(result.count);
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load notes."); }
    finally { setLoading(false); }
  }, [onCount]);
  useEffect(() => { void load(); }, [load]); // This page stays mounted to retain unsaved drafts across tabs.

  const mutate = async (action: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try { await action(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save changes."); throw cause; }
    finally { lock.current = false; setBusy(false); }
  };
  const replace = (saved: Note) => setNotes((current) => current.map((note) => note.id === saved.id ? saved : note));
  const done = notes.filter((note) => note.done).length;
  const needle = search.trim().toLocaleLowerCase();
  const visible = notes.filter((note) => (filter === "all" || note.done === (filter === "done")) &&
    (!needle || [note.title, note.description, note.script].some((text) => text.toLocaleLowerCase().includes(needle))));

  return <div hidden={!active}>
    <div className="view-stack results-view notes-view">
      <div className="page-heading"><div><span className="eyebrow"><FileText size={15} weight="fill" /> Your own words</span><h1>Notes</h1><p className="page-lede">A place for your ideas and scripts.</p></div><div className="notes-heading-actions"><span className="results-total" aria-live="polite">{loading ? "Loading notes…" : `${notes.length} ${notes.length === 1 ? "note" : "notes"}`}</span><button className="button button-primary" disabled={adding || loading} onClick={() => setAdding(true)}><Plus size={16} /> Add note</button></div></div>
      {error && <div className="panel notes-error" role="alert">{error} <button className="button button-secondary button-small" disabled={busy || loading} onClick={() => void load()}>Retry loading</button></div>}
      <section className="results-filters panel" aria-label="Filter notes">
        <label className="results-search"><MagnifyingGlass size={18} /><input aria-label="Search notes" placeholder="Search titles, descriptions, or scripts…" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        <div className="results-filter-summary"><div className="stage-tabs" aria-label="Note status">{[["all", "All", notes.length], ["pending", "Not done yet", notes.length - done], ["done", "Done", done]].map(([key, label, count]) => <button key={key} className={`stage-tab ${filter === key ? "is-active" : ""}`} aria-pressed={filter === key} onClick={() => setFilter(String(key))}>{label} <span>{count}</span></button>)}</div><span role="status">{loading ? "Loading…" : `${visible.length} of ${notes.length} notes`}</span></div>
      </section>
      <div className="results-grid">
        {adding && <article className="result-card panel"><h2 className="result-title">New note</h2><NoteForm initial={emptyDraft} busy={busy} onCancel={() => setAdding(false)} onSave={async (draft) => mutate(async () => {
          const saved = await api.createNote(draft);
          setNotes((current) => [saved, ...current]);
          onCount(notes.length + 1);
          setAdding(false); setFilter("all"); setSearch("");
        })} /></article>}
        {visible.map((note) => <NoteCard key={note.id} note={note} busy={busy || loading} onSave={(draft) => mutate(async () => replace(await api.updateNote(note.id, draft)))} onToggle={() => mutate(async () => replace(await api.updateNote(note.id, { done: !note.done })))} onDelete={() => mutate(async () => {
          await api.deleteNote(note.id);
          setNotes((current) => current.filter((item) => item.id !== note.id));
          onCount(notes.length - 1);
        })} />)}
      </div>
      {!loading && !visible.length && !adding && <div className="results-empty panel"><FileText size={32} /><h2>{notes.length ? "No matching notes" : "Your next script starts here"}</h2><p>{notes.length ? "Choose another status or clear your search." : "Add a note and write your title, description, and script."}</p></div>}
    </div>
  </div>;
}

function NoteForm({ initial, busy, onCancel, onSave }: { initial: NoteDraft; busy: boolean; onCancel: () => void; onSave: (draft: NoteDraft) => Promise<void> }) {
  const [draft, setDraft] = useState(initial);
  return <form className="note-form" onSubmit={(event) => { event.preventDefault(); void onSave({ ...draft, title: draft.title.trim() }).catch(() => {}); }}>
    <label>Title<input autoFocus dir="auto" required maxLength={240} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} placeholder="Give your note a title" disabled={busy} /></label>
    <label>Description<textarea dir="auto" rows={3} maxLength={20000} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} placeholder="What is this idea about?" disabled={busy} /></label>
    <label>Script<textarea dir="auto" rows={10} maxLength={200000} value={draft.script} onChange={(event) => setDraft({ ...draft, script: event.target.value })} placeholder="Write your script here…" disabled={busy} /></label>
    <div className="note-actions"><button className="button button-primary" type="submit" disabled={busy || !draft.title.trim()}>{busy ? "Saving…" : "Save note"}</button><button className="button button-secondary" type="button" disabled={busy} onClick={onCancel}>Cancel</button></div>
  </form>;
}

function NoteCard({ note, busy, onSave, onToggle, onDelete }: { note: Note; busy: boolean; onSave: (draft: NoteDraft) => Promise<void>; onToggle: () => Promise<void>; onDelete: () => Promise<void> }) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  return <article className={`result-card panel note-card ${expanded || editing ? "is-expanded" : "is-compact"}`} aria-label={note.title}>
    <div className="result-card-top"><span className={note.done ? "result-ready" : "note-pending"}><CheckCircle size={14} weight={note.done ? "fill" : "regular"} /> {note.done ? "Done" : "Not done yet"}</span><button className="result-delete icon-button" aria-label={`Delete ${note.title}`} disabled={busy} onClick={() => { if (window.confirm(`Delete “${note.title}” permanently?`)) void onDelete().catch(() => {}); }}><Trash size={18} /></button></div>
    {editing ? <NoteForm initial={{ title: note.title, description: note.description, script: note.script }} busy={busy} onCancel={() => setEditing(false)} onSave={async (draft) => { await onSave(draft); setEditing(false); }} /> : <>
      <h2 className="result-title" dir="auto">{note.title}</h2>
      <p className="note-description" dir="auto">{note.description || "No description yet."}</p>
      <section className="result-transcript" id={`note-script-${note.id}`}><div className="result-transcript-heading"><h3>Script</h3></div><div className="result-transcript-body" style={{ height: expanded ? "auto" : 88 }}><p className="result-transcript-text" dir="auto">{note.script || "Your script is waiting to be written."}</p></div></section>
      <button className="button result-expand" aria-expanded={expanded} aria-controls={`note-script-${note.id}`} onClick={() => setExpanded(!expanded)}>{expanded ? <ArrowsInSimple size={17} /> : <ArrowsOutSimple size={17} />}{expanded ? "Compact card" : "Expand card"}<span>{expanded ? "Less" : "Full script"}</span></button>
      <footer className="result-footer note-actions"><button className="button button-secondary button-small" disabled={busy} onClick={() => setEditing(true)}>Edit note</button><button className="button button-secondary button-small" aria-pressed={note.done} disabled={busy} onClick={() => void onToggle().catch(() => {})}><CheckCircle size={16} /> {note.done ? "Mark not done" : "Mark done"}</button></footer>
    </>}
  </article>;
}
