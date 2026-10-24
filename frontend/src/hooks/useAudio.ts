import { useCallback, useEffect, useRef, useState } from "react";

const SAMPLE_RATE = 24000;
const CHANNELS = 1;
const RMS_SMOOTHING = 0.3;

interface SeatAudioState {
  queue: AudioBuffer[];
  isPlaying: boolean;
  level: number;
  sourceNode: AudioBufferSourceNode | null;
}

interface UseAudioReturn {
  audioLevels: Record<number, number>;
  isSpeaking: Record<number, boolean>;
  playAudioChunk: (seat: number, base64Pcm: string) => void;
  connectRealtimeAudio: (seat: number, wsUrl: string) => void;
  disconnectRealtimeAudio: (seat: number) => void;
  setMuted: (muted: boolean) => void;
  isMuted: boolean;
}

function decodeBase64Pcm(ctx: AudioContext, base64: string): AudioBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const int16 = new Int16Array(bytes.buffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 32768;
  }
  const buffer = ctx.createBuffer(CHANNELS, float32.length, SAMPLE_RATE);
  buffer.copyToChannel(float32, 0);
  return buffer;
}

function computeRms(buffer: AudioBuffer): number {
  const data = buffer.getChannelData(0);
  let sum = 0;
  const step = Math.max(1, Math.floor(data.length / 256));
  let count = 0;
  for (let i = 0; i < data.length; i += step) {
    sum += data[i] * data[i];
    count++;
  }
  return Math.sqrt(sum / count);
}

export function useAudio(): UseAudioReturn {
  const ctxRef = useRef<AudioContext | null>(null);
  const gainRef = useRef<GainNode | null>(null);
  const seatsRef = useRef<Map<number, SeatAudioState>>(new Map());
  const realtimeWsRef = useRef<Map<number, WebSocket>>(new Map());
  const [audioLevels, setAudioLevels] = useState<Record<number, number>>({});
  const [isSpeaking, setIsSpeaking] = useState<Record<number, boolean>>({});
  const [isMuted, setIsMutedState] = useState(false);
  const animFrameRef = useRef<number>(0);

  const getCtx = useCallback(() => {
    if (!ctxRef.current) {
      ctxRef.current = new AudioContext({ sampleRate: SAMPLE_RATE });
      gainRef.current = ctxRef.current.createGain();
      gainRef.current.connect(ctxRef.current.destination);
    }
    if (ctxRef.current.state === "suspended") {
      ctxRef.current.resume();
    }
    return ctxRef.current;
  }, []);

  const getSeatState = useCallback((seat: number): SeatAudioState => {
    let s = seatsRef.current.get(seat);
    if (!s) {
      s = { queue: [], isPlaying: false, level: 0, sourceNode: null };
      seatsRef.current.set(seat, s);
    }
    return s;
  }, []);

  const updateLevels = useCallback(() => {
    const levels: Record<number, number> = {};
    const speaking: Record<number, boolean> = {};
    seatsRef.current.forEach((s, seat) => {
      levels[seat] = s.level;
      speaking[seat] = s.isPlaying;
    });
    setAudioLevels(levels);
    setIsSpeaking(speaking);
  }, []);

  const playNext = useCallback(
    (seat: number) => {
      const ctx = getCtx();
      const s = getSeatState(seat);

      if (s.queue.length === 0) {
        s.isPlaying = false;
        s.level = 0;
        updateLevels();
        return;
      }

      s.isPlaying = true;
      const buffer = s.queue.shift()!;
      const rms = computeRms(buffer);
      s.level = s.level * RMS_SMOOTHING + rms * (1 - RMS_SMOOTHING);
      s.level = Math.min(1, s.level * 4);

      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(gainRef.current!);
      s.sourceNode = source;

      source.onended = () => {
        s.sourceNode = null;
        playNext(seat);
      };

      source.start();
      updateLevels();
    },
    [getCtx, getSeatState, updateLevels]
  );

  const playAudioChunk = useCallback(
    (seat: number, base64Pcm: string) => {
      const ctx = getCtx();
      const s = getSeatState(seat);
      const buffer = decodeBase64Pcm(ctx, base64Pcm);
      s.queue.push(buffer);

      if (!s.isPlaying) {
        playNext(seat);
      }
    },
    [getCtx, getSeatState, playNext]
  );

  const connectRealtimeAudio = useCallback(
    (seat: number, wsUrl: string) => {
      const existing = realtimeWsRef.current.get(seat);
      if (existing) {
        existing.close();
      }

      const ws = new WebSocket(wsUrl);
      realtimeWsRef.current.set(seat, ws);

      ws.onmessage = (event) => {
        let msg: { type?: string; audio?: string };
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        if (msg.type === "audio" && msg.audio) {
          playAudioChunk(seat, msg.audio);
        }
      };

      ws.onclose = () => {
        realtimeWsRef.current.delete(seat);
        const s = getSeatState(seat);
        s.isPlaying = false;
        s.level = 0;
        updateLevels();
      };
    },
    [playAudioChunk, getSeatState, updateLevels]
  );

  const disconnectRealtimeAudio = useCallback((seat: number) => {
    const ws = realtimeWsRef.current.get(seat);
    if (ws) {
      ws.close();
      realtimeWsRef.current.delete(seat);
    }
  }, []);

  const setMuted = useCallback(
    (muted: boolean) => {
      setIsMutedState(muted);
      if (gainRef.current) {
        gainRef.current.gain.setTargetAtTime(
          muted ? 0 : 1,
          ctxRef.current?.currentTime ?? 0,
          0.05
        );
      }
    },
    []
  );

  useEffect(() => {
    let running = true;
    const tick = () => {
      if (!running) return;
      updateLevels();
      animFrameRef.current = requestAnimationFrame(tick);
    };
    animFrameRef.current = requestAnimationFrame(tick);
    return () => {
      running = false;
      cancelAnimationFrame(animFrameRef.current);
    };
  }, [updateLevels]);

  useEffect(() => {
    return () => {
      realtimeWsRef.current.forEach((ws) => ws.close());
      realtimeWsRef.current.clear();
      ctxRef.current?.close();
    };
  }, []);

  return {
    audioLevels,
    isSpeaking,
    playAudioChunk,
    connectRealtimeAudio,
    disconnectRealtimeAudio,
    setMuted,
    isMuted,
  };
}
