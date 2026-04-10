interface Props {
  level: "critical" | "urgent" | "routine";
  summary: string;
}

const CONFIG = {
  critical: {
    bg: "bg-red-50",
    border: "border-red-400 animate-pulse-border",
    icon: "\u{1F6A8}",
    label: "CRITICAL",
    labelBg: "bg-red-500 text-white",
    textColor: "text-red-700",
  },
  urgent: {
    bg: "bg-amber-50",
    border: "border-amber-400",
    icon: "\u26A0\uFE0F",
    label: "URGENT",
    labelBg: "bg-amber-500 text-white",
    textColor: "text-amber-700",
  },
  routine: {
    bg: "bg-gray-50",
    border: "border-gray-300",
    icon: "\u2714\uFE0F",
    label: "ROUTINE",
    labelBg: "bg-gray-400 text-white",
    textColor: "text-gray-600",
  },
};

export default function RiskBanner({ level, summary }: Props) {
  const c = CONFIG[level];
  return (
    <div
      className={`${c.bg} border ${c.border} border-l-4 rounded px-5 py-3 flex items-center gap-3 shadow-sm`}
    >
      <span className="text-lg">{c.icon}</span>
      <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${c.labelBg}`}>
        {c.label}
      </span>
      <span className={`text-sm ${c.textColor}`}>{summary}</span>
    </div>
  );
}
