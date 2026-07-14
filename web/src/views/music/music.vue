<template>
  <div class="page">
    <audio ref="audioEl" style="display: none" @ended="playingN = null" @pause="onAudioPause" />

    <!-- 页面标题 -->
    <div class="page-head">
      <div>
        <p class="eyebrow">// 资源获取</p>
        <h1>在线曲库</h1>
        <p class="page-sub">搜索并下载歌曲素材，下载后可直接在「AI 翻唱」中选用</p>
      </div>
      <el-button size="large" round class="ghost-btn" @click="openSettings">
        <el-icon class="el-icon--left"><Setting /></el-icon>API 设置
      </el-button>
    </div>

    <!-- 未配置 Key 提示 -->
    <div v-if="!hasKey" class="notice glass">
      <el-icon class="notice-ic"><Key /></el-icon>
      <div class="notice-main">
        <div class="notice-title">尚未配置 API Key</div>
        <div class="notice-sub">在线曲库由妖狐 API 提供，需填写你自己的接口密钥后才能搜索与下载。</div>
      </div>
      <el-button round class="cta-btn" @click="openSettings">前往设置</el-button>
    </div>

    <!-- 搜索栏 -->
    <div class="toolbar glass">
      <div class="source-field">
        <el-select v-model="source" class="source-select" @change="onSourceChange">
          <el-option v-for="s in sources" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
      </div>
      <div class="search">
        <el-icon><Search /></el-icon>
        <input
          v-model="keyword"
          type="text"
          placeholder="输入歌曲名 / 歌手，如：洛天依 知我…"
          @keyup.enter="doSearch"
        />
        <button v-if="keyword" class="search-clear" title="清除" @click="keyword = ''">
          <el-icon><Close /></el-icon>
        </button>
      </div>
      <el-button round class="cta-btn" :loading="searching" :disabled="!hasKey" @click="doSearch">
        <el-icon v-if="!searching" class="el-icon--left"><Search /></el-icon>搜索
      </el-button>
    </div>

    <!-- 搜索结果 -->
    <div v-if="results.length" class="block">
      <div class="block-head">
        <h2>搜索结果</h2>
        <span class="muted">{{ resultSourceName }} ·「{{ resultKeyword }}」· {{ results.length }} 首</span>
      </div>
      <div class="list glass">
        <div class="row" v-for="r in results" :key="r.n">
          <span class="row-no">{{ r.n }}</span>
          <button
            class="row-play"
            :title="playingN === r.n ? '暂停' : '试听'"
            :disabled="previewLoadingN === r.n"
            @click="togglePreview(r)"
          >
            <el-icon v-if="previewLoadingN === r.n" class="spin"><Loading /></el-icon>
            <el-icon v-else-if="playingN === r.n"><VideoPause /></el-icon>
            <el-icon v-else><VideoPlay /></el-icon>
          </button>
          <div class="row-main">
            <div class="row-title" :title="r.name">
              {{ r.name }}<span v-if="r.pay" class="pay-tag">{{ payLabel(r.pay) }}</span>
              <span v-if="isUnplayable(r.n)" class="dead-tag">不可播放</span>
            </div>
            <div class="row-sub">{{ r.singer }}<span v-if="r.album"> · {{ r.album }}</span></div>
          </div>
          <div class="row-ops">
            <el-button
              round
              size="small"
              class="ghost-btn"
              :loading="downloadingN === r.n"
              :disabled="isUnplayable(r.n)"
              :title="isUnplayable(r.n) ? '该资源不可播放，无法下载' : '下载'"
              @click="doDownload(r)"
            >
              <el-icon v-if="downloadingN !== r.n" class="el-icon--left"><Download /></el-icon>
              下载
            </el-button>
            <el-button
              round
              size="small"
              class="cta-btn"
              :loading="toCreateN === r.n"
              :disabled="isUnplayable(r.n)"
              @click="downloadAndCreate(r)"
            >
              <el-icon v-if="toCreateN !== r.n" class="el-icon--left"><Microphone /></el-icon>
              去翻唱
            </el-button>
          </div>
        </div>
      </div>
    </div>
    <div v-else-if="searched && !searching" class="empty glass">
      <el-icon class="empty-icon"><Search /></el-icon>
      <p class="empty-title">没有找到「{{ resultKeyword }}」相关歌曲</p>
      <p class="empty-sub">换个关键词试试吧</p>
    </div>

    <!-- 已下载 -->
    <div class="block">
      <div class="block-head">
        <h2>已下载素材</h2>
        <span class="muted">{{ downloaded.length }} 首 · 可在翻唱页选用</span>
      </div>
      <div v-if="downloaded.length" class="list glass">
        <div class="row" v-for="d in downloaded" :key="d.path">
          <div class="row-cover"><el-icon><Headset /></el-icon></div>
          <div class="row-main">
            <div class="row-title" :title="d.name">{{ d.name }}</div>
            <div class="row-sub">{{ d.size }}</div>
          </div>
          <div class="row-ops">
            <el-button round size="small" class="cta-btn" @click="useForCreate(d)">
              <el-icon class="el-icon--left"><Microphone /></el-icon>去翻唱
            </el-button>
            <button class="op danger" title="删除" @click="removeDownloaded(d)">
              <el-icon><Delete /></el-icon>
            </button>
          </div>
        </div>
      </div>
      <div v-else class="empty glass small">
        <span>暂无下载素材，搜索后点击「下载」即可保存到本地。</span>
      </div>
    </div>

    <!-- API 设置弹窗 -->
    <el-dialog v-model="settingsVisible" title="音乐 API 设置" width="460px" class="api-dialog">
      <div class="dialog-body">
        <p class="dialog-tip">
          在线曲库由
          <a href="https://api.yaohud.cn" target="_blank" rel="noreferrer">妖狐 API</a>
          提供。请在其控制台 → 密钥管理获取 Key 后填入下方。Key 仅保存在本地。
        </p>
        <label class="dialog-label">API Key</label>
        <el-input
          v-model="keyDraft"
          type="password"
          show-password
          placeholder="粘贴你的接口密钥"
          size="large"
        />
        <template v-if="cookieSupported">
          <label class="dialog-label">QQ音乐会员 Cookie（选填）</label>
          <el-input
            v-model="cookieDraft"
            type="textarea"
            :rows="3"
            placeholder="uin=xxx;qqmusic_key=xxx"
            resize="none"
          />
          <p class="dialog-tip" style="margin: 0">
            填写 QQ音乐会员 Cookie 后，可解析并下载高品质（320 / flac）音频。仅保存在本地。
          </p>
        </template>
      </div>
      <template #footer>
        <el-button round @click="settingsVisible = false">取消</el-button>
        <el-button round class="cta-btn" :loading="savingKey" @click="saveKey">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  Search,
  Close,
  VideoPlay,
  VideoPause,
  Loading,
  Download,
  Microphone,
  Headset,
  Delete,
  Setting,
  Key,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type MusicSearchItem, type DownloadedMusic, type MusicSource } from '@/api'

defineOptions({ name: 'MusicPage' })

const router = useRouter()

const hasKey = ref(false)
const keyword = ref('')
const searching = ref(false)
const searched = ref(false)
const results = ref<MusicSearchItem[]>([])
const resultKeyword = ref('')

/* ----- 曲库（网易云 / QQ音乐）----- */
const sources = ref<MusicSource[]>([{ id: 'wy', name: '网易云音乐', cookie: false }])
const source = ref('wy')
// 当前结果对应的曲库（预览 / 下载必须与搜索时一致）
const resultSource = ref('wy')
const cookieSupported = computed(() => sources.value.find((s) => s.id === source.value)?.cookie ?? false)
const resultSourceName = computed(() =>
  sources.value.find((s) => s.id === resultSource.value)?.name ?? resultSource.value,
)

function payLabel(pay: string): string {
  return pay.replace(/[[\]]/g, '') || 'VIP'
}

async function onSourceChange(val: string) {
  await api.setMusicSource(val)
  // 切换曲库后旧的搜索结果索引失效，清空避免误操作
  results.value = []
  searched.value = false
  resultKeyword.value = ''
  unplayable.value = []
}

const downloaded = ref<DownloadedMusic[]>([])

const downloadingN = ref<number | null>(null)
const toCreateN = ref<number | null>(null)

/* ----- 试听 ----- */
const audioEl = ref<HTMLAudioElement | null>(null)
const playingN = ref<number | null>(null)
const previewLoadingN = ref<number | null>(null)

/* 已判定「不可播放」的曲目序号（试听失败 / 下载校验失败）→ 禁止下载 */
const unplayable = ref<number[]>([])
function isUnplayable(n: number): boolean {
  return unplayable.value.includes(n)
}
function markUnplayable(n: number) {
  if (!unplayable.value.includes(n)) unplayable.value = [...unplayable.value, n]
}
/** 错误信息是否表示「资源不可播放」（而非网络抖动等临时失败）。 */
function isUnplayableError(msg?: string): boolean {
  return /无法播放|VIP|版权|失效|有效音频|无可试听/.test(msg || '')
}

function audioUrlCandidates(song: { vipmusicurl?: string; musicurl?: string; url?: string }): string[] {
  const urls: string[] = []
  for (const value of [song.vipmusicurl, song.musicurl, song.url]) {
    const url = String(value || '').trim()
    if (url && !urls.includes(url)) urls.push(url)
  }
  return urls
}

const onAudioPause = () => {
  if (audioEl.value && audioEl.value.ended) playingN.value = null
}

async function togglePreview(item: MusicSearchItem) {
  const el = audioEl.value
  if (!el) return
  if (playingN.value === item.n && !el.paused) {
    el.pause()
    playingN.value = null
    return
  }
  previewLoadingN.value = item.n
  try {
    const res = await api.getMusicSong(resultKeyword.value, item.n, resultSource.value)
    if (!res.ok || !res.song) {
      if (isUnplayableError(res.error)) markUnplayable(item.n)
      ElMessage.error(res.error || '获取歌曲信息失败')
      return
    }
    const candidates = audioUrlCandidates(res.song)
    if (!candidates.length) {
      markUnplayable(item.n)
      ElMessage.warning('该歌曲不可播放，无法下载（可能为 VIP / 无版权）')
      return
    }
    for (const src of candidates) {
      try {
        el.src = src
        el.load()
        await el.play()
        playingN.value = item.n
        return
      } catch {
        // 继续测试下一个候选地址。
      }
    }
    markUnplayable(item.n)
    ElMessage.error('该资源无法播放，无法下载')
  } catch {
    markUnplayable(item.n)
    ElMessage.error('该资源无法播放，无法下载')
  } finally {
    previewLoadingN.value = null
  }
}

/* ----- 搜索 ----- */
async function doSearch() {
  if (!hasKey.value) {
    openSettings()
    return
  }
  const kw = keyword.value.trim()
  if (!kw) {
    ElMessage.info('请输入搜索关键词')
    return
  }
  searching.value = true
  unplayable.value = []
  const usedSource = source.value
  try {
    const res = await api.searchMusic(kw, usedSource)
    searched.value = true
    if (!res.ok) {
      results.value = []
      resultKeyword.value = kw
      resultSource.value = usedSource
      ElMessage.error(res.error || '搜索失败')
      return
    }
    results.value = res.songs || []
    resultKeyword.value = res.keyword || kw
    resultSource.value = res.source || usedSource
  } finally {
    searching.value = false
  }
}

/* ----- 下载 ----- */
async function doDownload(item: MusicSearchItem): Promise<DownloadedMusic | null> {
  if (isUnplayable(item.n)) {
    ElMessage.warning('该资源不可播放，无法下载')
    return null
  }
  downloadingN.value = item.n
  try {
    const res = await api.downloadMusic(resultKeyword.value, item.n, resultSource.value)
    if (!res.ok || !res.path) {
      if (isUnplayableError(res.error)) markUnplayable(item.n)
      ElMessage.error(res.error || '下载失败')
      return null
    }
    ElMessage.success('已下载：' + res.name)
    await refreshDownloaded()
    return { name: res.name || item.name, path: res.path, size: res.size || '' }
  } finally {
    downloadingN.value = null
  }
}

async function downloadAndCreate(item: MusicSearchItem) {
  toCreateN.value = item.n
  try {
    const got = await doDownload(item)
    if (got) gotoCreate(got)
  } finally {
    toCreateN.value = null
  }
}

/* ----- 已下载 ----- */
async function refreshDownloaded() {
  downloaded.value = await api.listMusic()
}

function gotoCreate(d: DownloadedMusic) {
  router.push({ path: '/create', query: { source: d.path, name: d.name } })
}

function useForCreate(d: DownloadedMusic) {
  gotoCreate(d)
}

async function removeDownloaded(d: DownloadedMusic) {
  try {
    await ElMessageBox.confirm(`确定删除「${d.name}」吗？`, '删除素材', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const ok = await api.deleteMusic(d.path)
  if (ok) {
    await refreshDownloaded()
    ElMessage.success('已删除')
  } else {
    ElMessage.error('删除失败')
  }
}

/* ----- API 设置 ----- */
const settingsVisible = ref(false)
const keyDraft = ref('')
const cookieDraft = ref('')
const savingKey = ref(false)

async function openSettings() {
  keyDraft.value = await api.getMusicApiKey()
  cookieDraft.value = await api.getMusicCookie()
  settingsVisible.value = true
}

async function saveKey() {
  savingKey.value = true
  try {
    await api.setMusicApiKey(keyDraft.value.trim())
    await api.setMusicCookie(cookieDraft.value.trim())
    hasKey.value = !!keyDraft.value.trim()
    settingsVisible.value = false
    ElMessage.success('已保存设置')
  } finally {
    savingKey.value = false
  }
}

onMounted(async () => {
  const [key, srcList, curSource] = await Promise.all([
    api.getMusicApiKey(),
    api.listMusicSources(),
    api.getMusicSource(),
  ])
  hasKey.value = !!key
  if (srcList.length) sources.value = srcList
  if (srcList.some((s) => s.id === curSource)) source.value = curSource
  resultSource.value = source.value
  await refreshDownloaded()
})
</script>

<style scoped>
.page {
  max-width: 1320px;
  margin: 0 auto;
  padding: 28px 24px 60px;
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}
.eyebrow {
  color: var(--xb-primary);
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 14px;
  margin: 0 0 8px;
}
.page-head h1 { font-size: 30px; font-weight: 800; margin: 0 0 8px; }
.page-sub { color: var(--xb-muted); font-size: 15px; margin: 0; }

.glass {
  position: relative;
  background: var(--xb-panel);
  border: 1px solid var(--xb-border);
  backdrop-filter: blur(16px);
}
.cta-btn {
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important;
  border: none !important;
  color: var(--xb-on-primary) !important;
  font-weight: 700;
  box-shadow: 0 0 18px rgba(var(--xb-primary-rgb), 0.35);
}
.ghost-btn {
  background: rgba(var(--xb-primary-rgb), 0.06) !important;
  border: 1px solid var(--xb-border) !important;
  color: var(--xb-text) !important;
  font-weight: 600;
}
.ghost-btn:hover { border-color: var(--xb-primary) !important; color: var(--xb-primary) !important; }

/* 提示条 */
.notice {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 22px;
  border-radius: 6px;
  border-color: rgba(var(--xb-warn-rgb), 0.35);
  margin-bottom: 18px;
}
.notice-ic { font-size: 26px; color: var(--xb-warn); flex-shrink: 0; }
.notice-main { flex: 1; }
.notice-title { font-weight: 700; font-size: 15px; }
.notice-sub { font-size: 13px; color: var(--xb-muted); margin-top: 4px; }

/* 工具条 */
.toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border-radius: 6px;
  margin-bottom: 26px;
}
.search {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 9px;
  background: rgba(var(--xb-fill-rgb), 0.04);
  border: 1px solid var(--xb-border);
  color: var(--xb-muted);
}
.search input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--xb-text);
  font-size: 14px;
}
.search input::placeholder { color: var(--xb-muted); }
.search:focus-within { border-color: var(--xb-primary); }
.search-clear {
  display: grid;
  place-items: center;
  border: none;
  background: none;
  color: var(--xb-muted);
  cursor: pointer;
  padding: 0;
}
.search-clear:hover { color: var(--xb-accent); }
/* 曲库选择 */
.source-field { flex-shrink: 0; }
.source-select { width: 130px; }
.source-select :deep(.el-select__wrapper) {
  background: rgba(var(--xb-fill-rgb), 0.04);
  border: 1px solid var(--xb-border);
  border-radius: 9px;
  box-shadow: none;
  min-height: 42px;
}
.source-select :deep(.el-select__wrapper.is-focused) { border-color: var(--xb-primary); }
.source-select :deep(.el-select__placeholder),
.source-select :deep(.el-select__selected-item) { color: var(--xb-text); }

/* 区块 */
.block { margin-bottom: 30px; }
.block-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 14px;
}
.block-head h2 { font-size: 20px; font-weight: 800; margin: 0; }
.muted { color: var(--xb-muted); font-size: 13px; }

/* 列表 */
.list { border-radius: 6px; padding: 6px; }
.row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  border-radius: 6px;
  transition: background 0.2s;
}
.row:hover { background: rgba(var(--xb-primary-rgb), 0.05); }
.row + .row { border-top: 1px solid rgba(var(--xb-fill-rgb), 0.04); }
.row-no {
  width: 24px;
  flex-shrink: 0;
  text-align: center;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 13px;
  color: var(--xb-muted);
}
.row-play {
  width: 36px; height: 36px;
  flex-shrink: 0;
  border-radius: 50%;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-primary-rgb), 0.08);
  color: var(--xb-primary);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 15px;
  transition: all 0.2s;
}
.row-play:hover:not(:disabled) { background: var(--xb-primary); color: var(--xb-on-primary); }
.row-play:disabled { opacity: 0.5; cursor: progress; }
.row-cover {
  width: 38px; height: 38px;
  flex-shrink: 0;
  border-radius: 9px;
  display: grid;
  place-items: center;
  font-size: 17px;
  color: var(--xb-on-primary);
  background: linear-gradient(135deg, var(--xb-primary-2), var(--xb-accent));
}
.row-main { flex: 1; min-width: 0; }
.row-title {
  font-weight: 600;
  font-size: 14.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.row-sub {
  font-size: 12.5px;
  color: var(--xb-muted);
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pay-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  vertical-align: middle;
  color: var(--xb-warn);
  background: rgba(var(--xb-warn-rgb), 0.14);
  border: 1px solid rgba(var(--xb-warn-rgb), 0.35);
}
.dead-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  vertical-align: middle;
  color: var(--xb-accent);
  background: rgba(var(--xb-accent-rgb), 0.14);
  border: 1px solid rgba(var(--xb-accent-rgb), 0.35);
}
.row-ops { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.op {
  width: 34px; height: 34px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 16px;
  transition: all 0.2s;
}
.op.danger:hover { color: var(--xb-accent); background: rgba(var(--xb-accent-rgb), 0.1); }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 空状态 */
.empty {
  border-radius: 6px;
  padding: 56px 20px;
  text-align: center;
}
.empty.small { padding: 30px 20px; color: var(--xb-muted); font-size: 13.5px; }
.empty-icon { font-size: 46px; color: var(--xb-muted); opacity: 0.5; margin-bottom: 12px; }
.empty-title { font-size: 16px; font-weight: 700; margin: 0 0 6px; }
.empty-sub { font-size: 13px; color: var(--xb-muted); margin: 0; }

/* 弹窗 */
.dialog-body { display: flex; flex-direction: column; gap: 10px; }
.dialog-tip { font-size: 13px; color: var(--xb-muted); line-height: 1.6; margin: 0 0 6px; }
.dialog-tip a { color: var(--xb-primary); text-decoration: none; }
.dialog-tip a:hover { text-decoration: underline; }
.dialog-label { font-size: 13px; font-weight: 600; color: var(--xb-text); }

@media (max-width: 720px) {
  .page-head { flex-direction: column; align-items: flex-start; }
  .toolbar { flex-wrap: wrap; }
  .row-ops .el-button span { display: none; }
}
</style>
