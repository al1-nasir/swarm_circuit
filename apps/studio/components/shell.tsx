"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ArrowUpRight, ChevronLeft, ChevronRight, Plus, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { api } from "@/lib/api";
import type { Config, Run } from "@/lib/types";
import { Asset } from "./asset";

type OpenRun = Pick<Run, "run_id" | "name">;
const Project = createContext<{
  config: Config | null;
  health: string;
  error: string;
  refresh: () => void;
  rememberRun: (run: OpenRun) => void;
}>({
  config: null,
  health: "connecting",
  error: "",
  refresh: () => {},
  rememberRun: () => {},
});
export const useProject = () => useContext(Project);
const links = [
  { href: "/overview", label: "Overview" },
  { href: "/runs", label: "Workflows" },
  { href: "/demo", label: "Guided demo" },
];
const tools = [
  { href: "/incidents", label: "Findings" },
  { href: "/payments", label: "Payment evidence" },
  { href: "/experiments", label: "Comparisons" },
];
const storageKey = "swarmcircuit:open-runs:v1";
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [config, setConfig] = useState<Config | null>(null);
  const [health, setHealth] = useState("connecting");
  const [error, setError] = useState("");
  const [compact, setCompact] = useState(false);
  const [openRuns, setOpenRuns] = useState<OpenRun[]>([]);
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "[]");
      if (Array.isArray(saved))
        setOpenRuns(
          saved
            .filter(
              (r) =>
                typeof r.name === "string" && /^[0-9a-f-]{36}$/i.test(r.run_id),
            )
            .slice(-8),
        );
    } catch {
      /* A workspace can be used without persisted document tabs. */
    }
    setHydrated(true);
  }, []);
  useEffect(() => {
    if (hydrated)
      try {
        localStorage.setItem(storageKey, JSON.stringify(openRuns));
      } catch {
        /* Private browser storage can be unavailable. */
      }
  }, [openRuns, hydrated]);
  const rememberRun = useCallback(
    (run: OpenRun) =>
      setOpenRuns((old) => {
        if (old.some((r) => r.run_id === run.run_id && r.name === run.name))
          return old;
        return [
          ...old.filter((r) => r.run_id !== run.run_id),
          { run_id: run.run_id, name: run.name },
        ].slice(-8);
      }),
    [],
  );
  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/config", { cache: "no-store" });
      if (!response.ok) throw new Error("Check local Studio configuration.");
      const conf = (await response.json()) as Config;
      setConfig((old) =>
        old && JSON.stringify(old) === JSON.stringify(conf) ? old : conf,
      );
      const status = await api<{ status: string }>("health");
      setHealth(status.status);
      setError("");
    } catch (e) {
      setHealth("disconnected");
      setError(e instanceof Error ? e.message : "Backend unavailable.");
    }
  }, []);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 10000);
    return () => clearInterval(timer);
  }, [refresh]);
  function closeRun(id: string) {
    const remaining = openRuns.filter((r) => r.run_id !== id);
    setOpenRuns(remaining);
    if (path === `/runs/${id}`)
      router.push(
        remaining.length ? `/runs/${remaining.at(-1)!.run_id}` : "/runs",
      );
  }
  return (
    <Project.Provider
      value={{
        config,
        health,
        error,
        refresh: () => void refresh(),
        rememberRun,
      }}
    >
      <div className={`app-shell ${compact ? "compact-shell" : ""}`}>
        <a className="skip-link" href="#main">
          Skip to workspace
        </a>
        <aside className="sidebar" aria-label="Main navigation">
          <Link className="brand" href="/overview">
            <Asset name="flow-arrow" />
            <span>
              SwarmCircuit<small>AGENT WORKSPACE</small>
            </span>
          </Link>
          <div className="workspace-picker">
            <span className="workspace-icon">S</span>
            <span className="workspace-name">
              Local workspace<small>Development project</small>
            </span>
          </div>
          <div className="nav-caption">WORKSPACE</div>
          <nav>
            {links.map(({ href, label }, index) => (
              <Link
                key={href}
                href={href}
                className={`nav-link ${path.startsWith(href) ? "active" : ""}`}
                aria-current={path.startsWith(href) ? "page" : undefined}
                title={label}
              >
                <span className="nav-index">0{index + 1}</span>
                <span>{label}</span>
              </Link>
            ))}
            {tools.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className={`nav-link mobile-nav-item ${path.startsWith(href) ? "active" : ""}`}
                aria-current={path.startsWith(href) ? "page" : undefined}
              >
                {label}
              </Link>
            ))}
          </nav>
          <div className="nav-caption supporting-caption">
            INSPECT &amp; COMPARE
          </div>
          <nav className="supporting-nav" aria-label="Evidence and comparisons">
            {tools.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className={`nav-link ${path.startsWith(href) ? "active" : ""}`}
                aria-current={path.startsWith(href) ? "page" : undefined}
                title={label}
              >
                <span>{label}</span>
              </Link>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="local-card">
              <span
                className={`tiny-dot ${health === "ready" ? "online-dot" : ""}`}
              />
              <div>
                Backend {health}
                <small>
                  {config?.operator ? "Local operator" : "Read only"}
                </small>
              </div>
            </div>
            <Link className="nav-link" href="/settings/integrations">
              <span>Integrations</span>
              <ArrowUpRight size={14} />
            </Link>
            <Link className="nav-link" href="/setup">
              <span>SDK setup</span>
              <ArrowUpRight size={14} />
            </Link>
            <button
              className="collapse-button"
              onClick={() => setCompact((v) => !v)}
              aria-label={compact ? "Expand navigation" : "Collapse navigation"}
            >
              {compact ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
              <span>Collapse navigation</span>
            </button>
            <div className="version">
              LOCAL FIRST<span>v0.5.0</span>
            </div>
          </div>
        </aside>
        <div className="app-main">
          <header className="topbar">
            <Link className="workspace-home" href="/runs">
              Workspace<span>/</span>
              {path.includes("/runs/")
                ? "Workflow"
                : [...links, ...tools].find((l) => path.startsWith(l.href))
                    ?.label ||
                  (path === "/setup" ? "SDK setup" : "Integrations")}
            </Link>
            <span className="role-badge">
              {config?.operator ? "Operator" : "Read only"}
            </span>
          </header>
          {!!openRuns.length && (
            <nav className="document-tabs" aria-label="Open workflows">
              {openRuns.map((run) => (
                <div
                  key={run.run_id}
                  className={`document-tab ${path === `/runs/${run.run_id}` ? "active" : ""}`}
                >
                  <Link href={`/runs/${run.run_id}`} title={run.name}>
                    {run.name}
                  </Link>
                  <button
                    aria-label={`Close ${run.name}`}
                    onClick={() => closeRun(run.run_id)}
                  >
                    <X size={13} />
                  </button>
                </div>
              ))}
              <Link
                className="open-workflow"
                aria-label="Open another workflow"
                href="/runs"
              >
                <Plus size={15} />
              </Link>
            </nav>
          )}
          <main id="main">{children}</main>
          <footer className="app-footer">
            <span>
              <span className="tiny-dot" /> Local workspace
            </span>
            <span>Agent claims and source checks are shown separately</span>
          </footer>
        </div>
      </div>
    </Project.Provider>
  );
}
