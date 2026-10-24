/**
 * LiveKit integration hook for Higgs Avatar video streams.
 *
 * When LiveKit credentials are configured on the server, this hook:
 * 1. Requests avatar sessions be created (POST /api/avatar/create)
 * 2. Gets a spectator token (GET /api/avatar/token)
 * 3. Connects to the LiveKit room
 * 4. Exposes per-seat video tracks for rendering in PlayerAvatar
 *
 * When LiveKit is unavailable, everything returns null/empty and
 * the CSS portrait fallback takes over.
 */

import { useCallback, useEffect, useRef, useState } from "react";

interface SeatVideoTrack {
  track: MediaStreamTrack;
  stream: MediaStream;
}

interface UseLiveKitReturn {
  available: boolean;
  connected: boolean;
  seatVideos: Record<number, SeatVideoTrack>;
  connect: () => Promise<void>;
  disconnect: () => void;
}

const SEAT_IDENTITIES = [
  "avatar-seat-0",
  "avatar-seat-1",
  "avatar-seat-2",
  "avatar-seat-3",
  "avatar-seat-4",
];

export function useLiveKit(): UseLiveKitReturn {
  const [available, setAvailable] = useState(false);
  const [connected, setConnected] = useState(false);
  const [seatVideos, setSeatVideos] = useState<Record<number, SeatVideoTrack>>({});
  const roomRef = useRef<any>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    fetch("/api/avatar/status")
      .then((r) => r.json())
      .then((data) => setAvailable(data.available === true))
      .catch(() => setAvailable(false));
  }, []);

  const connectToRoom = useCallback(async () => {
    if (!available) return;

    try {
      const createResp = await fetch("/api/avatar/create", { method: "POST" });
      if (!createResp.ok) return;

      const tokenResp = await fetch("/api/avatar/token");
      if (!tokenResp.ok) return;
      const { token, url } = await tokenResp.json();
      if (!token || !url) return;

      // Dynamically import livekit-client (only loaded when avatars are available)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let lk: any;
      try {
        const modName = "livekit-client";
        lk = await (Function("m", "return import(m)")(modName));
      } catch {
        console.warn("[livekit] livekit-client not installed, avatars unavailable");
        return;
      }

      const room = new lk.Room({
        adaptiveStream: true,
        dynacast: true,
      });

      roomRef.current = room;

      const updateTracks = () => {
        const videos: Record<number, SeatVideoTrack> = {};
        room.remoteParticipants.forEach((participant: any) => {
          const identity = participant.identity;
          const seatIdx = SEAT_IDENTITIES.indexOf(identity);
          if (seatIdx === -1) return;

          participant.videoTrackPublications.forEach((pub: any) => {
            if (pub.track && pub.track.mediaStreamTrack) {
              const msTrack = pub.track.mediaStreamTrack;
              const stream = new MediaStream([msTrack]);
              videos[seatIdx] = { track: msTrack, stream };
            }
          });
        });
        setSeatVideos(videos);
      };

      room.on(lk.RoomEvent.TrackSubscribed, updateTracks);
      room.on(lk.RoomEvent.TrackUnsubscribed, updateTracks);
      room.on(lk.RoomEvent.ParticipantConnected, updateTracks);
      room.on(lk.RoomEvent.ParticipantDisconnected, updateTracks);
      room.on(lk.RoomEvent.Disconnected, () => {
        setConnected(false);
        setSeatVideos({});
      });

      await room.connect(url, token);
      setConnected(true);
      updateTracks();

      cleanupRef.current = () => {
        room.disconnect();
        roomRef.current = null;
        setConnected(false);
        setSeatVideos({});
        fetch("/api/avatar/release", { method: "DELETE" }).catch(() => {});
      };
    } catch (e) {
      console.warn("[livekit] connection failed:", e);
      setConnected(false);
    }
  }, [available]);

  const disconnect = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      cleanupRef.current?.();
    };
  }, []);

  return {
    available,
    connected,
    seatVideos,
    connect: connectToRoom,
    disconnect,
  };
}
