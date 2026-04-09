interface Props {
  level: "critical" | "urgent" | "routine";
  summary: string;
}

const CONFIG = {
  critical: {
    bg: "bg-red-950/60",
    border: "border-red-500 animate-pulse-border",
    icon: "\u{1F6A8}",
    label: "CRITICAL",
    labelColor: "text-red-400",
  },
  urgent: {
    bg: "bg-amber-950/40",
    border: "border-amber-500",
    icon: "\u26A0\uFE0F",
    label: "URGENT",
    labelColor: "text-amber-400",
  },
  routine: {
    bg: "bg-slate-800/40",
    border: "border-slate-600",
    icon: "\u2714\uFE0F",
    label: "ROUTINE",
    labelColor: "text-slate-400",
  },
};

export default function RiskBanner({ level, summary }: Props) {
  const c = CONFIG[level];
  return (
    <div
      className={`${c.bg} border ${c.border} border-l-4 rounded px-5 py-3 flex items-center gap-3`}
    >
      <span className="text-lg">{c.icon}</span>
      <span className={`font-bold tracking-wide text-sm ${c.labelColor}`}>
        {c.label}
      </span>
      <span className="text-sm text-slate-300">{summary}</span>
    </div>
  );
}
