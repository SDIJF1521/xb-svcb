/** 播放器展示用的文本格式化。 */

import type { PlayerAudioInfo } from './types'

/** 秒 -> m:ss / h:mm:ss。 */
export function formatTime(value: number): string {
  const seconds = Math.max(0, Math.floor(Number(value) || 0))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const rest = seconds % 60
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
  }
  return `${minutes}:${String(rest).padStart(2, '0')}`
}

/** 队列总时长；未知时长按 0 计。 */
export function formatTotalDuration(seconds: number): string {
  if (!seconds || seconds < 1) return ''
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟`
  const hours = Math.floor(minutes / 60)
  return `${hours} 小时 ${minutes % 60} 分钟`
}

export function formatSampleRate(rate?: number): string {
  if (!rate || rate <= 0) return ''
  const khz = rate / 1000
  return `${Number.isInteger(khz) ? khz.toFixed(0) : khz.toFixed(1)} kHz`
}

export function formatChannels(channels?: number): string {
  if (!channels || channels <= 0) return ''
  return channels === 1 ? '单声道' : channels === 2 ? '立体声' : `${channels} 声道`
}

/** 音质徽标：无损 / 高品质 / 格式名。 */
export function audioQualityBadge(info?: PlayerAudioInfo): string {
  if (!info) return ''
  if (info.lossless) return 'HiFi 无损'
  if (info.quality) return info.quality.replace(/[[\]]/g, '')
  if (info.format) return String(info.format).toUpperCase()
  return ''
}

/** 详细参数：FLAC · 44.1 kHz · 16 bit · 立体声。 */
export function audioDetailLabel(info?: PlayerAudioInfo): string {
  if (!info) return ''
  const parts: string[] = []
  if (info.format) parts.push(String(info.format).toUpperCase())
  if (info.bitDepth) parts.push(`${info.bitDepth} bit`)
  const rate = formatSampleRate(info.sampleRate)
  if (rate) parts.push(rate)
  const channels = formatChannels(info.channels)
  if (channels) parts.push(channels)
  if (!parts.length && info.quality) parts.push(info.quality)
  return parts.join(' · ')
}
