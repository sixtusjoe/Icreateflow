// noVNC ships no types. Only the handful of members this app touches are
// declared — a fuller shim would be guesswork about a library we drive
// through four properties and two events.
declare module "@novnc/novnc" {
  export default class RFB {
    constructor(target: HTMLElement, url: string, options?: Record<string, unknown>);
    scaleViewport: boolean;
    resizeSession: boolean;
    disconnect(): void;
    addEventListener(type: string, listener: (event: unknown) => void): void;
  }
}
