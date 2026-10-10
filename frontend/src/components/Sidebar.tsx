import {
  ArrowLeftRight,
  ChartNoAxesCombined,
  Gift,
  LayoutDashboard,
  Settings2,
  Sparkles,
  Target,
  WalletCards,
  type LucideIcon,
} from "lucide-react";
import type { View } from "../App";

interface NavigationItem {
  label: string;
  view: View;
  icon: LucideIcon;
}

const primaryItems: NavigationItem[] = [
  { label: "Overview", view: "overview", icon: LayoutDashboard },
  { label: "Portfolio", view: "portfolio", icon: ChartNoAxesCombined },
  { label: "Goals", view: "goals", icon: Target },
  { label: "Cash flow", view: "cashflow", icon: ArrowLeftRight },
  { label: "Equity & deposits", view: "compensation", icon: Gift },
];

const mobileItems: NavigationItem[] = [
  { label: "Overview", view: "overview", icon: LayoutDashboard },
  { label: "Portfolio", view: "portfolio", icon: ChartNoAxesCombined },
  { label: "Goals", view: "goals", icon: Target },
  { label: "Cash flow", view: "cashflow", icon: ArrowLeftRight },
  { label: "Assistant", view: "assistant", icon: Sparkles },
];

interface SidebarProps {
  activeView: View;
  onNavigate: (view: View) => void;
}

export function Sidebar({ activeView, onNavigate }: SidebarProps) {
  return (
    <aside className="sidebar">
      <a className="brand" href="#" aria-label="Northstar home" onClick={(event) => {
        event.preventDefault();
        onNavigate("overview");
      }}>
        <span className="brand-mark"><span /></span>
        <span className="brand-name">northstar</span>
      </a>

      <div className="sidebar-label">Workspace</div>
      <nav className="nav-list" aria-label="Main navigation">
        {primaryItems.map(({ label, view, icon: Icon }) => (
          <button
            key={view}
            className={`nav-item ${activeView === view ? "active" : ""}`}
            onClick={() => onNavigate(view)}
            aria-current={activeView === view ? "page" : undefined}
          >
            <Icon size={18} strokeWidth={1.8} />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar-divider" />
      <div className="sidebar-label">Plan & learn</div>
      <nav className="nav-list" aria-label="Planning navigation">
        <button
          className={`nav-item ${activeView === "assistant" ? "active" : ""}`}
          onClick={() => onNavigate("assistant")}
          aria-current={activeView === "assistant" ? "page" : undefined}
        >
          <Sparkles size={18} strokeWidth={1.8} />
          <span>AI assistant</span>
          <span className="nav-new">NEW</span>
        </button>
        <button
          className={`nav-item ${activeView === "goals" ? "active" : ""}`}
          onClick={() => onNavigate("goals")}
        >
          <WalletCards size={18} strokeWidth={1.8} />
          <span>Financial plan</span>
        </button>
      </nav>

      <nav className="mobile-nav" aria-label="Mobile navigation">
        {mobileItems.map(({ label, view, icon: Icon }) => (
          <button
            key={view}
            className={`nav-item ${activeView === view ? "active" : ""}`}
            onClick={() => onNavigate(view)}
            aria-current={activeView === view ? "page" : undefined}
            aria-label={label}
          >
            <Icon size={18} strokeWidth={1.8} />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar-spacer" />
      <div className="sidebar-note">
        <div className="sidebar-note-icon"><Settings2 size={16} /></div>
        <div>
          <strong>Built around you</strong>
          <span>Your goals, your rules.</span>
        </div>
      </div>
      <button className="profile-button" type="button" onClick={() => onNavigate("overview")}>
        <span className="profile-avatar">DP</span>
        <span className="profile-copy">
          <strong>Demo portfolio</strong>
          <span>Personal workspace</span>
        </span>
        <span className="profile-status" aria-label="Demo environment" />
      </button>
    </aside>
  );
}
