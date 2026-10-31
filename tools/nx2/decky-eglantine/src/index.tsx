// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

import { callable, definePlugin } from "@decky/api";
import {
  ButtonItem,
  DialogButton,
  DropdownItem,
  Focusable,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import { ReactNode, useEffect, useRef, useState } from "react";
import { FaSlidersH } from "react-icons/fa";

interface Option {
  value: string;
  label: string;
}

interface Setting {
  key: string;
  label: string;
  options: Option[];
  selected: string;
  effective: string | null;
}

interface State {
  found: boolean;
  scope: string;
  running: boolean;
  titles: { id: string; name: string }[];
  settings: Setting[];
  dma: string | null;
  presets: { id: string; label: string }[];
  lsfg_ready: boolean;
  error: string | null;
}

const GLOBAL_SCOPE = "global";
const POLL_MS = 3000;

const getState = callable<[scope: string], State>("get_state");
const setSetting = callable<[scope: string, key: string, value: string], State>("set_setting");
const applyPreset = callable<[scope: string, preset: string], State>("apply_preset");

function Note({ children }: { children: ReactNode }) {
  return (
    <PanelSectionRow>
      <div style={{ fontSize: "12px", lineHeight: "16px", opacity: 0.8, padding: "2px 0" }}>{children}</div>
    </PanelSectionRow>
  );
}

function SettingRow({
  setting,
  disabled,
  onChange,
}: {
  setting: Setting;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <PanelSectionRow>
      <DropdownItem
        label={setting.label}
        disabled={disabled}
        rgOptions={setting.options.map((o) => ({ data: o.value, label: o.label }))}
        selectedOption={setting.selected}
        onChange={(o) => {
          if (o.data !== setting.selected) onChange(o.data);
        }}
      />
    </PanelSectionRow>
  );
}

function applyNote(state: State): string {
  if (!state.running) return "Se aplica al siguiente arranque del juego.";
  if (state.scope === GLOBAL_SCOPE) return "Eglantine está abierto. Ciérralo para cambiar lo global.";
  return "Juego en marcha. Se aplica al volver a arrancarlo.";
}

function Content() {
  const [state, setState] = useState<State | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const busy = useRef(false);
  const scope = useRef("");

  // One call at a time, so that a poll cannot hide the result of a write.
  const run = async (call: () => Promise<State>, isWrite: boolean) => {
    busy.current = true;
    try {
      const next = await call();
      scope.current = next.scope;
      setState(next);
      if (isWrite) setMessage(next.error ?? "Guardado.");
    } catch (e) {
      setMessage(`Error del plugin: ${e}`);
    } finally {
      busy.current = false;
    }
  };

  useEffect(() => {
    void run(() => getState(""), false);
    const timer = setInterval(() => {
      if (!busy.current) void run(() => getState(scope.current), false);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, []);

  if (state === null) {
    return (
      <PanelSection>
        <Note>{message ?? "Leyendo ajustes..."}</Note>
      </PanelSection>
    );
  }
  if (!state.found) {
    return (
      <PanelSection>
        <Note>No encuentro ~/.config/eden/qt-config.ini. Abre Eglantine una vez.</Note>
      </PanelSection>
    );
  }

  const locked = state.running && state.scope === GLOBAL_SCOPE;
  const byKey = Object.fromEntries(state.settings.map((s) => [s.key, s]));
  const frameGenOn = byKey.frame_gen?.effective === "true";
  const multiplier = Number(byKey.frame_gen_multiplier?.effective ?? "2");
  const write = (key: string, value: string) => void run(() => setSetting(state.scope, key, value), true);
  const row = (key: string) =>
    byKey[key] && <SettingRow setting={byKey[key]} disabled={locked} onChange={(v) => write(key, v)} />;

  return (
    <PanelSection>
      <PanelSectionRow>
        <DropdownItem
          label="Ajustes de"
          layout="below"
          rgOptions={[
            { data: GLOBAL_SCOPE, label: "Global" },
            ...state.titles.map((t) => ({ data: t.id, label: t.name })),
          ]}
          selectedOption={state.scope}
          onChange={(o) => {
            setMessage(null);
            void run(() => getState(o.data), false);
          }}
        />
      </PanelSectionRow>
      <Note>{applyNote(state)}</Note>
      {message && <Note>{message}</Note>}

      <PanelSectionRow>
        <Focusable style={{ display: "flex", gap: "4px" }} flow-children="horizontal">
          {state.presets.map((p) => (
            <DialogButton
              key={p.id}
              disabled={locked}
              style={{ flex: 1, minWidth: 0, padding: "8px 0" }}
              onClick={() => void run(() => applyPreset(state.scope, p.id), true)}
            >
              {p.label}
            </DialogButton>
          ))}
        </Focusable>
      </PanelSectionRow>

      {row("resolution_setup")}
      {row("scaling_filter")}
      {row("gpu_accuracy")}
      {byKey.gpu_accuracy?.effective === "1" && <Note>Accurate deja apagado el hilo GPU partido.</Note>}
      {row("use_docked_mode")}
      {row("frame_gen")}
      {frameGenOn && (
        <>
          <Note>
            Con FG, VSync va en FIFO. La base máxima es Hz ÷ {multiplier}: a 60 Hz, {Math.floor(60 / multiplier)} FPS.
          </Note>
          {row("frame_gen_multiplier")}
          {byKey.frame_gen_type?.effective === "0" && !state.lsfg_ready && (
            <Note>LSFG necesita Lossless.dll en ~/.local/share/eden/lossless. Sin él no genera fotogramas.</Note>
          )}
          {row("frame_gen_type")}
        </>
      )}

      {state.dma !== null && state.dma !== "0" && (
        <>
          <Note>
            DMA en {state.dma === "2" ? "Safe" : "Unsafe"}, fijado a mano.
            {state.dma === "2" && " Deja apagado el hilo GPU partido."}
          </Note>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={locked} onClick={() => write("dma_accuracy", "0")}>
              Poner DMA en Default
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
}

export default definePlugin(() => ({
  name: "Eglantine",
  titleView: <div className={staticClasses.Title}>Eglantine</div>,
  content: <Content />,
  icon: <FaSlidersH />,
}));
