import { Icon, Tag } from "@blueprintjs/core";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { Clock } from "./Clock";
import { SCREENS, type Screen } from "./screens";
import { UserMenu } from "./UserMenu";

function NavList() {
  let group: Screen["group"] | null = null;
  const items = [];
  for (const screen of SCREENS) {
    if (screen.group !== group) {
      group = screen.group;
      items.push(
        <div key={`g-${group}`} className="nx-nav-group">
          {group}
        </div>,
      );
    }
    items.push(
      <NavLink
        key={screen.path}
        to={screen.path}
        end={screen.path === "/"}
        className={({ isActive }) => `nx-nav${isActive ? " nx-nav-active" : ""}`}
      >
        <Icon icon={screen.icon} size={14} />
        {screen.title}
      </NavLink>,
    );
  }
  return <nav aria-label="Main">{items}</nav>;
}

interface Props {
  onLogout: () => void;
}

export function AppShell({ onLogout }: Props) {
  const { pathname } = useLocation();
  const current = SCREENS.find((s) => s.path === pathname);

  return (
    <div className="nx-app">
      <aside className="nx-aside">
        <div className="nx-brand">
          <svg viewBox="0 0 40 40" aria-hidden="true">
            <circle cx="20" cy="20" r="15" fill="none" stroke="#4C90F0" strokeWidth="4" />
            <circle cx="20" cy="20" r="6" fill="#4C90F0" />
          </svg>
          <b>NEXIRA</b>
        </div>
        <NavList />
      </aside>
      <main className="nx-main">
        <header className="nx-header">
          <div>
            <h1>{current?.title ?? "Not found"}</h1>
            <div className="nx-crumb">{current?.subtitle}</div>
          </div>
          <span className="nx-grow" />
          <Tag intent="warning" minimal>
            SIMULATED DATA
          </Tag>
          <Clock />
          <UserMenu onLogout={onLogout} />
        </header>
        <section className="nx-view">
          <Outlet />
        </section>
      </main>
    </div>
  );
}
