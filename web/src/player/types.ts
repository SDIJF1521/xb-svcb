/** 播放器共享类型：队列、播放模式与音质信息。 */

export type PlayMode = 'order' | 'repeat' | 'single' | 'shuffle'

export type PlayerTrackKind = 'work' | 'local' | 'online'

/** 当前播放音频的技术信息（来自后端 ffprobe 或在线曲库描述）。 */
export interface PlayerAudioInfo {
  format?: string
  codec?: string
  sampleRate?: number
  bitDepth?: number
  channels?: number
  lossless?: boolean
  quality?: string
  size?: number
}

/** 队列中的一首歌。`url` 为运行时解析出的播放地址，不写入 localStorage。 */
export interface PlayerTrack {
  /** 队列内稳定的唯一键：work:<id> / local:<path> / online:<source>:<n>:<keyword>。 */
  key: string
  kind: PlayerTrackKind
  /** 作品 ID、本地路径或在线歌曲的定位串。 */
  id: string
  title: string
  subtitle: string
  album?: string
  duration?: number
  color: string
  audioInfo?: PlayerAudioInfo
  /** 本地歌曲路径（kind=local 时）。 */
  path?: string
  /** 作品 ID（kind=work 时，便于歌词 / MV 关联）。 */
  workId?: string
  /** 在线歌曲的解析参数。 */
  online?: {
    msg: string
    n: number
    source: string
    songId?: string
  }
  /** 已解析的播放地址（运行时）。 */
  url?: string
  /** 直通地址播放失败后是否已尝试 data URI 兜底。 */
  fallbackTried?: boolean
}
