export interface PendingAudio {
  name: string
  path: string
  hint?: string
}

let pendingAudio: PendingAudio | null = null

export function setPendingAudio(audio: PendingAudio) {
  pendingAudio = audio
}

export function takePendingAudio(): PendingAudio | null {
  const audio = pendingAudio
  pendingAudio = null
  return audio
}
