import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Plays per-seat speech sent over the game socket (base64 WAV from Higgs TTS) and reports
 * each seat's live level. Used only when that seat has no LiveKit avatar.
 */
interface SeatChannel {
  analyser: AnalyserNode;
  queue: Promise<void>;
  playing: boolean;
}

export function useAudio() {
  const ctxRef = useRef<AudioContext | null>(null);
  const gainRef = useRef<GainNode | null>(null);
  const seatsRef = useRef<Map<number, SeatChannel>>(new Map());
  const [levels, setLevels] = useState<Record<number, number>>({});
  const [isMuted, setIsMuted] = useState(false);

  const getCtx = useCallback(() => {
    if (!ctxRef.current) {
      const ctx = new AudioContext();
      const gain = ctx.createGain();
      gain.connect(ctx.destination);
      ctxRef.current = ctx;
      gainRef.current = gain;
    }
    if (ctxRef.current.state === "suspended") void ctxRef.current.resume();
    return ctxRef.current;
  }, []);

  const channel = useCallback(
    (seat: number) => {
      let ch = seatsRef.current.get(seat);
      if (!ch) {
        const ctx = getCtx();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        analyser.connect(gainRef.current!);
        ch = { analyser, queue: Promise.resolve(), playing: false };
        seatsRef.current.set(seat, ch);
      }
      return ch;
    },
    [getCtx]
  );

  const playAudio = useCallback(
    (seat: number, base64Wav: string) => {
      const ctx = getCtx();
      const ch = channel(seat);
      const bytes = Uint8Array.from(atob(base64Wav), (c) => c.charCodeAt(0));
      ch.queue = ch.queue.then(async () => {
        try {
          const buffer = await ctx.decodeAudioData(bytes.buffer.slice(0));
          await new Promise<void>((resolve) => {
            const source = ctx.createBufferSource();
            source.buffer = buffer;
            source.connect(ch.analyser);
            source.onended = () => {
              ch.playing = false;
              resolve();
            };
            ch.playing = true;
            source.start();
          });
        } catch (e) {
          console.warn("[audio] could not play speech", e);
        }
      });
    },
    [getCtx, channel]
  );

  const setMuted = useCallback((muted: boolean) => {
    setIsMuted(muted);
    const ctx = ctxRef.current;
    if (gainRef.current && ctx) gainRef.current.gain.setTargetAtTime(muted ? 0 : 1, ctx.currentTime, 0.05);
  }, []);

  /** Browsers block audio until a user gesture; call this from a click. */
  const unlock = useCallback(() => {
    getCtx();
  }, [getCtx]);

  useEffect(() => {
    let frame = 0;
    const data = new Uint8Array(256);
    const tick = () => {
      const next: Record<number, number> = {};
      seatsRef.current.forEach((ch, seat) => {
        if (!ch.playing) {
          next[seat] = 0;
          return;
        }
        ch.analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const v of data) sum += ((v - 128) / 128) ** 2;
        next[seat] = Math.min(1, Math.sqrt(sum / data.length) * 5);
      });
      setLevels((prev) => {
        const same = Object.keys(next).every((k) => Math.abs((prev[+k] ?? 0) - next[+k]) < 0.02);
        return same && Object.keys(prev).length === Object.keys(next).length ? prev : next;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => () => void ctxRef.current?.close(), []);

  return { playAudio, levels, setMuted, isMuted, unlock };
}
