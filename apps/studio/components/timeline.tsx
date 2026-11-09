"use client";
import { ArrowDown, Clock3, ListFilter, Radio, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { duration, short, spanDuration, time } from "@/lib/model";
import type { Evidence } from "@/lib/types";
import { Empty, Trust } from "./ui";

export function Timeline({
  items,
  selected,
  onSelect,
  hasOlder,
  onOlder,
}: {
  items: Evidence[];
  selected: string | null;
  onSelect: (id: string) => void;
  hasOlder: boolean;
  onOlder: () => void;
}) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [scroll, setScroll] = useState(0);
  const viewport = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setScroll(0);
    viewport.current?.scrollTo(0, 0);
  }, [filter, query]);
  const rows = useMemo(
    () =>
      items
        .filter(
          (e) =>
            (filter === "all" || e.item_type === filter) &&
            (e.label + " " + e.id + " " + (e.task_id || ""))
              .toLowerCase()
              .includes(query.toLowerCase()),
        )
        .sort(
          (a, b) =>
            a.occurred_at_ms - b.occurred_at_ms || a.id.localeCompare(b.id),
        ),
    [items, filter, query],
  );
  const first = rows[0]?.occurred_at_ms || 0;
  const last = Math.max(
    first + 1,
    ...rows.map((i) => i.occurred_at_ms + (spanDuration(i) || 0)),
  );
  const windowMs = last - first;
  const height = 70;
  const start = Math.max(0, Math.floor(scroll / height) - 5);
  const visible = rows.slice(start, start + 22);
  return (
    <section className="panel timeline-panel">
      <div className="table-toolbar">
        <div className="segmented">
          {["all", "event", "span"].map((k) => (
            <button
              key={k}
              className={filter === k ? "active" : ""}
              onClick={() => {
                setFilter(k);
                setScroll(0);
                viewport.current?.scrollTo(0, 0);
              }}
            >
              {k === "all"
                ? "All evidence"
                : k === "event"
                  ? "Lifecycle events"
                  : "Trace spans"}
            </button>
          ))}
        </div>
        <label className="search-box">
          <Search size={14} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Filter timeline"
            placeholder="Filter loaded evidence…"
          />
        </label>
      </div>
      <div className="timeline-scope">
        <Clock3 size={14} />
        <span>
          Loaded window: {time(first)} – {time(last)} UTC
        </span>
        <span>
          {rows.length} records · {duration(windowMs)}
        </span>
      </div>
      {!rows.length ? (
        <Empty title="No evidence in this window">
          <p>Lifecycle events and trace spans appear after ingestion.</p>
        </Empty>
      ) : (
        <>
          <div className="timeline-columns">
            <span>EVENT / OPERATION</span>
            <span>RELATIVE TIME</span>
            <span>UTC</span>
          </div>
          <div
            ref={viewport}
            className="timeline-viewport"
            aria-label="Timeline evidence"
            onScroll={(e) => setScroll(e.currentTarget.scrollTop)}
          >
            <div style={{ height: rows.length * height, position: "relative" }}>
              {visible.map((item, index) => {
                const d = spanDuration(item);
                const offset = Math.max(
                  0,
                  ((item.occurred_at_ms - first) / windowMs) * 100,
                );
                return (
                  <button
                    type="button"
                    aria-pressed={selected === item.id}
                    id={`timeline-${item.id}`}
                    key={item.id}
                    className={`timeline-row ${selected === item.id ? "selected" : ""}`}
                    style={{ top: (start + index) * height, height }}
                    onClick={() => {
                      onSelect(item.id);
                    }}
                  >
                    <div className="timeline-name">
                      <span className={`evidence-dot ${item.item_type}`} />
                      <div>
                        <strong>{item.label}</strong>
                        <small>
                          <Trust value={item.trust_class} />
                          <span className="mono">
                            {short(item.task_id || item.trace_id || item.id)}
                          </span>
                        </small>
                      </div>
                    </div>
                    <div className="waterfall-track">
                      <div
                        className={`waterfall-bar ${item.item_type}`}
                        style={{
                          left: `${Math.min(94, offset)}%`,
                          width: `${d === null ? 1 : Math.max(1, Math.min(100 - offset, (d / windowMs) * 100))}%`,
                        }}
                      />
                      <span>
                        {d === null
                          ? `+${duration(item.occurred_at_ms - first)}`
                          : duration(d)}
                      </span>
                    </div>
                    <span className="mono metadata">
                      {time(item.occurred_at_ms)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}
      <div className="table-footer">
        <span>Source time · nanosecond IDs remain exact in the inspector</span>
        {hasOlder && (
          <button className="button small" onClick={onOlder}>
            <ArrowDown size={13} />
            Load older evidence
          </button>
        )}
      </div>
    </section>
  );
}
