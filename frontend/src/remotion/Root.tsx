import React from "react";
import { Composition } from "remotion";
import { AudioVideoComposition, type CompositionProps } from "./AudioVideoComposition";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="AudioVideo"
      component={AudioVideoComposition}
      durationInFrames={30 * 30} // default 30s at 30fps, overridden at render time
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{
        themeId: "minimal" as const,
        accentColor: "#00FFAA",
        textGlow: "0 0 15px rgba(0,255,170,0.5)",
        bgImageUrl: null,
        coverImageUrl: null,
        audioUrl: null,
        words: [],
        clipStartS: 0,
        clipDuration: 30,
      } satisfies CompositionProps}
    />
  );
};
