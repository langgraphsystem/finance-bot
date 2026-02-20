import { useCurrentFrame, interpolate, spring, useVideoConfig } from "remotion";

const BG = "#16161e";
const CARD_BG = "#1e1e2e";
const GREEN = "#4ade80";
const YELLOW = "#fbbf24";
const RED = "#ef4444";
const LIGHT = "#e0e0e0";
const DIM = "#888";

const statuses = [
  "done","done","done","skip","done","done","miss",
  "done","done","done","done","done","done","done",
  "done","done","done","done","skip","done","miss",
  "done","done","done","skip","done","done","done",
];

const colorMap = { done: GREEN, skip: YELLOW, miss: RED };
const dayLabels = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

export const HabitTracker = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cell = 42;
  const gap = 6;
  const x0 = 30;
  const y0 = 90;
  const offset = 6; // Feb 2026 starts Sunday

  return (
    <div style={{ width: 440, height: 400, background: BG, fontFamily: "system-ui, sans-serif" }}>
      <div
        style={{
          margin: "10px 15px",
          padding: "12px 15px",
          background: CARD_BG,
          borderRadius: 16,
          height: 370,
          position: "relative",
        }}
      >
        {/* Title */}
        <div style={{ color: LIGHT, fontSize: 18, fontWeight: 600 }}>Meditation</div>
        <div style={{ color: DIM, fontSize: 13, marginTop: 2 }}>February 2026</div>

        {/* Day headers */}
        <div style={{ display: "flex", position: "absolute", top: 60, left: 15 }}>
          {dayLabels.map((d, i) => (
            <div
              key={d}
              style={{
                width: cell,
                marginRight: gap,
                textAlign: "center",
                color: DIM,
                fontSize: 12,
              }}
            >
              {d}
            </div>
          ))}
        </div>

        {/* Grid cells — animate one by one */}
        {statuses.map((status, dayIdx) => {
          const pos = dayIdx + offset;
          const col = pos % 7;
          const row = Math.floor(pos / 7);
          const x = x0 - 15 + col * (cell + gap);
          const y = y0 - 10 + row * (cell + gap);

          // Staggered reveal: each cell appears 1.5 frames apart
          const delay = dayIdx * 1.5;
          const scale = spring({ frame: frame - delay, fps, config: { damping: 12, stiffness: 120 } });
          const opacity = interpolate(frame - delay, [0, 5], [0, 1], { extrapolateRight: "clamp" });

          return (
            <div
              key={dayIdx}
              style={{
                position: "absolute",
                left: x,
                top: y,
                width: cell,
                height: cell,
                borderRadius: 8,
                background: colorMap[status],
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: BG,
                fontSize: 14,
                fontWeight: 600,
                transform: `scale(${scale})`,
                opacity,
              }}
            >
              {dayIdx + 1}
            </div>
          );
        })}

        {/* Legend */}
        <div
          style={{
            position: "absolute",
            bottom: 32,
            left: 15,
            display: "flex",
            gap: 24,
            opacity: interpolate(frame, [50, 60], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          }}
        >
          {[
            ["Done", GREEN],
            ["Skipped", YELLOW],
            ["Missed", RED],
          ].map(([label, color]) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 14, height: 14, borderRadius: 3, background: color }} />
              <span style={{ color: DIM, fontSize: 12 }}>{label}</span>
            </div>
          ))}
        </div>

        {/* Stats */}
        <div
          style={{
            position: "absolute",
            bottom: 10,
            left: 15,
            color: DIM,
            fontSize: 12,
            opacity: interpolate(frame, [55, 65], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          }}
        >
          Streak: 5d | Rate: 21/28 (75%)
        </div>
      </div>
    </div>
  );
};
