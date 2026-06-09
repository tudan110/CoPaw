import * as echarts from "echarts";

let ready = false;
let inflight: Promise<void> | null = null;

export function isChinaMapReady(): boolean {
  return ready;
}

export function __resetChinaMapForTest(): void {
  ready = false;
  inflight = null;
}

export async function ensureChinaMap(): Promise<void> {
  if (ready) return;
  if (!inflight) {
    inflight = fetch("/geo/china.json")
      .then((r) => r.json())
      .then((geo) => {
        echarts.registerMap("china", geo);
        ready = true;
      });
  }
  await inflight;
}
