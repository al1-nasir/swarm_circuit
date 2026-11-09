"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiWindow } from "./api";
import { createInvalidator } from "./invalidation";
import { mergeById, mergePage } from "./model";
import type {
  Approval,
  Command,
  Evidence,
  Graph,
  Incident,
  Page,
  Payment,
  Run,
  Runtime,
  Snapshot,
} from "./types";

export function useRun(runId: string) {
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState(0);
  const [live, setLive] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const generation = useRef(0);
  const busy = useRef("");
  const again = useRef(false);
  const connected = useRef(false);
  const latest = useRef(data);
  latest.current = data;
  const currentId = useRef(runId);
  currentId.current = runId;
  const refresh = useCallback(async () => {
    if (busy.current === runId) {
      again.current = true;
      return;
    }
    busy.current = runId;
    const current = generation.current;
    setRefreshing(true);
    try {
      const base = `runs/${runId}`;
      const [
        run,
        taskGraph,
        agentGraph,
        timeline,
        incidents,
        approvals,
        payments,
        runtimes,
        commands,
      ] = await Promise.all([
        api<Run>(base),
        api<Graph>(base + "/graph?view=task"),
        api<Graph>(base + "/graph?view=agent"),
        api<Page<Evidence>>(base + "/timeline?limit=100"),
        api<Page<Incident>>(base + "/incidents"),
        apiWindow<Approval>(
          base + "/approvals",
          latest.current?.run.run_id === runId
            ? latest.current.approvals.items.length
            : 200,
          200,
        ),
        apiWindow<Payment>(
          base + "/payments",
          latest.current?.run.run_id === runId
            ? latest.current.payments.items.length
            : 200,
          200,
        ),
        api<{ items: Runtime[] }>(base + "/runtime-sessions"),
        apiWindow<Command>(
          base + "/control-commands",
          latest.current?.run.run_id === runId
            ? latest.current.commands.items.length
            : 100,
          100,
        ),
      ]);
      if (current !== generation.current || currentId.current !== runId) return;
      setData((old) => ({
        run,
        taskGraph,
        agentGraph,
        timeline:
          old && old.run.run_id === runId
            ? mergePage(old.timeline, timeline, (i) => i.id)
            : timeline,
        incidents: incidents.items,
        approvals:
          old && old.run.run_id === runId
            ? mergePage(old.approvals, approvals, (i) => i.approval_id)
            : approvals,
        payments:
          old && old.run.run_id === runId
            ? mergePage(old.payments, payments, (i) => i.payment_intent_id)
            : payments,
        runtimes: runtimes.items,
        commands:
          old && old.run.run_id === runId
            ? mergePage(old.commands, commands, (i) => i.command_id)
            : commands,
      }));
      setUpdated(Date.now());
      setError("");
      setLive(connected.current);
    } catch (e) {
      if (current === generation.current)
        setError(e instanceof Error ? e.message : "Snapshot unavailable.");
    } finally {
      if (busy.current === runId) busy.current = "";
      if (currentId.current === runId) setRefreshing(false);
      if (again.current && currentId.current === runId) {
        again.current = false;
        void refresh();
      }
    }
  }, [runId]);
  useEffect(() => {
    generation.current++;
    connected.current = false;
    setData(null);
    setLive(false);
    setError("");
    setUpdated(0);
    void refresh();
    let disposed = false;
    let socket: WebSocket | null = null;
    let reconnect: ReturnType<typeof setTimeout>;
    const invalidator = createInvalidator(() => void refresh());
    let attempt = 0;
    let cursor: number | null = null;
    const seen = new Set<string>();
    const schedule = invalidator.schedule;
    function connect() {
      if (disposed) return;
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/studio-ws/${runId}${cursor !== null ? "?after=" + cursor : ""}`,
      );
      socket.onmessage = (message) => {
        if (disposed) return;
        let batch;
        try {
          batch = JSON.parse(message.data);
        } catch {
          socket?.close();
          return;
        }
        if (batch.run_id !== runId) {
          socket?.close();
          return;
        }
        connected.current = true;
        attempt = 0;
        if (batch.type === "snapshot_required") {
          setLive(false);
          cursor = batch.cursor;
          void refresh();
          return;
        }
        if (batch.type === "notifications") {
          let changed = false;
          for (const item of batch.notifications) {
            if (seen.has(item.notification_id)) continue;
            if (cursor !== null && item.sequence !== cursor + 1) {
              seen.clear();
              schedule();
            }
            seen.add(item.notification_id);
            cursor = item.sequence;
            changed = true;
          }
          if (seen.size > 1000) seen.clear();
          if (changed) schedule();
        }
      };
      socket.onclose = () => {
        if (disposed) return;
        connected.current = false;
        setLive(false);
        reconnect = setTimeout(connect, Math.min(5000, 500 * 2 ** attempt++));
      };
      socket.onerror = () => socket?.close();
    }
    connect();
    const interval = setInterval(() => void refresh(), 10000);
    const focus = () => void refresh();
    window.addEventListener("focus", focus);
    return () => {
      disposed = true;
      generation.current++;
      invalidator.cancel();
      clearTimeout(reconnect);
      clearInterval(interval);
      window.removeEventListener("focus", focus);
      socket?.close();
    };
  }, [runId, refresh]);
  async function older(
    kind: "timeline" | "commands" | "payments" | "approvals",
  ) {
    const cursor = data?.[kind].next_cursor;
    if (!cursor) return;
    const path = kind === "commands" ? "control-commands" : kind;
    try {
      const page = await api<Page<Evidence | Command | Payment | Approval>>(
        `runs/${runId}/${path}?limit=100&cursor=${encodeURIComponent(cursor)}`,
      );
      setData((old) => {
        if (!old || old.run.run_id !== runId) return old;
        const identify = (i: Evidence | Command | Payment | Approval) =>
          "id" in i
            ? i.id
            : "command_id" in i
              ? i.command_id
              : "payment_intent_id" in i
                ? i.payment_intent_id
                : i.approval_id;
        return {
          ...old,
          [kind]: {
            items: mergeById(
              old[kind].items as (Evidence | Command | Payment | Approval)[],
              page.items,
              identify,
            ),
            next_cursor: page.next_cursor,
          },
        };
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Older records unavailable.");
    }
  }
  return { data, error, updated, live, refreshing, refresh, older };
}
