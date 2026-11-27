/** 把作品 / 在线歌曲 / 已下载歌曲转换成统一的播放队列项。 */

import { pickColor } from '@/api'
import type { DownloadedMusic, MusicSearchItem, WorkDTO } from '@/api'
import type { PlayerTrack } from './types'

/** 解析作品列表里的时长文本（"3:24" / "1:02:03"）。 */
export function parseDurationLabel(label?: string): number {
  const text = String(label || '').trim()
  if (!text) return 0
  const parts = text.split(':').map((part) => Number(part))
  if (!parts.length || parts.some((part) => !Number.isFinite(part) || part < 0)) return 0
  return parts.reduce((total, part) => total * 60 + part, 0)
}

export function workToTrack(work: WorkDTO): PlayerTrack {
  return {
    key: `work:${work.id}`,
    kind: 'work',
    id: work.id,
    workId: work.id,
    title: work.title || '未命名作品',
    subtitle: work.model || 'AI 翻唱',
    album: '翻唱作品',
    duration: parseDurationLabel(work.duration),
    color: pickColor(work.id),
  }
}

export function onlineToTrack(
  item: MusicSearchItem,
  context: { keyword: string; source: string },
): PlayerTrack {
  const rider = [item.singer, item.album].filter(Boolean).join(' · ')
  return {
    key: `online:${context.source}:${item.n}:${context.keyword}`,
    kind: 'online',
    id: `online:${context.source}:${item.n}`,
    title: item.name || `歌曲 ${item.n}`,
    subtitle: rider || '在线曲库',
    album: item.album || context.keyword,
    duration: 0,
    color: pickColor(`${context.source}:${item.n}:${context.keyword}`),
    online: {
      msg: context.keyword,
      n: item.n,
      source: context.source,
      songId: String(item.rid || '').trim() || undefined,
    },
  }
}

export function localToTrack(item: DownloadedMusic): PlayerTrack {
  return {
    key: `local:${item.path}`,
    kind: 'local',
    id: item.path,
    path: item.path,
    title: item.name || '本地歌曲',
    subtitle: `已下载 · ${item.size || '本地音乐'}`,
    album: '已下载素材',
    duration: 0,
    color: pickColor(item.path),
  }
}
