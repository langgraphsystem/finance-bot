import { useCurrentFrame, interpolate, spring, useVideoConfig } from "remotion";

const BG = "#16161e";
const CARD_BG = "#1e1e2e";
const LIGHT = "#e0e0e0";
const DIM = "#888";

const habits = [
  { name: "Meditate", done: 6, total: 7, color: "#4ade80" },
  { name: "Workout", done: 5, total: 7, color: "#60a5fa" },
  { name: "Read", done: 4, total: 7, color: "#a78bfa" },
  { name: "Water", done: 7, total: 7, color: "#06b6d4" },
  { name: "Journal", done: 3, total: 7, color: "#fbbf24" },
];

export const WeeklyProgress = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const barMaxW = 260;

  return (
    <div
      style={{
        width: 440,
        height: 420,
        background: BG,
        fontFamily: "system-ui, sans-serif",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div
        style={{
          width: 410,
          background: CARD_BG,
          borderRadius: 16,
          padding: "18px 20px",
        }}
      >
        {/* Title */}
        <div
          style={{
            color: LIGHT,
            fontSize: 17,
            fontWeight: 600,
            marginBottom: 4,
            opacity: interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" }),
          }}
        >
          This Week — Habit Completion
        </div>
        <div
          style={{
            color: DIM,
            fontSize: 12,
            marginBottom: 18,
            opacity: interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" }),
          }}
        >
          Feb 14 – Feb 20, 2026
        </div>

        {/* Bars */}
        {habits.map((h, i) => {
          const delay = 8 + i * 6;
          const barProgress = spring({
            frame: frame - delay,
            fps,
            config: { damping: 15, stiffness: 80 },
          });
          const pct = h.done / h.total;
          const fillW = barMaxW * pct * barProgress;

          const labelOpacity = interpolate(frame - delay, [0, 8], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });

          // Score animation
          const scoreFrame = frame - delay - 10;
          const scoreScale = spring({
            frame: scoreFrame,
            fps,
            config: { damping: 10, stiffness: 150 },
          });

          return (
            <div key={h.name} style={{ marginBottom: 14 }}>
              {/* Label row */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 6,
                  opacity: labelOpacity,
                }}
              >
                <span style={{ color: LIGHT, fontSize: 14 }}>{h.name}</span>
                <span
                  style={{
                    color: h.done === h.total ? h.color : DIM,
                    fontSize: 13,
                    fontWeight: 600,
                    transform: `scale(${scoreScale})`,
                    display: "inline-block",
                  }}
                >
                  {h.done}/{h.total}
                </span>
              </div>

              {/* Bar */}
              <div
                style={{
                  width: barMaxW + 40,
                  height: 16,
                  background: "#2a2a3e",
                  borderRadius: 8,
                  overflow: "hidden",
                  position: "relative",
                }}
              >
                <div
                  style={{
                    width: fillW,
                    height: "100%",
                    background: h.color,
                    borderRadius: 8,
                    transition: "none",
                  }}
                />
              </div>
            </div>
          );
        })}

        {/* Summary */}
        <div
          style={{
            marginTop: 10,
            color: DIM,
            fontSize: 12,
            opacity: interpolate(frame, [65, 75], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          }}
        >
          Overall: 25/35 (71%) — Great week! 🔥
        </div>
      </div>
    </div>
  );
};
