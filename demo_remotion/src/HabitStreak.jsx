import { useCurrentFrame, interpolate, spring, useVideoConfig } from "remotion";

const BG = "#16161e";
const GREEN = "#4ade80";
const RED = "#ef4444";
const LIGHT = "#e0e0e0";
const DIM = "#888";

// Streak data: 20 days
const streakData = [1,2,3,4,5,6,0,1,2,3,4,5,6,7,8,9,10,11,0,1];
const days = Array.from({ length: 20 }, (_, i) => `Feb ${i + 1}`);

export const HabitStreak = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const W = 500;
  const H = 300;
  const padLeft = 50;
  const padRight = 20;
  const padTop = 50;
  const padBottom = 40;
  const chartW = W - padLeft - padRight;
  const chartH = H - padTop - padBottom;
  const maxVal = Math.max(...streakData);

  // How many points to reveal — animate progressively
  const revealCount = interpolate(frame, [0, 60], [0, streakData.length], {
    extrapolateRight: "clamp",
  });

  const points = streakData.slice(0, Math.ceil(revealCount)).map((val, i) => ({
    x: padLeft + (i / (streakData.length - 1)) * chartW,
    y: padTop + chartH - (val / maxVal) * chartH,
    val,
    isMiss: val === 0,
  }));

  // Build SVG path
  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  // Area path
  const areaD = pathD + ` L ${points[points.length - 1]?.x ?? padLeft} ${padTop + chartH} L ${padLeft} ${padTop + chartH} Z`;

  // Title fade
  const titleOpacity = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });

  // Y-axis labels
  const yTicks = [0, 3, 6, 9, 12];

  return (
    <div style={{ width: W, height: H, background: BG, fontFamily: "system-ui, sans-serif", position: "relative" }}>
      {/* Title */}
      <div
        style={{
          position: "absolute",
          top: 12,
          left: 0,
          width: "100%",
          textAlign: "center",
          color: LIGHT,
          fontSize: 15,
          fontWeight: 600,
          opacity: titleOpacity,
        }}
      >
        Meditation — Streak History
      </div>

      <svg width={W} height={H}>
        {/* Grid lines */}
        {yTicks.map((tick) => {
          const y = padTop + chartH - (tick / maxVal) * chartH;
          return (
            <g key={tick}>
              <line x1={padLeft} y1={y} x2={W - padRight} y2={y} stroke="#333" strokeWidth={0.5} />
              <text x={padLeft - 8} y={y + 4} fill={DIM} fontSize={10} textAnchor="end">
                {tick}
              </text>
            </g>
          );
        })}

        {/* Y-axis label */}
        <text
          x={14}
          y={padTop + chartH / 2}
          fill={DIM}
          fontSize={10}
          textAnchor="middle"
          transform={`rotate(-90, 14, ${padTop + chartH / 2})`}
        >
          Consecutive days
        </text>

        {/* Area fill — animated */}
        {points.length > 1 && (
          <path d={areaD} fill={GREEN} fillOpacity={0.2} />
        )}

        {/* Line — animated */}
        {points.length > 1 && (
          <path d={pathD} fill="none" stroke={GREEN} strokeWidth={2.5} />
        )}

        {/* Points */}
        {points.map((p, i) => (
          <circle
            key={i}
            cx={p.x}
            cy={p.y}
            r={p.isMiss ? 5 : 3}
            fill={p.isMiss ? RED : GREEN}
            stroke={p.isMiss ? "white" : "none"}
            strokeWidth={p.isMiss ? 1 : 0}
          />
        ))}

        {/* X-axis labels (every 4th) */}
        {points.filter((_, i) => i % 4 === 0).map((p, i) => (
          <text key={i} x={p.x} y={H - 12} fill={DIM} fontSize={9} textAnchor="middle">
            {days[i * 4]}
          </text>
        ))}
      </svg>
    </div>
  );
};
