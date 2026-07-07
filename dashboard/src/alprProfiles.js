export const ALPR_PROFILES = [
  {
    id: "sharp_read",
    label: "Sharp read",
    short: "SHARP",
    resolution: "2304x1296",
    fps: 24,
    processFps: 12,
    purpose: "plate detail",
    bitrate: "10 Mbps",
  },
  {
    id: "fast_lane",
    label: "Fast lane",
    short: "FAST",
    resolution: "1920x1080",
    fps: 60,
    processFps: 30,
    purpose: "motion freeze",
    bitrate: "12 Mbps",
  },
  {
    id: "track_boost",
    label: "Track boost",
    short: "TRACK",
    resolution: "1280x720",
    fps: 60,
    processFps: 45,
    purpose: "smooth tracking",
    bitrate: "8 Mbps",
  },
  {
    id: "night_boost",
    label: "Night boost",
    short: "NIGHT",
    resolution: "1920x1080",
    fps: 20,
    processFps: 10,
    purpose: "low light / IR",
    bitrate: "9 Mbps",
  },
  {
    id: "pi_economy",
    label: "Pi economy",
    short: "ECO",
    resolution: "1280x720",
    fps: 30,
    processFps: 8,
    purpose: "low heat",
    bitrate: "5 Mbps",
  },
];

export function profileById(id) {
  return ALPR_PROFILES.find((p) => p.id === id) || ALPR_PROFILES[0];
}
