import { Composition } from "remotion";
import { HabitTracker } from "./HabitTracker";
import { HabitStreak } from "./HabitStreak";
import { WeeklyProgress } from "./WeeklyProgress";

export const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="HabitTracker"
        component={HabitTracker}
        durationInFrames={90}
        fps={30}
        width={440}
        height={400}
      />
      <Composition
        id="HabitStreak"
        component={HabitStreak}
        durationInFrames={90}
        fps={30}
        width={500}
        height={300}
      />
      <Composition
        id="WeeklyProgress"
        component={WeeklyProgress}
        durationInFrames={90}
        fps={30}
        width={440}
        height={420}
      />
    </>
  );
};
