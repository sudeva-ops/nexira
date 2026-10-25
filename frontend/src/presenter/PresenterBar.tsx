import { Icon } from "@blueprintjs/core";
import { useNavigate } from "react-router-dom";

import { hasRole, useMe } from "../api/me";
import { DEMO_SCENARIO, useScenario, useScenarioCommand } from "../api/scenario";
import { demoMode } from "../app/demo";
import { SCENE_SCREEN } from "./scenes";

/** Demo mode only: drives the scenario through the scenario API (PLT-06). The
 *  scenes with data (1, 4) play events; the others are moments for the people
 *  in the room to act (approve PB-07, decide the evacuation, close the incident). */
export function PresenterBar() {
  const me = useMe().data;
  const operator = hasRole(me, "ADMIN") || hasRole(me, "DUTY_OFFICER");
  const enabled = demoMode() && operator;
  const { data: state } = useScenario(DEMO_SCENARIO, enabled);
  const command = useScenarioCommand(DEMO_SCENARIO);
  const navigate = useNavigate();
  if (!enabled || !state) return null;

  const current = state.current_scene;
  const last = state.scenes.length - 1;
  const scene = state.scenes[current];
  const run = (c: "play" | "pause" | "next" | "reset") =>
    command.mutate(c, {
      onSuccess: (next) => {
        if (c === "next" || c === "reset") void navigate(SCENE_SCREEN[next.current_scene] ?? "/");
      },
    });

  return (
    <div className="nx-presenter" role="toolbar" aria-label="Presenter">
      <div className="lbl">
        DEMO SCENARIO
        <b>{state.name}</b>
      </div>
      <button type="button" className="pbtn" title="Reset to scene 0" aria-label="Reset" onClick={() => run("reset")}>
        <Icon icon="reset" size={12} />
      </button>
      {state.scenes.map((s) => (
        <span
          key={s.scene_no}
          className={`sc${s.scene_no < current ? " done" : s.scene_no === current ? " on" : ""}`}
          title={s.expect ?? s.name}
          aria-current={s.scene_no === current ? "step" : undefined}
        >
          <span className="n">{s.scene_no < current ? "✓" : s.scene_no}</span>
          {s.scene_no === current && s.name}
        </span>
      ))}
      {state.status === "PLAYING" ? (
        <button type="button" className="pbtn" aria-label="Pause" onClick={() => run("pause")}>
          <Icon icon="pause" size={12} />
        </button>
      ) : (
        <button
          type="button"
          className="pbtn"
          aria-label="Play scene"
          disabled={state.scene_complete || state.status === "FINISHED"}
          onClick={() => run("play")}
        >
          <Icon icon="play" size={12} />
        </button>
      )}
      <button
        type="button"
        className="pbtn play"
        aria-label="Next scene"
        disabled={current >= last && state.status === "FINISHED"}
        onClick={() => run("next")}
      >
        <Icon icon="arrow-right" size={12} />
      </button>
      {scene?.expect && <div className="nx-presenter-expect">{scene.expect}</div>}
    </div>
  );
}
