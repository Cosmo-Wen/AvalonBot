/**
 * Higgs Avatar video via LiveKit.
 *
 * `start()` asks the server to start one avatar per seat (POST /api/avatar/start), then joins the
 * room as a subscriber. Each avatar publishes lip-synced video plus its speech audio; seats without
 * an avatar fall back to the portrait and the WebSocket audio.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ConnectionState, Room, RoomEvent, Track, type RemoteParticipant, type RemoteTrack, type RemoteTrackPublication } from "livekit-client";

export type AvatarStatus = "checking" | "unavailable" | "idle" | "starting" | "connected" | "error";

const seatOf = (identity: string): number | null => {
  const m = /^avatar-seat-(\d)$/.exec(identity);
  return m ? Number(m[1]) : null;
};

export function useLiveKit() {
  const [status, setStatus] = useState<AvatarStatus>("checking");
  const [message, setMessage] = useState<string>("");
  const [seatVideos, setSeatVideos] = useState<Record<number, RemoteTrack>>({});
  const [levels, setLevels] = useState<Record<number, number>>({});
  const roomRef = useRef<Room | null>(null);
  const audioEls = useRef<Map<string, HTMLMediaElement>>(new Map());
  const mutedRef = useRef(false);

  const refresh = useCallback(() => {
    const room = roomRef.current;
    if (!room) return;
    const videos: Record<number, RemoteTrack> = {};
    room.remoteParticipants.forEach((p: RemoteParticipant) => {
      const seat = seatOf(p.identity);
      if (seat === null) return;
      p.trackPublications.forEach((pub: RemoteTrackPublication) => {
        if (pub.kind !== Track.Kind.Video) return;
        // LiveKit pauses a video track that was never attached to an element, so subscribe
        // explicitly and let the seat attach it.
        if (!pub.isSubscribed) pub.setSubscribed(true);
        if (pub.track) videos[seat] = pub.track;
      });
    });
    setSeatVideos((prev) => {
      const same =
        Object.keys(prev).length === Object.keys(videos).length &&
        Object.entries(videos).every(([seat, track]) => prev[Number(seat)] === track);
      return same ? prev : videos;
    });
  }, []);

  const connect = useCallback(async () => {
    if (roomRef.current && roomRef.current.state !== ConnectionState.Disconnected) return;
    roomRef.current = null;
    const tokenResp = await fetch("/api/avatar/token");
    if (!tokenResp.ok) throw new Error(`token request failed (${tokenResp.status})`);
    const { token, url } = await tokenResp.json();

    const room = new Room();
    roomRef.current = room;
    room
      .on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === Track.Kind.Audio) {
          const el = track.attach();
          el.muted = mutedRef.current;
          el.style.display = "none";
          document.body.appendChild(el);
          audioEls.current.set(track.sid ?? String(Math.random()), el);
        }
        refresh();
      })
      .on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
        if (track.kind === Track.Kind.Audio) {
          track.detach().forEach((el) => el.remove());
          if (track.sid) audioEls.current.delete(track.sid);
        }
        refresh();
      })
      .on(RoomEvent.TrackPublished, refresh)
      .on(RoomEvent.ParticipantConnected, refresh)
      .on(RoomEvent.ParticipantDisconnected, refresh)
      .on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        const next: Record<number, number> = {};
        for (const p of speakers) {
          const seat = seatOf(p.identity);
          if (seat !== null) next[seat] = Math.min(1, p.audioLevel * 3);
        }
        setLevels(next);
      })
      .on(RoomEvent.Disconnected, () => {
        if (roomRef.current !== room) return;
        roomRef.current = null;
        setSeatVideos({});
        setStatus("idle");
      });

    await room.connect(url, token);
    await room.startAudio().catch(() => undefined);
    setStatus("connected");
    refresh();
  }, [refresh]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/avatar/status")
      .then((r) => r.json())
      .then(async (info) => {
        if (cancelled) return;
        if (!info.available) {
          setStatus("unavailable");
          return;
        }
        setStatus("idle");
        const running = Object.values(info.seats ?? {}).some((s) => (s as { ready: boolean }).ready);
        if (running) await connect().catch(() => setStatus("idle"));
      })
      .catch(() => !cancelled && setStatus("unavailable"));
    return () => {
      cancelled = true;
    };
  }, [connect]);

  // Avatars can join after we do. Keep looking so a seat never stays on its shield.
  useEffect(() => {
    const id = setInterval(() => {
      if (roomRef.current?.state === ConnectionState.Connected) refresh();
    }, 2000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(
    () => () => {
      roomRef.current?.disconnect();
      audioEls.current.forEach((el) => el.remove());
    },
    []
  );

  /** Starts the seat avatars on the server (can take ~30 s) and joins their room. */
  const start = useCallback(async () => {
    setStatus("starting");
    setMessage("");
    try {
      const resp = await fetch("/api/avatar/start", { method: "POST" });
      const info = await resp.json();
      if (!resp.ok) throw new Error(info.error ?? `start failed (${resp.status})`);
      const errors = Object.entries(info.errors ?? {});
      if (errors.length) {
        const text = (e: unknown) => /"message":\s*"([^"]+)"/.exec(String(e))?.[1] ?? String(e).slice(0, 80);
        setMessage(`Avatar failed for seat ${errors.map(([s, e]) => `${s} (${text(e)})`).join(", ")}`);
      }
      await connect();
      setStatus("connected");
      refresh();
      roomRef.current?.startAudio().catch(() => undefined);
    } catch (e) {
      setStatus("error");
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }, [connect, refresh]);

  const stop = useCallback(async () => {
    roomRef.current?.disconnect();
    roomRef.current = null;
    setSeatVideos({});
    await fetch("/api/avatar/release", { method: "DELETE" }).catch(() => undefined);
    setStatus("idle");
  }, []);

  const setMuted = useCallback((muted: boolean) => {
    mutedRef.current = muted;
    audioEls.current.forEach((el) => (el.muted = muted));
  }, []);

  return { status, message, seatVideos, levels, start, stop, setMuted };
}
