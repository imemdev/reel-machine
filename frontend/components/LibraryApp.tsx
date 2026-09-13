"use client";

import {
  ArrowClockwise,
  ArrowLeft,
  ArrowRight,
  CaretDown,
  CaretRight,
  Check,
  CheckCircle,
  CircleNotch,
  Clock,
  CloudArrowUp,
  CopySimple,
  DownloadSimple,
  DotsThree,
  FileArrowDown,
  FileText,
  FunnelSimple,
  GearSix,
  HardDrives,
  Info,
  Lightning,
  LockSimple,
  MagnifyingGlass,
  Moon,
  Palette,
  Play,
  Plus,
  Pulse,
  ShieldCheck,
  Sparkle,
  SquaresFour,
  Stack,
  Sun,
  Tag,
  TextT,
  Trash,
  Waveform,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from "react";
import {
  api,
  API_BASE,
  ApiError,
  exportUrl,
  type Activity as ActivityItem,
  type Config,
  type Counts,
  type JobAction,
  type ModelOption,
  type Preview,
  type Run,
  type Segment,
  type Stage,
  type StageAction,
  type Video,
} from "@/lib/api";

type View = "dashboard" | "library" | "settings";
type Theme = "light" | "paper" | "slate" | "dark";
type NoticeKind = "info" | "success" | "warning" | "error";
type IconComponent = ComponentType<any>;

const ZERO_COUNTS: Counts = {
  total: 0,
  inbox: 0,
  processing: 0,
  processed: 0,
  error: 0,
  done: 0,
  complete: 0,
};

const FALLBACK_MODELS: ModelOption[] = [
  {
    key: "farukstt",
    label: "FarukSTT",
    description: "Tunisian Derja fine-tune for Arabic + French + English code-switching.",
    source: "medyas/FarukSTT",
    available: false,
    availability_note: "Connect the local API to read runtime readiness.",
  },
  {
    key: "whisper_large_v3",
    label: "Whisper Large-v3 (Full)",
    description: "OpenAI's full multilingual baseline; heavier, with no quantization fallback.",
    source: "ggml-large-v3.bin",
    available: false,
    availability_note: "Connect the local API to read runtime readiness.",
  },
];

const STAGE_LABELS: Record<Stage, string> = {
  inbox: "Inbox",
  processing: "Processing",
  processed: "Processed",
  error: "Error",
  done: "Done",
  complete: "Complete",
};

const PIPELINE_STEPS = [
  ["inspect", "Inspect"],
  ["download", "Download"],
  ["prepare_audio", "Prepare audio"],
  ["check_language", "Language check"],
  ["transcribe", "Transcribe"],
  ["format", "Format"],
  ["publish", "Publish"],
] as const;

const NAV_ITEMS: { key: View; label: string; icon: IconComponent }[] = [
  { key: "dashboard", label: "Dashboard", icon: SquaresFour },
  { key: "library", label: "Library", icon: Stack },
  { key: "settings", label: "Settings", icon: GearSix },
];

const THEME_OPTIONS: { key: Theme; label: string; icon: IconComponent }[] = [
  { key: "light", label: "Light", icon: Sun },
  { key: "paper", label: "Warm Paper", icon: Palette },
  { key: "slate", label: "Slate", icon: Waveform },
  { key: "dark", label: "Dark", icon: Moon },
];

function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Check the local API and try again.";
}

function formatDuration(ms: number | null) {
  if (ms === null || !Number.isFinite(ms)) return "—";
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function formatEditorTime(ms: number) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const millis = Math.max(0, Math.round(ms % 1000));
  return `${minutes}:${seconds.toString().padStart(2, "0")}.${millis.toString().padStart(3, "0")}`;
}

function formatDate(value: string | null | undefined, withTime = true) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: withTime ? "numeric" : undefined,
    minute: withTime ? "2-digit" : undefined,
  }).format(date);
}

function platformLabel(platform: string) {
  if (platform === "instagram") return "Instagram";
  if (platform === "facebook") return "Facebook";
  if (platform === "tiktok") return "TikTok";
  if (platform === "fixture") return "Local fixture";
  return platform;
}

function stageLabel(stage: Stage) {
  return STAGE_LABELS[stage] ?? stage;
}

function actionLabel(action: JobAction) {
  if (action === "retry") return "Retry";
  if (action === "reprocess") return "Reprocess";
  return "Process";
}

function stepLabel(step: string | null) {
  return PIPELINE_STEPS.find(([key]) => key === step)?.[1] ?? (step || "Waiting");
}

function replaceItem(items: Video[], item: Video) {
  const exists = items.some((entry) => entry.id === item.id);
  if (!exists) return [item, ...items];
  return items.map((entry) => (entry.id === item.id ? item : entry));
}

function tagNames(videos: Video[]) {
  return Array.from(new Set(videos.flatMap((video) => video.tags))).sort((a, b) => a.localeCompare(b));
}

export default function LibraryApp() {
  const reducedMotion = useReducedMotion() ?? false;
  const [activeView, setActiveView] = useState<View>("dashboard");
  const [theme, setTheme] = useState<Theme>("light");
  const [config, setConfig] = useState<Config | null>(null);
  const [videos, setVideos] = useState<Video[]>([]);
  const [counts, setCounts] = useState<Counts>(ZERO_COUNTS);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [search, setSearch] = useState("");
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Video | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: NoticeKind; message: string } | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [modelDialog, setModelDialog] = useState<{
    ids: string[];
    action: JobAction;
    hasManualEdits: boolean;
  } | null>(null);
  const [jobBusy, setJobBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showNotice = useCallback((message: string, kind: NoticeKind = "info") => {
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    setNotice({ message, kind });
    noticeTimer.current = setTimeout(() => setNotice(null), 5200);
  }, []);

  useEffect(() => {
    const savedTheme = window.localStorage.getItem("kite-theme") as Theme | null;
    if (savedTheme && THEME_OPTIONS.some((option) => option.key === savedTheme)) setTheme(savedTheme);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("kite-theme", theme);
  }, [theme]);

  const refresh = useCallback(async () => {
    try {
      const [dashboard, list] = await Promise.all([api.getDashboard(), api.getVideos()]);
      setCounts(dashboard.counts);
      setActivities(dashboard.recent_activity);
      setVideos(list.items);
      setApiError(null);
      if (selectedVideoId) {
        try {
          const selected = await api.getVideo(selectedVideoId);
          setDetail(selected);
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            setSelectedVideoId(null);
            setDetail(null);
          }
        }
      }
    } catch (error) {
      setApiError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [selectedVideoId]);

  useEffect(() => {
    let mounted = true;
    api.getConfig()
      .then((value) => {
        if (mounted) setConfig(value);
      })
      .catch((error) => {
        if (mounted) setApiError(errorMessage(error));
      });
    void refresh();
    return () => {
      mounted = false;
    };
  }, [refresh]);

  useEffect(() => {
    const hasProcessing = videos.some((video) => video.stage === "processing");
    if (!hasProcessing) return;
    const timer = setInterval(() => void refresh(), 1600);
    return () => clearInterval(timer);
  }, [refresh, videos]);

  const models = config?.models?.length === 2 ? config.models : FALLBACK_MODELS;
  const allTags = useMemo(() => tagNames(videos), [videos]);
  const selectedBatchAction = useMemo<JobAction | null>(() => {
    const chosen = videos.filter((video) => selectedIds.includes(video.id));
    if (!chosen.length) return null;
    const stages = new Set(chosen.map((video) => video.stage));
    if (stages.size !== 1) return null;
    const [stage] = Array.from(stages);
    if (stage === "inbox") return "process";
    if (stage === "error") return "retry";
    if (stage === "processed") return "reprocess";
    return null;
  }, [selectedIds, videos]);

  const mergeVideo = useCallback((video: Video) => {
    setVideos((current) => {
      const previous = current.find((entry) => entry.id === video.id);
      const merged = video.runs == null && previous?.runs ? { ...video, runs: previous.runs } : video;
      return replaceItem(current, merged);
    });
    setDetail((current) => {
      if (current?.id !== video.id) return current;
      return video.runs == null && current.runs ? { ...video, runs: current.runs } : video;
    });
  }, []);

  const selectVideo = useCallback(async (id: string) => {
    setSelectedVideoId(id);
    setActiveView("library");
    const cached = videos.find((video) => video.id === id);
    if (cached) setDetail(cached);
    try {
      setDetail(await api.getVideo(id));
    } catch (error) {
      showNotice(errorMessage(error), "error");
    }
  }, [showNotice, videos]);

  const handleAdded = useCallback((video: Video, duplicate: boolean) => {
    mergeVideo(video);
    setSelectedVideoId(video.id);
    setAddOpen(false);
    setActiveView("library");
    setSelectedIds([]);
    showNotice(duplicate ? "This link was already in your library." : "Saved to Inbox. Choose a model when you are ready to process it.", duplicate ? "info" : "success");
    void refresh();
  }, [mergeVideo, refresh, showNotice]);

  const openModelDialog = useCallback((ids: string[], action: JobAction) => {
    if (!ids.length) return;
    setModelDialog({ ids, action, hasManualEdits: videos.some((video) => ids.includes(video.id) && video.manual_edits) });
  }, [videos]);

  const handleJobs = useCallback(async (modelKey: "farukstt" | "whisper_large_v3", ownerAsserted: boolean) => {
    if (!modelDialog) return;
    setJobBusy(true);
    try {
      const result = await api.createJobs({
        video_ids: modelDialog.ids,
        action: modelDialog.action,
        model_key: modelKey,
        owner_asserted_tunisian: ownerAsserted,
      });
      setModelDialog(null);
      setSelectedIds([]);
      const rejectedText = result.rejected.length ? ` ${result.rejected.length} item${result.rejected.length === 1 ? " was" : "s were"} rejected.` : "";
      showNotice(`${actionLabel(modelDialog.action)} queued with ${modelKey === "farukstt" ? "FarukSTT" : "Whisper Large-v3 (Full)"}.${rejectedText}`, result.rejected.length ? "warning" : "success");
      await refresh();
    } catch (error) {
      showNotice(errorMessage(error), "error");
    } finally {
      setJobBusy(false);
    }
  }, [modelDialog, refresh, showNotice]);

  const handleStageAction = useCallback(async (id: string, action: StageAction) => {
    setActionBusy(id);
    try {
      const updated = await api.stageAction(id, action);
      mergeVideo(updated);
      showNotice(action === "complete" ? "Completed. Source media was deleted; the transcript remains." : action === "done" ? "Moved to Done." : "Moved back to Processed.", "success");
      await refresh();
    } catch (error) {
      showNotice(errorMessage(error), "error");
    } finally {
      setActionBusy(null);
    }
  }, [mergeVideo, refresh, showNotice]);

  const handleVideoUpdated = useCallback((video: Video) => {
    mergeVideo(video);
  }, [mergeVideo]);

  const toggleSelected = (id: string) => {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><Waveform size={21} weight="bold" /></div>
          <div>
            <span className="brand-name">Kite</span>
            <span className="brand-subtitle">Video library</span>
          </div>
        </div>

        <div className="sidebar-section-label">Workspace</div>
        <nav className="primary-nav" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = activeView === item.key;
            return (
              <button key={item.key} className={`nav-item ${isActive ? "is-active" : ""}`} onClick={() => setActiveView(item.key)}>
                <Icon size={18} weight={isActive ? "fill" : "regular"} />
                <span>{item.label}</span>
                {item.key === "library" && counts.total > 0 ? <span className="nav-count">{counts.total}</span> : null}
              </button>
            );
          })}
        </nav>

        <div className="sidebar-spacer" />
        <div className="local-card">
          <div className="local-card-icon"><ShieldCheck size={18} weight="duotone" /></div>
          <div>
            <strong>Local workspace</strong>
            <span>Media stays on this Mac</span>
          </div>
          <span className="status-dot" aria-label="Local mode active" />
        </div>
        <div className="sidebar-footer">Kite v0.1 · local only</div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <div className="topbar-context">
            <span className="topbar-kicker">Personal workspace</span>
            <span className="topbar-divider">/</span>
            <span>{activeView === "dashboard" ? "Overview" : activeView === "library" ? "Library" : "Preferences"}</span>
          </div>
          <div className="topbar-actions">
            <label className="global-search" aria-label="Search library">
              <MagnifyingGlass size={16} />
              <input name="global-search" value={search} onChange={(event) => setSearch(event.target.value)} onFocus={() => setActiveView("library")} placeholder="Search library" />
              <kbd>⌘ K</kbd>
            </label>
            <ThemeMenu theme={theme} onChange={setTheme} compact />
            <button className="avatar-button" title="Local owner">LM</button>
            <button className="button button-primary button-small" onClick={() => setAddOpen(true)}>
              <Plus size={16} weight="bold" />
              <span>New video</span>
            </button>
          </div>
        </header>

        <AnimatePresence initial={false} mode="wait">
          {notice ? (
            <motion.div
              key={notice.message}
              className={`notice notice-${notice.kind}`}
              initial={reducedMotion ? false : { opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reducedMotion ? undefined : { opacity: 0, y: -5 }}
            >
              {notice.kind === "success" ? <CheckCircle size={18} weight="fill" /> : notice.kind === "error" ? <WarningCircle size={18} weight="fill" /> : <Info size={18} weight="fill" />}
              <span>{notice.message}</span>
              <button className="icon-button icon-button-tiny" onClick={() => setNotice(null)} aria-label="Dismiss notification"><X size={15} /></button>
            </motion.div>
          ) : null}
        </AnimatePresence>

        {apiError ? (
          <div className="offline-banner">
            <WarningCircle size={17} weight="fill" />
            <span>{apiError}</span>
            <button className="button button-quiet button-small" onClick={() => { setApiError(null); void refresh(); }}>Retry connection</button>
          </div>
        ) : null}

        <main className="page-content">
          {activeView === "dashboard" ? (
            <DashboardPage
              counts={counts}
              processing={videos.filter((video) => video.stage === "processing")}
              activities={activities}
              models={models}
              loading={loading}
              onAdd={() => setAddOpen(true)}
              onOpenLibrary={() => setActiveView("library")}
              onSelect={selectVideo}
            />
          ) : null}
          {activeView === "library" ? (
            <LibraryPage
              videos={videos}
              counts={counts}
              search={search}
              allTags={allTags}
              selectedIds={selectedIds}
              selectedBatchAction={selectedBatchAction}
              selectedVideoId={selectedVideoId}
              detail={detail}
              actionBusy={actionBusy}
              onSearch={setSearch}
              onSelect={selectVideo}
              onToggleSelected={toggleSelected}
              onToggleAll={(ids) => setSelectedIds(ids)}
              onOpenModel={openModelDialog}
              onStageAction={handleStageAction}
              onUpdated={handleVideoUpdated}
              onNotice={showNotice}
              onCloseDetail={() => { setSelectedVideoId(null); setDetail(null); }}
              onClearSelection={() => setSelectedIds([])}
            />
          ) : null}
          {activeView === "settings" ? <SettingsPage models={models} theme={theme} onThemeChange={setTheme} /> : null}
        </main>
      </div>

      <AnimatePresence>
        {addOpen ? <AddVideoDialog key="add" suggestedTags={config?.suggested_tags ?? []} onClose={() => setAddOpen(false)} onSaved={handleAdded} onError={showNotice} /> : null}
        {modelDialog ? <ModelDialog key="model" action={modelDialog.action} count={modelDialog.ids.length} hasManualEdits={modelDialog.hasManualEdits} models={models} busy={jobBusy} onClose={() => setModelDialog(null)} onSubmit={handleJobs} /> : null}
      </AnimatePresence>
    </div>
  );
}

function DashboardPage({
  counts,
  processing,
  activities,
  models,
  loading,
  onAdd,
  onOpenLibrary,
  onSelect,
}: {
  counts: Counts;
  processing: Video[];
  activities: ActivityItem[];
  models: ModelOption[];
  loading: boolean;
  onAdd: () => void;
  onOpenLibrary: () => void;
  onSelect: (id: string) => void;
}) {
  const reducedMotion = useReducedMotion() ?? false;
  const metrics = [
    { label: "Inbox", value: counts.inbox, detail: "Waiting for a model", icon: Stack, tone: "blue" },
    { label: "Processing", value: counts.processing, detail: "Local jobs running", icon: Pulse, tone: "orange" },
    { label: "Processed", value: counts.processed, detail: "Ready to review", icon: CheckCircle, tone: "green" },
    { label: "Complete", value: counts.complete, detail: "Transcript retained", icon: LockSimple, tone: "purple" },
  ] as const;

  return (
    <div className="view-stack">
      <section className="hero-row">
        <div>
          <span className="eyebrow"><Sparkle size={14} weight="fill" /> Your quiet corner for good transcripts</span>
          <h1>Make sense of the scroll.</h1>
          <p className="page-lede">Save public short videos, process them locally, and keep the useful words close.</p>
        </div>
        <div className="hero-actions">
          <button className="button button-primary" onClick={onAdd}><CloudArrowUp size={18} weight="duotone" /> Add a video</button>
          <button className="button button-secondary" onClick={onOpenLibrary}><Stack size={17} /> Open library <ArrowRight size={15} /></button>
        </div>
      </section>

      <section className="metric-grid" aria-label="Library totals">
        {metrics.map((metric, index) => {
          const Icon = metric.icon;
          return (
            <motion.article
              key={metric.label}
              className={`metric-card metric-${metric.tone}`}
              initial={reducedMotion ? false : { opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={reducedMotion ? { duration: 0 } : { delay: index * 0.045, duration: 0.32 }}
            >
              <div className="metric-top"><span>{metric.label}</span><span className="metric-icon"><Icon size={17} weight="duotone" /></span></div>
              <strong>{loading ? <span className="skeleton-number" /> : metric.value}</strong>
              <span className="metric-detail">{metric.detail}</span>
            </motion.article>
          );
        })}
      </section>

      <section className="dashboard-grid">
        <div className="panel processing-panel">
          <div className="panel-heading">
            <div><span className="section-eyebrow">Live queue</span><h2>Processing now</h2></div>
            <span className="live-pulse"><span /> Local worker</span>
          </div>
          {processing.length ? (
            <div className="processing-list">
              {processing.map((video) => <ProcessingCard key={video.id} video={video} onSelect={onSelect} />)}
            </div>
          ) : (
            <EmptyProcessing onAdd={onAdd} />
          )}
        </div>

        <div className="panel model-panel">
          <div className="panel-heading">
            <div><span className="section-eyebrow">Recognition lab</span><h2>Choose your voice</h2></div>
            <Lightning size={18} className="panel-heading-icon" weight="duotone" />
          </div>
          <p className="panel-copy">Every processing run asks you to choose one model first. That keeps testing comparable and auditable.</p>
          <div className="model-mini-list">
            {models.map((model) => <ModelMiniCard key={model.key} model={model} />)}
          </div>
          <div className="subtle-callout"><Info size={16} /><span>FarukSTT is the Derja-focused test. Whisper Large-v3 is the full multilingual baseline.</span></div>
        </div>
      </section>

      <section className="panel activity-panel">
        <div className="panel-heading">
          <div><span className="section-eyebrow">Trace</span><h2>Recent activity</h2></div>
          <button className="text-button" onClick={onOpenLibrary}>View library <ArrowRight size={14} /></button>
        </div>
        {activities.length ? (
          <div className="activity-list">{activities.slice(0, 8).map((item) => <ActivityRow key={item.id} item={item} onSelect={item.video_id ? onSelect : undefined} />)}</div>
        ) : (
          <div className="empty-inline"><Clock size={18} /><span>Activity will appear here once you save a source.</span></div>
        )}
      </section>
    </div>
  );
}

function ProcessingCard({ video, onSelect }: { video: Video; onSelect: (id: string) => void }) {
  const progressIndex = Math.max(0, PIPELINE_STEPS.findIndex(([key]) => key === video.job?.current_step));
  return (
    <button className="processing-card" onClick={() => onSelect(video.id)}>
      <Thumb video={video} size="medium" />
      <span className="processing-card-main">
        <strong>{video.title}</strong>
        <span>{video.job ? `${actionLabel(video.job.action)} · ${video.job.model_label}` : "Queued"}</span>
      </span>
      <span className="processing-card-progress">
        <span className="progress-label">{stepLabel(video.job?.current_step ?? null)}</span>
        <span className="progress-track"><span style={{ width: `${Math.max(10, ((progressIndex + 1) / PIPELINE_STEPS.length) * 100)}%` }} /></span>
      </span>
      <CaretRight size={17} className="muted-icon" />
    </button>
  );
}

function EmptyProcessing({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="empty-processing">
      <div className="empty-orbit"><Waveform size={24} weight="duotone" /></div>
      <div><strong>No active jobs</strong><span>Your local queue is clear. Add something when you find it.</span></div>
      <button className="button button-secondary button-small" onClick={onAdd}><Plus size={15} /> Add source</button>
    </div>
  );
}

function ModelMiniCard({ model }: { model: ModelOption }) {
  return (
    <div className="model-mini-card">
      <div className={`model-symbol ${model.key === "farukstt" ? "symbol-saffron" : "symbol-ink"}`}>
        {model.key === "farukstt" ? <Waveform size={17} weight="duotone" /> : <TextT size={17} weight="bold" />}
      </div>
      <div className="model-mini-copy"><strong>{model.label}</strong><span>{model.key === "farukstt" ? "Derja + code-switching" : "Full multilingual baseline"}</span></div>
      <span className={`ready-pill ${model.available ? "is-ready" : "is-pending"}`}>{model.available ? "Ready" : "Setup"}</span>
    </div>
  );
}

function ActivityRow({ item, onSelect }: { item: ActivityItem; onSelect?: (id: string) => void }) {
  const content = (
    <>
      <span className={`activity-dot activity-${item.kind}`} />
      <span className="activity-copy"><strong>{item.message}</strong><span>{item.display_title || (item.video_id ? "Video item" : "Workspace")} · {formatDate(item.created_at)}</span></span>
      {onSelect ? <CaretRight size={16} className="muted-icon" /> : null}
    </>
  );
  return onSelect ? <button className="activity-row" onClick={() => onSelect(item.video_id!)}>{content}</button> : <div className="activity-row">{content}</div>;
}

function LibraryPage({
  videos,
  counts,
  search,
  allTags,
  selectedIds,
  selectedBatchAction,
  selectedVideoId,
  detail,
  actionBusy,
  onSearch,
  onSelect,
  onToggleSelected,
  onToggleAll,
  onOpenModel,
  onStageAction,
  onUpdated,
  onNotice,
  onCloseDetail,
  onClearSelection,
}: {
  videos: Video[];
  counts: Counts;
  search: string;
  allTags: string[];
  selectedIds: string[];
  selectedBatchAction: JobAction | null;
  selectedVideoId: string | null;
  detail: Video | null;
  actionBusy: string | null;
  onSearch: (value: string) => void;
  onSelect: (id: string) => void;
  onToggleSelected: (id: string) => void;
  onToggleAll: (ids: string[]) => void;
  onOpenModel: (ids: string[], action: JobAction) => void;
  onStageAction: (id: string, action: StageAction) => void;
  onUpdated: (video: Video) => void;
  onNotice: (message: string, kind?: NoticeKind) => void;
  onCloseDetail: () => void;
  onClearSelection: () => void;
}) {
  const [stageFilter, setStageFilter] = useState<Stage | "all">("all");
  const [activeTags, setActiveTags] = useState<string[]>([]);
  const visibleVideos = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return videos.filter((video) => {
      const stageMatch = stageFilter === "all" || video.stage === stageFilter;
      const searchMatch = !needle || [video.title, video.creator, video.platform, video.source_url, ...video.tags].join(" ").toLowerCase().includes(needle);
      const tagMatch = !activeTags.length || activeTags.some((tag) => video.tags.includes(tag));
      return stageMatch && searchMatch && tagMatch;
    });
  }, [activeTags, search, stageFilter, videos]);
  const allSelected = visibleVideos.length > 0 && visibleVideos.every((video) => selectedIds.includes(video.id));
  const stageOptions: (Stage | "all")[] = ["all", ...(Object.keys(STAGE_LABELS) as Stage[])];
  const bulkStageAction = useMemo<StageAction | null>(() => {
    const selected = videos.filter((video) => selectedIds.includes(video.id));
    if (!selected.length || new Set(selected.map((video) => video.stage)).size !== 1) return null;
    if (selected[0].stage === "processed") return "done";
    if (selected[0].stage === "done") return "move_to_processed";
    return null;
  }, [selectedIds, videos]);

  const toggleTag = (tag: string) => setActiveTags((current) => current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]);

  return (
    <div className={`library-layout ${selectedVideoId ? "has-detail" : ""}`}>
      <section className="library-list-column">
        <div className="page-heading compact-heading">
          <div><span className="eyebrow"><Stack size={14} weight="fill" /> Archive</span><h1>Library</h1><p className="page-lede">One place for sources, drafts, and the words worth keeping.</p></div>
          <div className="heading-side-note"><HardDrives size={17} /><span>{counts.total} saved item{counts.total === 1 ? "" : "s"}</span></div>
        </div>

        <div className="stage-tabs" role="tablist" aria-label="Filter by workflow stage">
          {stageOptions.map((stage) => {
            const count = stage === "all" ? counts.total : counts[stage] ?? 0;
            return <button key={stage} className={`stage-tab ${stageFilter === stage ? "is-active" : ""}`} onClick={() => setStageFilter(stage)}>{stage === "all" ? "All" : stageLabel(stage)}<span>{count}</span></button>;
          })}
        </div>

        <div className="library-toolbar">
          <label className="search-field"><MagnifyingGlass size={16} /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search title, creator, or tag" /><kbd>⌘ K</kbd></label>
          <div className="toolbar-actions">
            <div className="filter-menu"><FunnelSimple size={16} /><span>{activeTags.length ? `${activeTags.length} tag${activeTags.length === 1 ? "" : "s"}` : "Tags"}</span><CaretDown size={14} />
              <div className="filter-popover">{allTags.length ? allTags.map((tag) => <button key={tag} className={`filter-option ${activeTags.includes(tag) ? "is-selected" : ""}`} onClick={() => toggleTag(tag)}><span>{tag}</span>{activeTags.includes(tag) ? <Check size={14} /> : null}</button>) : <span className="filter-empty">Tags appear after you save details.</span>}</div>
            </div>
            {selectedIds.length ? <button className="button button-quiet button-small" onClick={onClearSelection}>{selectedIds.length} selected <X size={14} /></button> : null}
          </div>
        </div>

        {selectedIds.length ? (
          <div className="bulk-bar">
            <span><CheckCircle size={16} weight="fill" /> {selectedIds.length} selected</span>
            <div>
              {selectedBatchAction ? <button className="button button-primary button-small" onClick={() => onOpenModel(selectedIds, selectedBatchAction)}>{actionLabel(selectedBatchAction)} with a model <ArrowRight size={14} /></button> : null}
              {bulkStageAction ? <button className="button button-secondary button-small" onClick={() => selectedIds.forEach((id) => onStageAction(id, bulkStageAction))}>{bulkStageAction === "done" ? "Mark Done" : "Move to Processed"}</button> : null}
            </div>
          </div>
        ) : null}

        {visibleVideos.length ? (
          <div className="library-table" role="table" aria-label="Saved videos">
            <div className="table-head" role="row">
              <span className="check-cell"><input name="select-all-visible" type="checkbox" checked={allSelected} onChange={() => onToggleAll(allSelected ? [] : visibleVideos.map((video) => video.id))} aria-label="Select all visible videos" /></span>
              <span>Source</span><span>Stage</span><span>Tags</span><span>Saved</span><span />
            </div>
            <AnimatePresence initial={false}>
              {visibleVideos.map((video) => (
                <VideoRow
                  key={video.id}
                  video={video}
                  selected={selectedIds.includes(video.id)}
                  isOpen={selectedVideoId === video.id}
                  actionBusy={actionBusy === video.id}
                  onSelect={onSelect}
                  onToggleSelected={onToggleSelected}
                  onOpenModel={onOpenModel}
                  onStageAction={onStageAction}
                />
              ))}
            </AnimatePresence>
          </div>
        ) : (
          <EmptyLibrary hasFilter={Boolean(search || activeTags.length || stageFilter !== "all")} />
        )}
      </section>

      <aside className="detail-column">
        {detail ? (
          <VideoDetail
            video={detail}
            onBack={onCloseDetail}
            onOpenModel={(action) => onOpenModel([detail.id], action)}
            onStageAction={onStageAction}
            onUpdated={onUpdated}
            onNotice={onNotice}
          />
        ) : (
          <div className="detail-placeholder"><div className="placeholder-art"><Waveform size={30} weight="duotone" /></div><strong>Select an item</strong><span>Transcript, processing history, and export controls will live here.</span></div>
        )}
      </aside>
    </div>
  );
}

function VideoRow({
  video,
  selected,
  isOpen,
  actionBusy,
  onSelect,
  onToggleSelected,
  onOpenModel,
  onStageAction,
}: {
  video: Video;
  selected: boolean;
  isOpen: boolean;
  actionBusy: boolean;
  onSelect: (id: string) => void;
  onToggleSelected: (id: string) => void;
  onOpenModel: (ids: string[], action: JobAction) => void;
  onStageAction: (id: string, action: StageAction) => void;
}) {
  const action = video.stage === "inbox" ? "process" : video.stage === "error" ? "retry" : video.stage === "processed" ? "reprocess" : null;
  return (
    <motion.div
      className={`table-row ${isOpen ? "is-open" : ""} ${selected ? "is-selected" : ""}`}
      role="row"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.18 }}
      onClick={() => onSelect(video.id)}
      onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onSelect(video.id); }}
      tabIndex={0}
    >
      <span className="check-cell" onClick={(event) => event.stopPropagation()}><input name={`select-${video.id}`} type="checkbox" checked={selected} onChange={() => onToggleSelected(video.id)} aria-label={`Select ${video.title}`} /></span>
      <span className="source-cell"><Thumb video={video} size="small" /><span className="source-copy"><strong>{video.title}</strong><span>{platformLabel(video.platform)} · {video.creator}</span></span></span>
      <span><StageBadge stage={video.stage} /></span>
      <span className="row-tags">{video.tags.length ? video.tags.slice(0, 2).map((tag) => <span className="tag-chip" key={tag}>{tag}</span>) : <span className="muted-text">No tags</span>}{video.tags.length > 2 ? <span className="tag-overflow">+{video.tags.length - 2}</span> : null}</span>
      <span className="saved-cell">{formatDate(video.saved_at, false)}<small>{formatDuration(video.duration_ms)}</small></span>
      <span className="row-action" onClick={(event) => event.stopPropagation()}>
        {action ? <button className="row-cta" disabled={actionBusy} onClick={() => onOpenModel([video.id], action)}>{actionBusy ? <CircleNotch size={15} className="spin" /> : action === "reprocess" ? <ArrowClockwise size={15} /> : <Play size={15} weight="fill" />}<span>{actionLabel(action)}</span></button> : video.stage === "done" ? <button className="row-cta quiet-cta" onClick={() => onStageAction(video.id, "complete")}><LockSimple size={15} /> Complete</button> : <DotsThree size={20} className="muted-icon" />}
      </span>
    </motion.div>
  );
}

function StageBadge({ stage }: { stage: Stage }) {
  const icon = stage === "processing" ? <CircleNotch size={13} className="spin" /> : stage === "processed" || stage === "done" ? <CheckCircle size={13} weight="fill" /> : stage === "complete" ? <LockSimple size={13} weight="fill" /> : stage === "error" ? <WarningCircle size={13} weight="fill" /> : <Clock size={13} />;
  return <span className={`stage-badge stage-${stage}`}>{icon}{stageLabel(stage)}</span>;
}

function Thumb({ video, size }: { video: Video; size: "small" | "medium" }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className={`thumb thumb-${size} platform-${video.platform}`}>
      {video.thumbnail_url && !failed ? <img src={video.thumbnail_url} alt="" onError={() => setFailed(true)} /> : <><span>{video.platform === "fixture" ? "T" : video.platform.slice(0, 1).toUpperCase()}</span><Waveform size={size === "medium" ? 18 : 14} weight="duotone" /></>}
    </span>
  );
}

function EmptyLibrary({ hasFilter }: { hasFilter: boolean }) {
  return (
    <div className="empty-library"><div className="empty-orbit large"><Stack size={28} weight="duotone" /></div><strong>{hasFilter ? "Nothing matches this view" : "Your library starts here"}</strong><span>{hasFilter ? "Try a different stage, tag, or search term." : "Save a public Facebook, Instagram, or TikTok video to begin."}</span></div>
  );
}

function VideoDetail({
  video,
  onBack,
  onOpenModel,
  onStageAction,
  onUpdated,
  onNotice,
}: {
  video: Video;
  onBack: () => void;
  onOpenModel: (action: JobAction) => void;
  onStageAction: (id: string, action: StageAction) => void;
  onUpdated: (video: Video) => void;
  onNotice: (message: string, kind?: NoticeKind) => void;
}) {
  const [title, setTitle] = useState(video.title);
  const [creator, setCreator] = useState(video.creator);
  const [tags, setTags] = useState(video.tags.join(", "));
  const [detailsBusy, setDetailsBusy] = useState(false);
  const [segments, setSegments] = useState<Segment[]>(video.transcript?.segments ?? []);
  const [saveState, setSaveState] = useState<"saved" | "saving" | "unsaved" | "conflict" | "locked">(video.transcript ? "saved" : "locked");
  const dirtyRef = useRef(false);
  const generationRef = useRef(0);
  const videoIdRef = useRef(video.id);
  const [confirmComplete, setConfirmComplete] = useState(false);

  useEffect(() => {
    if (videoIdRef.current !== video.id) {
      videoIdRef.current = video.id;
      dirtyRef.current = false;
      setTitle(video.title);
      setCreator(video.creator);
      setTags(video.tags.join(", "));
      setSegments(video.transcript?.segments ?? []);
      setSaveState(video.transcript ? "saved" : "locked");
      return;
    }
    setTitle(video.title);
    setCreator(video.creator);
    setTags(video.tags.join(", "));
    if (!dirtyRef.current) {
      setSegments(video.transcript?.segments ?? []);
      setSaveState(video.transcript ? "saved" : "locked");
    }
  }, [video]);

  useEffect(() => {
    if (!dirtyRef.current || !video.transcript || video.stage === "complete") return;
    const expectedRevision = video.transcript.id;
    const generation = generationRef.current;
    const timer = setTimeout(async () => {
      setSaveState("saving");
      try {
        const updated = await api.updateTranscript(video.id, expectedRevision, segments);
        if (generation === generationRef.current) {
          dirtyRef.current = false;
          onUpdated(updated);
          setSaveState("saved");
        }
      } catch (error) {
        if (generation === generationRef.current) {
          setSaveState(error instanceof ApiError && error.code === "transcript_conflict" ? "conflict" : "unsaved");
          onNotice(errorMessage(error), "error");
        }
      }
    }, 850);
    return () => clearTimeout(timer);
  }, [onNotice, onUpdated, segments, video]);

  const editable = video.stage !== "processing" && video.stage !== "complete";
  const hasTranscript = Boolean(video.transcript);
  const updateSegment = (index: number, patch: Partial<Segment>) => {
    if (!editable || !hasTranscript) return;
    dirtyRef.current = true;
    generationRef.current += 1;
    setSaveState("unsaved");
    setSegments((current) => current.map((segment, itemIndex) => itemIndex === index ? { ...segment, ...patch } : segment));
  };
  const addSegment = () => {
    if (!editable || !hasTranscript) return;
    const previous = segments[segments.length - 1];
    const start = previous ? previous.end_ms : 0;
    updateSegment(-1, {});
    setSegments((current) => [...current, { start_ms: start, end_ms: start + 1500, text: "" }]);
  };
  const removeSegment = (index: number) => {
    if (!editable || !hasTranscript) return;
    dirtyRef.current = true;
    generationRef.current += 1;
    setSaveState("unsaved");
    setSegments((current) => current.filter((_, itemIndex) => itemIndex !== index));
  };
  const saveDetails = async () => {
    if (!editable) return;
    setDetailsBusy(true);
    try {
      const updated = await api.updateVideo(video.id, { title, creator, tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean) });
      onUpdated(updated);
      onNotice("Library details saved.", "success");
    } catch (error) {
      onNotice(errorMessage(error), "error");
    } finally {
      setDetailsBusy(false);
    }
  };
  const copyTranscript = async (withTimes: boolean) => {
    const text = withTimes ? segments.map((segment) => `[${formatEditorTime(segment.start_ms)}] ${segment.text}`).join("\n") : segments.map((segment) => segment.text).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      onNotice(withTimes ? "Timestamped transcript copied." : "Transcript copied.", "success");
    } catch {
      onNotice("Clipboard access was not available in this browser.", "warning");
    }
  };

  const nextAction = video.stage === "inbox" ? "process" : video.stage === "error" ? "retry" : video.stage === "processed" ? "reprocess" : null;

  return (
    <div className="detail-panel">
      <div className="detail-topline"><button className="back-button" onClick={onBack}><ArrowLeft size={16} /> <span>Library</span></button><span className="detail-id">{video.canonical_id}</span></div>
      <div className="detail-source-head"><Thumb video={video} size="medium" /><div className="detail-source-copy"><div className="detail-platform">{platformLabel(video.platform)} <span>·</span> {formatDuration(video.duration_ms)}</div><h2>{video.title}</h2><span>{video.creator}</span></div><StageBadge stage={video.stage} /></div>

      {video.error_message ? <div className={`error-card error-${video.error_code === "private_video" ? "private" : "general"}`}><WarningCircle size={18} weight="fill" /><div><strong>{video.error_code === "private_video" ? "Private source" : video.error_code === "uncertain_language" ? "Language needs review" : "Processing stopped"}</strong><span>{video.error_message}</span><small>{video.failed_step ? `Stopped at ${stepLabel(video.failed_step)}.` : "You can keep the link and try again when the source is available."}</small></div></div> : null}
      {video.stage === "complete" ? <div className="complete-card"><LockSimple size={18} weight="fill" /><div><strong>Read-only record</strong><span>Source media has been removed. Your transcript and edit history are retained.</span></div></div> : null}

      <section className="detail-section metadata-section">
        <div className="detail-section-heading"><div><span className="section-eyebrow">Library details</span><h3>Keep the context</h3></div>{editable ? <button className="button button-quiet button-small" onClick={saveDetails} disabled={detailsBusy}>{detailsBusy ? <CircleNotch size={14} className="spin" /> : <Check size={14} />} Save details</button> : null}</div>
        <label className="field-label">Title<input name="video-title" value={title} onChange={(event) => setTitle(event.target.value)} disabled={!editable} /></label>
        <label className="field-label">Creator<input name="video-creator" value={creator} onChange={(event) => setCreator(event.target.value)} disabled={!editable} /></label>
        <label className="field-label"><span>Tags <small>comma separated</small></span><input name="video-tags" value={tags} onChange={(event) => setTags(event.target.value)} disabled={!editable} /></label>
        <div className="source-url-row"><Tag size={14} /><span title={video.source_url}>{video.source_url}</span><a href={video.source_page_url || video.canonical_url} target="_blank" rel="noreferrer">Open source <ArrowUpRightIcon /></a></div>
      </section>

      <section className="detail-section history-section">
        <div className="detail-section-heading"><div><span className="section-eyebrow">Pipeline</span><h3>Processing history</h3></div>{nextAction ? <button className="button button-primary button-small" onClick={() => onOpenModel(nextAction)}><Play size={14} weight="fill" /> {actionLabel(nextAction)}</button> : null}</div>
        {video.job?.state === "running" || video.job?.state === "queued" ? <div className="job-status"><CircleNotch size={16} className="spin" /><span><strong>{actionLabel(video.job.action)} in progress</strong><small>{stepLabel(video.job.current_step)} · {video.job.model_label}</small></span></div> : null}
        <PipelineTimeline video={video} />
        {video.job ? <a className="export-link" href={`${API_BASE}/api/jobs/${encodeURIComponent(video.job.id)}/logs`} target="_blank" rel="noreferrer">View debug logs · current run</a> : null}
        {video.runs?.filter((run) => run.id !== video.job?.id).map((run) => <p key={`logs-${run.id}`}><a className="export-link" href={`${API_BASE}/api/jobs/${encodeURIComponent(run.id)}/logs`} target="_blank" rel="noreferrer">Debug logs · {run.model_label} · {formatDate(run.started_at)} · {run.id.slice(-6)}</a></p>)}
        {video.runs?.length ? <div className="run-history">{video.runs.slice(0, 4).map((run) => <RunRow key={run.id} run={run} />)}</div> : <div className="empty-inline history-empty"><Clock size={16} /><span>No runs yet. This item is waiting in Inbox.</span></div>}
      </section>

      <section className="detail-section transcript-section">
        <div className="detail-section-heading"><div><span className="section-eyebrow">Transcript draft</span><h3>{hasTranscript ? "Review the words" : "No transcript yet"}</h3></div>{hasTranscript ? <span className={`save-indicator save-${saveState}`}>{saveState === "saving" ? <CircleNotch size={13} className="spin" /> : saveState === "saved" ? <Check size={13} /> : <WarningCircle size={13} />} {saveState === "saving" ? "Saving" : saveState === "conflict" ? "Refresh needed" : saveState === "unsaved" ? "Unsaved" : video.stage === "complete" ? "Read-only" : "Saved"}</span> : null}</div>
        {hasTranscript ? <>
          <div className="transcript-toolbar"><button className="button button-secondary button-small" onClick={() => void copyTranscript(false)}><CopySimple size={14} /> Copy text</button><button className="button button-secondary button-small" onClick={() => void copyTranscript(true)}><TextT size={14} /> Copy + timestamps</button><span className="toolbar-spacer" /><a className="export-link" href={exportUrl(video.id, "txt")} download><DownloadSimple size={14} /> TXT</a><a className="export-link" href={exportUrl(video.id, "srt")} download><DownloadSimple size={14} /> SRT</a><a className="export-link" href={exportUrl(video.id, "vtt")} download><DownloadSimple size={14} /> VTT</a></div>
          <div className="transcript-notice"><Info size={15} /><span>Draft output · {video.transcript?.origin} · {video.transcript?.model_key === "farukstt" ? "FarukSTT" : "Whisper Large-v3 (Full)"}. Recognition output is preserved separately from your edits.</span></div>
          <div className="segment-list">
            {segments.map((segment, index) => <TranscriptSegment key={`${video.transcript?.id}-${index}`} segment={segment} index={index} editable={editable} onChange={updateSegment} onRemove={removeSegment} />)}
          </div>
          {editable ? <button className="add-segment" onClick={addSegment}><Plus size={15} /> Add segment</button> : null}
        </> : <div className="transcript-empty"><FileText size={23} weight="duotone" /><span>{video.stage === "processing" ? "Your selected model will write a draft here when the local worker finishes." : video.stage === "error" ? "Resolve the error, then retry to create a transcript draft." : "Choose a model to process this saved source."}</span></div>}
      </section>

      {video.stage === "processed" ? <div className="detail-footer-actions"><button className="button button-primary" onClick={() => onStageAction(video.id, "done")}><CheckCircle size={16} weight="fill" /> Mark as Done</button></div> : null}
      {video.stage === "done" ? <div className="detail-footer-actions"><button className="button button-secondary" onClick={() => onStageAction(video.id, "move_to_processed")}><ArrowLeft size={16} /> Move to Processed</button><button className="button button-primary" onClick={() => setConfirmComplete(true)}><LockSimple size={16} weight="fill" /> Complete record</button></div> : null}
      {confirmComplete ? <ConfirmComplete onCancel={() => setConfirmComplete(false)} onConfirm={() => { setConfirmComplete(false); onStageAction(video.id, "complete"); }} /> : null}
    </div>
  );
}

function ArrowUpRightIcon() {
  return <ArrowRight size={13} className="external-arrow" />;
}

function PipelineTimeline({ video }: { video: Video }) {
  const failedIndex = video.failed_step ? PIPELINE_STEPS.findIndex(([key]) => key === video.failed_step) : -1;
  const currentIndex = video.stage === "processed" || video.stage === "done" || video.stage === "complete" ? PIPELINE_STEPS.length : video.job?.current_step ? PIPELINE_STEPS.findIndex(([key]) => key === video.job?.current_step) : -1;
  return (
    <div className="pipeline-timeline">
      {PIPELINE_STEPS.map(([key, label], index) => {
        const completed = index < currentIndex;
        const failed = index === failedIndex;
        return <div className={`pipeline-step ${completed ? "is-complete" : ""} ${failed ? "is-failed" : ""} ${index === currentIndex ? "is-current" : ""}`} key={key}><span className="pipeline-dot">{failed ? <WarningCircle size={12} weight="fill" /> : completed ? <Check size={12} weight="bold" /> : index === currentIndex ? <CircleNotch size={12} className="spin" /> : <span />}</span><span>{label}</span></div>;
      })}
    </div>
  );
}

function RunRow({ run }: { run: Run }) {
  return <div className="run-row"><span className={`run-state run-${run.state}`}>{run.state === "succeeded" ? <Check size={12} /> : run.state === "failed" ? <WarningCircle size={12} /> : <Clock size={12} />}</span><span className="run-copy"><strong>{actionLabel(run.action)} · {run.model_label}</strong><small>{run.state === "failed" ? `${run.error_message || "Failed"}` : run.state === "succeeded" ? `Completed ${formatDate(run.finished_at)}` : `Attempt ${run.attempt_count || 0} · ${formatDate(run.updated_at)}`}</small></span><span className="run-source">{run.model_source}</span></div>;
}

function TranscriptSegment({
  segment,
  index,
  editable,
  onChange,
  onRemove,
}: {
  segment: Segment;
  index: number;
  editable: boolean;
  onChange: (index: number, patch: Partial<Segment>) => void;
  onRemove: (index: number) => void;
}) {
  return <div className="transcript-segment"><div className="segment-gutter"><span>{(index + 1).toString().padStart(2, "0")}</span><div className="segment-times"><label><span>start</span><input name={`segment-${index + 1}-start`} type="number" min={0} value={segment.start_ms} onChange={(event) => onChange(index, { start_ms: Number(event.target.value) })} disabled={!editable} /></label><span>→</span><label><span>end</span><input name={`segment-${index + 1}-end`} type="number" min={1} value={segment.end_ms} onChange={(event) => onChange(index, { end_ms: Number(event.target.value) })} disabled={!editable} /></label></div></div><textarea name={`segment-${index + 1}-text`} dir="auto" value={segment.text} onChange={(event) => onChange(index, { text: event.target.value })} disabled={!editable} aria-label={`Transcript segment ${index + 1}`} />{editable ? <button className="segment-delete" onClick={() => onRemove(index)} aria-label={`Delete segment ${index + 1}`}><Trash size={15} /></button> : null}</div>;
}

function ConfirmComplete({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  return <motion.div className="modal-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><motion.div className="confirm-card" initial={{ opacity: 0, scale: 0.97, y: 8 }} animate={{ opacity: 1, scale: 1, y: 0 }}><div className="confirm-icon"><LockSimple size={21} weight="fill" /></div><h3>Complete this record?</h3><p>The source audio/video will be deleted from local storage. The transcript and edit history will remain read-only.</p><div className="modal-actions"><button className="button button-secondary" onClick={onCancel}>Keep in Done</button><button className="button button-primary" onClick={onConfirm}>Delete source & complete</button></div></motion.div></motion.div>;
}

function AddVideoDialog({
  suggestedTags,
  onClose,
  onSaved,
  onError,
}: {
  suggestedTags: string[];
  onClose: () => void;
  onSaved: (video: Video, duplicate: boolean) => void;
  onError: (message: string, kind?: NoticeKind) => void;
}) {
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [saveBusy, setSaveBusy] = useState(false);
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const inspect = async () => {
    if (!url.trim()) return;
    setPreviewBusy(true);
    setSubmitted(true);
    try {
      setPreview(await api.preview(url.trim()));
    } catch (error) {
      setPreview(null);
      onError(errorMessage(error), "error");
    } finally {
      setPreviewBusy(false);
    }
  };
  const addTag = (value = tagInput) => {
    const normalized = value.trim();
    if (!normalized || tags.includes(normalized)) {
      setTagInput("");
      return;
    }
    setTags((current) => [...current, normalized]);
    setTagInput("");
  };
  const save = async () => {
    if (!preview) return;
    setSaveBusy(true);
    try {
      const result = await api.createVideo({
        url: preview.url,
        source_page_url: preview.source_page_url,
        title: preview.title,
        creator: preview.creator,
        thumbnail_url: preview.thumbnail_url,
        duration_ms: preview.duration_ms,
        tags,
      });
      onSaved(result.video, result.duplicate);
    } catch (error) {
      onError(errorMessage(error), "error");
    } finally {
      setSaveBusy(false);
    }
  };

  return <motion.div className="modal-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <motion.div className="modal-card add-modal" initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.22 }}>
      <div className="modal-header"><div><span className="section-eyebrow">New library item</span><h2>Bring a video into focus</h2><p>Paste a public social-video link. Metadata lookup is separate from download and transcription.</p></div><button className="icon-button" onClick={onClose} aria-label="Close add video dialog"><X size={19} /></button></div>
      <form onSubmit={(event) => { event.preventDefault(); void inspect(); }}>
        <label className="field-label large-label">Video URL<div className="url-input-wrap"><LinkIcon /><input name="video-url" autoFocus value={url} onChange={(event) => { setUrl(event.target.value); setSubmitted(false); }} placeholder="https://www.instagram.com/reel/..." /><button className="button button-dark button-small" type="submit" disabled={previewBusy || !url.trim()}>{previewBusy ? <CircleNotch size={15} className="spin" /> : <MagnifyingGlass size={15} />} {previewBusy ? "Checking" : "Preview"}</button></div></label>
      </form>
      <div className="fixture-hint"><Info size={14} /><span>For local UI testing only, enable <code>ALLOW_FIXTURE_SOURCES=true</code> and use <code>fixture://tunisian-demo</code>.</span></div>
      {submitted && !preview && !previewBusy ? <div className="inline-error"><WarningCircle size={16} /><span>Nothing to preview yet. Check the URL and try again.</span></div> : null}
      {preview ? <div className="preview-block"><div className="preview-heading"><span className={`preview-status preview-${preview.status}`}>{preview.status === "ready" ? <CheckCircle size={14} weight="fill" /> : <WarningCircle size={14} weight="fill" />} {preview.status === "ready" ? "Metadata found" : preview.status === "private" ? "Private source" : "Metadata unknown"}</span><span>{platformLabel(preview.platform)} · {formatDuration(preview.duration_ms)}</span></div><div className="preview-content"><div className={`preview-thumb platform-${preview.platform}`}>{preview.thumbnail_url ? <img src={preview.thumbnail_url} alt="" /> : <Waveform size={23} weight="duotone" />}</div><div className="preview-copy"><strong>{preview.title || "Untitled video"}</strong><span>{preview.creator || "Creator unknown"}</span><small>{preview.message}</small></div></div><div className="preview-source"><span title={preview.canonical_url}>{preview.canonical_url}</span><span>{preview.metadata_source || "No metadata adapter result"}</span></div></div> : null}
      {preview ? <>
        <div className="tag-editor"><div className="field-label"><span>Tags <small>optional</small></span><div className="tag-input-wrap"><Tag size={15} /><input name="video-tag" value={tagInput} onChange={(event) => setTagInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === ",") { event.preventDefault(); addTag(); } }} placeholder="Add a tag" />{tagInput ? <button type="button" onClick={() => addTag()}><Plus size={14} /></button> : null}</div></div><div className="tag-suggestions">{suggestedTags.filter((tag) => !tags.includes(tag)).slice(0, 5).map((tag) => <button type="button" key={tag} onClick={() => addTag(tag)}>{tag}</button>)}{tags.map((tag) => <button type="button" className="tag-chip selected-chip" key={tag} onClick={() => setTags((current) => current.filter((item) => item !== tag))}>{tag} <X size={11} /></button>)}</div></div>
        <div className="modal-footer"><span className="modal-footnote"><ShieldCheck size={15} /> Saved locally first · no processing starts here</span><div className="modal-actions"><button type="button" className="button button-secondary" onClick={onClose}>Cancel</button><button type="button" className="button button-primary" disabled={saveBusy} onClick={() => void save()}>{saveBusy ? <CircleNotch size={16} className="spin" /> : <Stack size={16} />} {saveBusy ? "Saving" : "Save to Inbox"}</button></div></div>
      </> : null}
    </motion.div>
  </motion.div>;
}

function ModelDialog({
  action,
  count,
  hasManualEdits,
  models,
  busy,
  onClose,
  onSubmit,
}: {
  action: JobAction;
  count: number;
  hasManualEdits: boolean;
  models: ModelOption[];
  busy: boolean;
  onClose: () => void;
  onSubmit: (modelKey: "farukstt" | "whisper_large_v3", ownerAsserted: boolean) => void;
}) {
  const [selectedModel, setSelectedModel] = useState<"farukstt" | "whisper_large_v3" | null>(null);
  const [ownerAsserted, setOwnerAsserted] = useState(false);
  const selectedOption = models.find((model) => model.key === selectedModel);
  return <motion.div className="modal-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <motion.div className="modal-card model-modal" initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.22 }}>
      <div className="modal-header"><div><span className="section-eyebrow">{actionLabel(action)} · {count} item{count === 1 ? "" : "s"}</span><h2>Choose a recognition model</h2><p>This choice is recorded on the run. Select one before processing starts.</p></div><button className="icon-button" onClick={onClose} disabled={busy} aria-label="Close model dialog"><X size={19} /></button></div>
      <div className="model-choice-grid">
        {models.map((model) => { const selected = selectedModel === model.key; return <button type="button" key={model.key} className={`model-choice ${selected ? "is-selected" : ""}`} onClick={() => setSelectedModel(model.key)}><span className={`model-choice-mark ${model.key === "farukstt" ? "symbol-saffron" : "symbol-ink"}`}>{model.key === "farukstt" ? <Waveform size={20} weight="duotone" /> : <TextT size={20} weight="bold" />}</span><span className="model-choice-copy"><strong>{model.label}</strong><span>{model.description}</span><small>{model.source}</small></span><span className={`selection-ring ${selected ? "is-selected" : ""}`}>{selected ? <Check size={13} weight="bold" /> : null}</span><span className={`model-ready-note ${model.available ? "ready" : "setup"}`}>{model.available ? "Runtime ready" : "Needs local setup"}</span></button>; })}
      </div>
      {action === "reprocess" && hasManualEdits ? <div className="model-warning"><WarningCircle size={17} weight="fill" /><div><strong>Manual edits found</strong><span>A successful reprocess creates a fresh recognition draft. Your current edited transcript stays available in the revision history until the new result succeeds.</span></div></div> : null}
      <div className="model-test-note"><Info size={16} /><div><strong>Testing note</strong><span>Fixture sources can exercise either choice without loading a model. Real media requires the selected model's local runtime and files.</span></div></div>
      <label className="confirm-check"><input name="tunisian-confirmation" type="checkbox" checked={ownerAsserted} onChange={(event) => setOwnerAsserted(event.target.checked)} /><span><strong>I confirm this video is primarily Tunisian Arabic.</strong><small>The local app does not bundle a dialect classifier, so this confirmation is recorded as an owner assertion—not language proof.</small></span></label>
      <div className="modal-footer"><span className="modal-footnote"><ShieldCheck size={15} /> Local processing · draft output</span><div className="modal-actions"><button className="button button-secondary" onClick={onClose} disabled={busy}>Cancel</button><button className="button button-primary" disabled={!selectedOption || !ownerAsserted || busy} onClick={() => selectedModel && onSubmit(selectedModel, ownerAsserted)}>{busy ? <CircleNotch size={16} className="spin" /> : <Play size={16} weight="fill" />} {busy ? "Queueing" : `${actionLabel(action)} now`}</button></div></div>
    </motion.div>
  </motion.div>;
}

function LinkIcon() {
  return <span className="link-icon"><ArrowRight size={16} /></span>;
}

function SettingsPage({ models, theme, onThemeChange }: { models: ModelOption[]; theme: Theme; onThemeChange: (theme: Theme) => void }) {
  return <div className="view-stack settings-view"><div className="page-heading compact-heading"><div><span className="eyebrow"><GearSix size={14} weight="fill" /> Workspace setup</span><h1>Settings</h1><p className="page-lede">Small choices that keep this local library predictable.</p></div></div><div className="settings-grid"><section className="panel settings-panel"><div className="panel-heading"><div><span className="section-eyebrow">Recognition</span><h2>Local model readiness</h2></div><Lightning size={18} className="panel-heading-icon" weight="duotone" /></div><p className="panel-copy">Both models remain explicit choices at processing time. Setup status is informational; fixture tests can still compare the two paths.</p><div className="settings-model-list">{models.map((model) => <div className="settings-model" key={model.key}><div className={`model-symbol ${model.key === "farukstt" ? "symbol-saffron" : "symbol-ink"}`}>{model.key === "farukstt" ? <Waveform size={18} /> : <TextT size={18} weight="bold" />}</div><div><strong>{model.label}</strong><span>{model.source}</span><small>{model.availability_note}</small></div><span className={`ready-pill ${model.available ? "is-ready" : "is-pending"}`}>{model.available ? "Ready" : "Setup"}</span></div>)}</div></section><section className="panel settings-panel"><div className="panel-heading"><div><span className="section-eyebrow">Appearance</span><h2>Choose a surface</h2></div><Palette size={18} className="panel-heading-icon" weight="duotone" /></div><p className="panel-copy">The workspace remembers this choice in your browser. Motion follows your system's reduced-motion preference.</p><ThemeMenu theme={theme} onChange={onThemeChange} /><div className="settings-rule" /><div className="privacy-row"><ShieldCheck size={20} weight="duotone" /><div><strong>Local by design</strong><span>SQLite, local artifacts, and a local worker. No account or hosted transcript service is configured.</span></div></div></section><section className="panel settings-panel full-settings"><div className="panel-heading"><div><span className="section-eyebrow">Acquisition</span><h2>Working download path</h2></div><HardDrives size={18} className="panel-heading-icon" weight="duotone" /></div><div className="acquisition-grid"><div><span className="setting-label">URL metadata</span><strong>yt-dlp + web_embedded</strong><small>Metadata inspection uses the web embedded extractor argument.</small></div><div><span className="setting-label">Media download</span><strong><code>yta</code> login-shell function</strong><small>The worker invokes <code>zsh -lic 'yta "$@"'</code>, so your wrapper's embedding, Node.js runtime, retries, metadata, and thumbnail options remain active.</small></div><div><span className="setting-label">Audio preparation</span><strong>FFmpeg · mono 16 kHz WAV</strong><small>Recognition gets a stable local audio artifact and can resume from checkpoints.</small></div></div></section></div></div>;
}

function ThemeMenu({ theme, onChange, compact = false }: { theme: Theme; onChange: (theme: Theme) => void; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const current = THEME_OPTIONS.find((option) => option.key === theme) ?? THEME_OPTIONS[0];
  const Icon = current.icon;
  return <div className={`theme-menu ${compact ? "theme-menu-compact" : ""}`}><button className="theme-trigger" onClick={() => setOpen((value) => !value)} aria-expanded={open}><Icon size={16} weight="duotone" /><span>{compact ? "" : current.label}</span><CaretDown size={13} /></button>{open ? <div className="theme-popover">{THEME_OPTIONS.map((option) => { const OptionIcon = option.icon; return <button key={option.key} className={option.key === theme ? "is-selected" : ""} onClick={() => { onChange(option.key); setOpen(false); }}><OptionIcon size={16} weight="duotone" /><span>{option.label}</span>{option.key === theme ? <Check size={14} /> : null}</button>; })}</div> : null}</div>;
}
