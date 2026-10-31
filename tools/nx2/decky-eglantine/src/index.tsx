// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

import { callable, definePlugin } from "@decky/api";
import {
  ButtonItem,
  DialogButton,
  Focusable,
  PanelSection,
  PanelSectionRow,
  SliderField,
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

interface Build {
  available: boolean;
  busy?: boolean;
  current?: number[];
  latest?: number | null;
  update?: boolean;
  previous?: number | null;
  error?: string | null;
}

const GLOBAL_SCOPE = "global";
const POLL_MS = 3000;
const MESSAGE_MS = 5000;
// Steam gives each tick a minimum width. The ticks of a long list go past the right edge of the panel.
const MAX_TICKS = 9;

const getState = callable<[scope: string], State>("get_state");
const setSetting = callable<[scope: string, key: string, value: string], State>("set_setting");
const applyPreset = callable<[scope: string, preset: string], State>("apply_preset");
const checkBuild = callable<[], Build>("check_build");
const updateBuild = callable<[], Build>("update_build");
const rollbackBuild = callable<[], Build>("rollback_build");

function Note({ children }: { children: ReactNode }) {
  return (
    <PanelSectionRow>
      <div style={{ fontSize: "12px", lineHeight: "16px", opacity: 0.8, padding: "2px 0" }}>{children}</div>
    </PanelSectionRow>
  );
}

// A slider, not a dropdown: on the Legion Go at 2560x1600, the Quick Access view is 854 CSS pixels
// wide and only 348 show. Steam centres a dropdown menu in that view, so the screen edge cuts it.
function OptionSlider({
  label,
  options,
  selected,
  disabled,
  onChange,
}: {
  label: string;
  options: Option[];
  selected: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const index = Math.max(0, options.findIndex((o) => o.value === selected));
  const [shown, setShown] = useState(index);
  useEffect(() => setShown(index), [index]);
  const ticks = options.length <= MAX_TICKS;
  return (
    <PanelSectionRow>
      <SliderField
        label={`${label}: ${options[shown]?.label ?? ""}`}
        value={shown}
        min={0}
        max={options.length - 1}
        step={1}
        notchCount={ticks ? options.length : undefined}
        notchTicksVisible={ticks}
        disabled={disabled}
        bottomSeparator="none"
        onChange={(i) => {
          setShown(i);
          if (options[i] && options[i].value !== selected) onChange(options[i].value);
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

function BuildSection({ running }: { running: boolean }) {
  const [build, setBuild] = useState<Build | null>(null);
  const [working, setWorking] = useState<string | null>(null);

  const run = async (text: string | null, call: () => Promise<Build>) => {
    setWorking(text);
    try {
      setBuild(await call());
    } catch (e) {
      setBuild((b) => ({ ...(b ?? { available: true }), error: `Error del plugin: ${e}` }));
    } finally {
      setWorking(null);
    }
  };

  useEffect(() => {
    void run(null, checkBuild);
  }, []);

  // A download goes on when the panel closes. A panel that opens later looks again until it ends.
  useEffect(() => {
    if (!build?.busy) return undefined;
    const timer = setInterval(() => void run(null, checkBuild), POLL_MS);
    return () => clearInterval(timer);
  }, [build?.busy]);

  if (!build?.available) return null;
  const blocked = running || working !== null || !!build.busy;
  const status = build.current ? `Build ${build.current.join(" y ")}.` : "";
  const next = build.update ? ` Hay build ${build.latest}.` : build.latest ? " No hay otra más nueva." : "";
  return (
    <PanelSection title="Build">
      <Note>{working ?? (build.busy ? "Descargando una build..." : status + next)}</Note>
      {build.error && <Note>{build.error}</Note>}
      {running && (build.update || build.previous) && <Note>Cierra Eglantine para cambiar de build.</Note>}
      {build.update && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={blocked}
            onClick={() => void run(`Descargando build ${build.latest}...`, updateBuild)}
          >
            Actualizar a build {build.latest}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {build.previous && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={blocked}
            onClick={() => void run(`Volviendo a build ${build.previous}...`, rollbackBuild)}
          >
            Volver a build {build.previous}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

function Content() {
  const [state, setState] = useState<State | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const calls = useRef(0);
  const scope = useRef("");

  const run = async (call: () => Promise<State>, isWrite: boolean) => {
    calls.current++;
    try {
      const next = await call();
      scope.current = next.scope;
      setState(next);
      if (isWrite) setMessage(next.error ?? "Guardado. Se aplica al siguiente arranque.");
    } catch (e) {
      setMessage(`Error del plugin: ${e}`);
    } finally {
      calls.current--;
    }
  };

  useEffect(() => {
    void run(() => getState(""), false);
    const timer = setInterval(() => {
      // A poll waits for open calls, so that it cannot hide the result of a write.
      if (calls.current === 0) void run(() => getState(scope.current), false);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (message === null) return undefined;
    const timer = setTimeout(() => setMessage(null), MESSAGE_MS);
    return () => clearTimeout(timer);
  }, [message]);

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
    byKey[key] && (
      <OptionSlider
        label={byKey[key].label}
        options={byKey[key].options}
        selected={byKey[key].selected}
        disabled={locked}
        onChange={(v) => write(key, v)}
      />
    );

  return (
    <>
    <PanelSection>
      <OptionSlider
        label="Ajustes de"
        options={[
          { value: GLOBAL_SCOPE, label: "Global" },
          ...state.titles.map((t) => ({ value: t.id, label: t.name })),
        ]}
        selected={state.scope}
        onChange={(v) => void run(() => getState(v), false)}
      />
      <Note>{message ?? applyNote(state)}</Note>

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
    <BuildSection running={state.running} />
    </>
  );
}

export default definePlugin(() => ({
  name: "Eglantine",
  titleView: <div className={staticClasses.Title}>Eglantine</div>,
  content: <Content />,
  icon: <FaSlidersH />,
}));
