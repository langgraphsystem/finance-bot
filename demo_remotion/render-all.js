const { execSync } = require("child_process");
const path = require("path");

const compositions = ["HabitTracker", "HabitStreak", "WeeklyProgress"];

// Render still frames (last frame) for preview
for (const comp of compositions) {
  console.log(`\n📸 Rendering still: ${comp}...`);
  try {
    execSync(
      `npx remotion still ${comp} out/${comp}_still.png --frame=80`,
      { stdio: "inherit", cwd: __dirname }
    );
  } catch (e) {
    console.error(`Failed to render ${comp} still:`, e.message);
  }
}

// Render MP4 videos
for (const comp of compositions) {
  console.log(`\n🎬 Rendering video: ${comp}...`);
  try {
    execSync(
      `npx remotion render ${comp} out/${comp}.mp4`,
      { stdio: "inherit", cwd: __dirname }
    );
  } catch (e) {
    console.error(`Failed to render ${comp} video:`, e.message);
  }
}

console.log("\n✅ All renders complete! Check demo_remotion/out/");
