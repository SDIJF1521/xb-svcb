<template>
  <div class="page">
    <!-- 页面标题 -->
    <div class="page-head">
      <div>
        <p class="eyebrow">// AI 翻唱</p>
        <h1>歌声转换工作台</h1>
        <p class="page-sub">上传歌曲 → 选择 S模型 → 调整参数 → 一键生成翻唱</p>
      </div>
    </div>

    <div class="layout">
      <!-- 左侧：配置 -->
      <div class="config">
        <!-- 翻唱模式 -->
        <section class="card glass mode-card">
          <button class="mode-item" :class="{ active: mode === 'single' }" @click="mode = 'single'">
            <el-icon><Microphone /></el-icon>
            <div class="mode-text">
              <div class="mode-name">单模型翻唱</div>
              <div class="mode-desc">整首歌用一个模型</div>
            </div>
          </button>
          <button class="mode-item" :class="{ active: mode === 'multi' }" @click="mode = 'multi'">
            <el-icon><Operation /></el-icon>
            <div class="mode-text">
              <div class="mode-name">多模型混合</div>
              <div class="mode-desc">逐句指派不同模型</div>
            </div>
          </button>
        </section>

        <section class="card glass workflow-card">
          <div class="card-head">
            <span class="step-no">ADV</span>
            <h2>高级功能</h2>
          </div>
          <div class="workflow-grid">
            <button
              v-for="item in availableWorkflowOptions"
              :key="item.key"
              class="workflow-item"
              :class="{ active: workflow === item.key }"
              @click="workflow = item.key"
            >
              <span class="workflow-no">{{ item.no }}</span>
              <span class="workflow-copy">
                <span class="workflow-title">
                  {{ item.title }}
                  <i v-if="item.tag">{{ item.tag }}</i>
                </span>
                <span class="workflow-desc">{{ item.desc }}</span>
              </span>
            </button>
          </div>
        </section>

        <!-- 上传歌曲 -->
        <section class="card glass">
          <div class="card-head">
            <span class="step-no">01</span>
            <h2>上传歌曲</h2>
          </div>
          <div v-if="!song" class="dropzone" @click="onPickSong">
            <el-icon class="dz-icon"><UploadFilled /></el-icon>
            <p class="dz-main">点击选择音频文件</p>
            <p class="dz-sub">支持 MP3 / WAV / FLAC，单文件 ≤ 50MB</p>
          </div>
          <div v-else class="song-file">
            <div class="song-cover"><el-icon><Headset /></el-icon></div>
            <div class="song-info">
              <div class="song-name">{{ song.name }}</div>
              <div class="song-meta">{{ song.hint }}</div>
            </div>
            <button class="icon-x" @click="song = null"><el-icon><Close /></el-icon></button>
          </div>

          <!-- 已下载素材：从「资源获取」下载的歌曲可直接选用 -->
          <div v-if="downloaded.length" class="lib">
            <div class="lib-head">
              <span>从已下载素材选择</span>
              <router-link to="/music" class="head-link">资源获取 <el-icon><Right /></el-icon></router-link>
            </div>
            <div class="lib-list">
              <button
                v-for="d in downloaded"
                :key="d.path"
                class="lib-item"
                :class="{ active: song?.path === d.path }"
                :title="d.name"
                @click="pickDownloaded(d)"
              >
                <el-icon><Headset /></el-icon>
                <span class="lib-name">{{ d.name }}</span>
                <span class="lib-size">{{ d.size }}</span>
              </button>
            </div>
          </div>
        </section>

        <!-- 选择模型（单模型） -->
        <section v-if="mode === 'single'" class="card glass">
          <div class="card-head">
            <span class="step-no">02</span>
            <h2>选择你的模型</h2>
            <router-link to="/models" class="head-link">管理模型 <el-icon><Right /></el-icon></router-link>
          </div>
          <div v-if="availableFrameworks.length > 1" class="model-filter">
            <button class="filter-chip" :class="{ on: modelFilter === '' }" @click="modelFilter = ''">全部</button>
            <button
              v-for="fw in availableFrameworks"
              :key="fw"
              class="filter-chip"
              :class="{ on: modelFilter === fw }"
              @click="modelFilter = fw"
            >{{ frameworkLabel(fw) }}</button>
          </div>
          <div v-if="filteredModels.length" class="model-list">
            <button
              v-for="m in filteredModels"
              :key="m.id"
              class="model-item"
              :class="{ active: selectedModel === m.id }"
              @click="selectedModel = m.id"
            >
              <div class="model-dot" :style="{ '--mc': m.color }">
                <el-icon><Microphone /></el-icon>
              </div>
              <div class="model-text">
                <div class="model-name">
                  {{ m.name }}<span class="fw-chip">{{ frameworkLabel(m.framework) }}</span>
                </div>
                <div class="model-tag">{{ m.type }} · {{ m.sr }}</div>
              </div>
              <el-icon v-if="selectedModel === m.id" class="model-check"><Select /></el-icon>
            </button>
          </div>
          <p v-else class="field-tip">该框架下暂无模型，切换筛选或前往「管理模型」导入。</p>
        </section>

        <!-- 选择模型（多模型 + 各自参数） -->
        <section v-else class="card glass">
          <div class="card-head">
            <span class="step-no">02</span>
            <h2>选择参与模型</h2>
            <router-link to="/models" class="head-link">管理模型 <el-icon><Right /></el-icon></router-link>
          </div>
          <p class="field-tip">勾选本次要混合的模型（可跨框架：So-VITS-SVC / RVC / SeedVC 同曲混用），每个模型可单独展开设置参数</p>
          <div v-if="availableFrameworks.length > 1" class="model-filter">
            <button class="filter-chip" :class="{ on: modelFilter === '' }" @click="modelFilter = ''">全部</button>
            <button
              v-for="fw in availableFrameworks"
              :key="fw"
              class="filter-chip"
              :class="{ on: modelFilter === fw }"
              @click="modelFilter = fw"
            >{{ frameworkLabel(fw) }}</button>
          </div>
          <div class="model-list">
            <div v-for="m in filteredModels" :key="m.id" class="multi-model">
              <button
                class="model-item"
                :class="{ active: isPicked(m.id) }"
                @click="togglePick(m.id)"
              >
                <div class="model-dot" :style="{ '--mc': modelDisplayColor(m.id, m.color) }">
                  <el-icon><Microphone /></el-icon>
                </div>
                <div class="model-text">
                  <div class="model-name">
                    {{ m.name }}<span class="fw-chip">{{ frameworkLabel(m.framework) }}</span>
                  </div>
                  <div class="model-tag">{{ m.type }} · {{ m.sr }}</div>
                </div>
                <span v-if="isPicked(m.id)" class="model-badge" :style="{ background: pickedModelColor(m.id) }">
                  {{ pickedIndex(m.id) + 1 }}
                </span>
                <el-icon v-if="isPicked(m.id)" class="model-check"><Select /></el-icon>
              </button>

              <div v-if="isPicked(m.id)" class="mp-params">
                <div class="mp-row">
                  <label>变调 {{ mp(m.id).pitch > 0 ? '+' + mp(m.id).pitch : mp(m.id).pitch }}</label>
                  <input type="range" min="-12" max="12" step="1" v-model.number="mp(m.id).pitch" />
                </div>
                <template v-if="frameworkOf(m.id) !== 'rvc'">
                  <div class="mp-row">
                    <label v-if="frameworkOf(m.id) === 'seed-vc'">扩散步数 {{ qualitySteps(mp(m.id).diffusionRatio) }}</label>
                    <label v-else-if="frameworkOf(m.id) === 'ddsp-svc'">采样步数 {{ ddspQualitySteps(mp(m.id).diffusionRatio) }}</label>
                    <label v-else>扩散占比 {{ Math.round(mp(m.id).diffusionRatio * 100) }}%</label>
                    <input type="range" min="0" max="1" step="0.05" v-model.number="mp(m.id).diffusionRatio" />
                  </div>
                  <div v-if="frameworkOf(m.id) === 'ddsp-svc'" class="mp-row">
                    <label>共振峰偏移 {{ signedFormantShift(mp(m.id).formantShift) }}</label>
                    <input type="range" min="-2" max="2" step="0.05" v-model.number="mp(m.id).formantShift" />
                  </div>
                  <div v-if="frameworkOf(m.id) === 'seed-vc'" class="mp-ref">
                    <span>参考音频</span>
                    <button type="button" class="mini-picker" @click="pickMultiReference(m.id)">
                      {{ baseName(mp(m.id).referenceAudio) || '选择音色参考' }}
                    </button>
                  </div>
                </template>
                <template v-else>
                  <div class="mp-row">
                    <label>清辅音保护 {{ mp(m.id).protect.toFixed(2) }}</label>
                    <input type="range" min="0" max="0.5" step="0.01" v-model.number="mp(m.id).protect" />
                  </div>
                  <div class="mp-row">
                    <label>检索比率 {{ mp(m.id).indexRate.toFixed(2) }}</label>
                    <input type="range" min="0" max="1" step="0.05" v-model.number="mp(m.id).indexRate" />
                  </div>
                </template>
                <div class="mp-inline">
                  <div v-if="frameworkOf(m.id) !== 'seed-vc'" class="mp-mini">
                    <span>F0</span>
                    <select v-model="mp(m.id).f0Method">
                      <option v-for="f in f0Methods" :key="f" :value="f">{{ f }}</option>
                    </select>
                  </div>
                  <div class="mp-mini">
                    <span>设备</span>
                    <select v-model="mp(m.id).device">
                      <option v-for="d in deviceOptionsFor(frameworkOf(m.id))" :key="d.v" :value="d.v">{{ d.label }}</option>
                    </select>
                  </div>
                  <div v-if="frameworkOf(m.id) === 'rvc'" class="mp-mini">
                    <span>版本</span>
                    <select v-model="mp(m.id).rvcVersion">
                      <option v-for="v in rvcVersions" :key="v" :value="v">{{ v }}</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 人声分离 -->
        <section class="card glass">
          <div class="card-head">
            <span class="step-no">03</span>
            <h2>人声分离 (UVR)</h2>
          </div>
          <p class="field-tip">由 Ultimate Vocal Remover 自动分离人声与伴奏</p>
          <div class="seg">
            <button
              v-for="u in uvrModels"
              :key="u"
              class="seg-item"
              :class="{ active: uvrModel === u }"
              @click="uvrModel = u"
            >{{ u }}</button>
          </div>
        </section>

        <!-- 推理参数（单模型） -->
        <section v-if="mode === 'single'" class="card glass">
          <div class="card-head">
            <span class="step-no">04</span>
            <h2>推理参数</h2>
          </div>

          <div class="fw-banner">
            当前模型框架：<b>{{ frameworkLabel(selectedFramework) }}</b>
          </div>

          <div v-if="selectedFramework === 'seed-vc'" class="field">
            <label class="field-block-label">目标音色参考音频</label>
            <button type="button" class="path-picker" @click="pickSeedVcReference">
              <el-icon><Headset /></el-icon>
              <span>{{ baseName(seedVcReferenceAudio) || '选择本次推理使用的参考音频' }}</span>
            </button>
            <div class="field-hint">建议使用 1-30 秒干净人声；这不是模型文件，每次推理可以单独更换</div>
          </div>

          <div v-if="selectedFramework !== 'rvc'" class="field">
            <div class="field-row">
              <label>{{ selectedFramework === 'seed-vc' ? 'SeedVC 推理质量' : selectedFramework === 'ddsp-svc' ? 'DDSP-SVC 推理质量' : '主模型 / 扩散模型 比例' }}</label>
              <span class="field-val">
                <template v-if="selectedFramework === 'seed-vc' || selectedFramework === 'ddsp-svc'">
                  <i class="ratio-diff">{{ selectedFramework === 'ddsp-svc' ? ddspQualitySteps(diffusionRatio) : qualitySteps(diffusionRatio) }} 步</i>
                </template>
                <template v-else>
                  <i class="ratio-main">主 {{ Math.round((1 - diffusionRatio) * 100) }}%</i>
                  ·
                  <i class="ratio-diff">扩散 {{ Math.round(diffusionRatio * 100) }}%</i>
                </template>
              </span>
            </div>
            <input class="ratio-range" type="range" min="0" max="1" step="0.05" v-model.number="diffusionRatio" />
            <div class="field-hint">
              {{ selectedFramework === 'seed-vc' ? 'SeedVC 使用扩散步数控制质量与速度，向右质量更高但更慢' : selectedFramework === 'ddsp-svc' ? 'DDSP-SVC 使用 Rectified Flow 采样步数控制质量与速度' : '两个模型共同参与推理，向右扩散模型占比更高' }}
            </div>
          </div>

          <div v-if="selectedFramework === 'ddsp-svc'" class="field">
            <div class="field-row">
              <label>共振峰偏移（半音）</label>
              <span class="field-val">{{ signedFormantShift(formantShift) }}</span>
            </div>
            <input type="range" min="-2" max="2" step="0.05" v-model.number="formantShift" />
            <div class="field-hint">用于细调音色的厚薄与明暗，仅对使用 pitch augmentation 训练的模型有效</div>
          </div>

          <div class="field">
            <div class="field-row">
              <label>变调（半音）</label>
              <span class="field-val">{{ pitch > 0 ? '+' + pitch : pitch }}</span>
            </div>
            <input type="range" min="-12" max="12" step="1" v-model.number="pitch" />
            <div class="field-hint">男声转女声建议 +12，女声转男声建议 -12</div>
          </div>

          <div v-if="selectedFramework !== 'seed-vc'" class="field">
            <label class="field-block-label">F0 提取算法</label>
            <div class="seg">
              <button
                v-for="f in f0Methods"
                :key="f"
                class="seg-item"
                :class="{ active: f0Method === f }"
                @click="f0Method = f"
              >{{ f }}</button>
            </div>
          </div>

          <div class="field">
            <label class="field-block-label">推理设备</label>
            <div class="seg">
              <button
                v-for="d in deviceOptions"
                :key="d.v"
                class="seg-item"
                :class="{ active: device === d.v }"
                @click="device = d.v"
              >{{ d.label }}</button>
            </div>
            <div class="field-hint">{{ deviceHint }}</div>
          </div>

          <!-- RVC 专属参数 -->
          <template v-if="selectedFramework === 'rvc'">
            <div class="field">
              <div class="field-row">
                <label>索引比率</label>
                <span class="field-val">{{ indexRate.toFixed(2) }}</span>
              </div>
              <input type="range" min="0" max="1" step="0.05" v-model.number="indexRate" />
            </div>

            <div class="field">
              <div class="field-row">
                <label>响度包络融合</label>
                <span class="field-val">{{ rmsMix.toFixed(2) }}</span>
              </div>
              <input type="range" min="0" max="1" step="0.05" v-model.number="rmsMix" />
            </div>

            <div class="field">
              <div class="field-row">
                <label>清辅音保护 (protect)</label>
                <span class="field-val">{{ protect.toFixed(2) }}</span>
              </div>
              <input type="range" min="0" max="0.5" step="0.01" v-model.number="protect" />
              <div class="field-hint">越小越贴合目标音色，越大越保留原声辅音/呼吸（0~0.5）</div>
            </div>

            <div class="field">
              <div class="field-row">
                <label>F0 中值滤波半径</label>
                <span class="field-val">{{ filterRadius }}</span>
              </div>
              <input type="range" min="0" max="7" step="1" v-model.number="filterRadius" />
              <div class="field-hint">≥3 可降低呼吸杂音（仅对 harvest 等有效）</div>
            </div>

            <div class="field">
              <label class="field-block-label">RVC 模型版本</label>
              <div class="seg">
                <button
                  v-for="v in rvcVersions"
                  :key="v"
                  class="seg-item"
                  :class="{ active: rvcVersion === v }"
                  @click="rvcVersion = v"
                >{{ v }}</button>
              </div>
            </div>
          </template>
        </section>

        <!-- 歌词与分句指派（多模型） -->
        <section v-else class="card glass">
          <div class="card-head">
            <span class="step-no">04</span>
            <h2>歌词分句指派</h2>
          </div>
          <p class="field-tip">按歌名在线获取，或导入带时间轴的歌词文件（.lrc），再为每句指派演唱模型</p>

          <div class="lyric-fetch">
            <input
              v-model="songQuery"
              class="lyric-input"
              type="text"
              placeholder="歌曲名 / 歌手，用于获取歌词"
              @keyup.enter="fetchLyrics"
            />
            <input v-model.number="songIndex" class="lyric-n" type="number" min="1" max="20" title="搜索结果序号" />
            <el-select v-model="lyricSrc" class="lyric-src">
              <el-option v-for="s in lyricSources" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
            <el-button round class="ghost-btn" :loading="lyricLoading" @click="fetchLyrics">获取歌词</el-button>
            <el-button round class="ghost-btn" @click="pickLrc">
              <el-icon class="el-icon--left"><Upload /></el-icon>导入歌词文件
            </el-button>
            <input
              ref="lrcInput"
              type="file"
              accept=".lrc,.txt,text/plain"
              hidden
              @change="onLrcFile"
            />
          </div>

          <!-- 对齐校验 -->
          <div v-if="lyrics.length" class="align-bar" :class="alignStatus.type">
            <el-icon><Clock /></el-icon>
            <span class="align-text">{{ alignStatus.text }}</span>
            <div class="offset-ctrl">
              <label>整体偏移 {{ offset > 0 ? '+' : '' }}{{ offset.toFixed(1) }}s</label>
              <input type="range" min="-10" max="10" step="0.1" v-model.number="offset" />
            </div>
          </div>

          <!-- 快捷指派 -->
          <div v-if="segments.length && pickedModels.length" class="assign-quick">
            <span class="muted">批量：</span>
            <button
              v-for="pm in pickedModels"
              :key="pm.id"
              class="quick-btn"
              :style="{ '--mc': pm.color }"
              @click="assignAll(pm.id)"
            >全指派给 {{ pm.name }}</button>
            <span class="muted assign-tip">每段可多选模型 → 合唱同唱一段</span>
          </div>

          <!-- 可视化时间轴（缩略预览，编辑在弹窗中进行，避免撑破内联布局）-->
          <div v-if="segments.length && pickedModels.length" class="timeline-wrap">
            <div class="timeline-head">
              <span class="tl-title"><el-icon><Operation /></el-icon> 时间轴</span>
              <div class="tl-tools">
                <button class="tl-zoom" title="撤销" :disabled="!canUndo" @click="undo"><el-icon><RefreshLeft /></el-icon></button>
                <button class="tl-zoom" title="重做" :disabled="!canRedo" @click="redo"><el-icon><RefreshRight /></el-icon></button>
                <button class="tl-zoom" title="复原为初始切分" @click="resetTimeline"><el-icon><Refresh /></el-icon></button>
                <button class="tl-enlarge" title="放大编辑时间轴" @click="openTlDialog">
                  <el-icon><FullScreen /></el-icon>放大编辑
                </button>
              </div>
            </div>
            <div class="tl-legend">
              <span v-for="pm in pickedModels" :key="pm.id" class="tl-leg">
                <span class="tl-leg-dot" :style="{ background: pm.color }">{{ pickedIndex(pm.id) + 1 }}</span>{{ pm.name }}
              </span>
              <span class="tl-leg"><span class="tl-leg-dot idle"></span>间奏</span>
            </div>
            <!-- 内联缩略预览：色块按比例铺满，固定高度 + overflow:hidden，配合已钳制的 left/width 百分比
                 与固定的总时长，任何极端片段都被裁进容器内，绝不撑破布局。点击进入弹窗编辑。 -->
            <div class="tl-mini" title="点击放大编辑时间轴" @click="openTlDialog">
              <div
                v-for="blk in timelineBlocks"
                :key="blk.id"
                class="tl-mini-block"
                :class="{ 'is-idle': !blk.ids.length, 'is-chorus': blk.ids.length > 1 }"
                :style="{ left: blk.leftPct + '%', width: blk.widthPct + '%', ...blockStyle(blk.ids) }"
              ></div>
            </div>
            <p class="tl-hint muted">缩略预览。点击「放大编辑」可拖动边界 / 缩放 / 拆分合并；撤销 / 重做 / 复原随时回退误操作。</p>
          </div>

          <!-- 放大编辑弹窗 -->
          <el-dialog
            v-model="tlDialog"
            title="时间轴编辑"
            width="92%"
            top="5vh"
            append-to-body
            destroy-on-close
            class="tl-dialog"
            @opened="onTlOpened"
            @closed="onTlClosed"
          >
            <div class="tl-dialog-bar">
              <div class="tl-legend">
                <span v-for="pm in pickedModels" :key="pm.id" class="tl-leg">
                  <span class="tl-leg-dot" :style="{ background: pm.color }">{{ pickedIndex(pm.id) + 1 }}</span>{{ pm.name }}
                </span>
                <span class="tl-leg"><span class="tl-leg-dot idle"></span>间奏</span>
              </div>
              <div class="tl-tools">
                <button class="tl-zoom" title="撤销" :disabled="!canUndo" @click="undo"><el-icon><RefreshLeft /></el-icon></button>
                <button class="tl-zoom" title="重做" :disabled="!canRedo" @click="redo"><el-icon><RefreshRight /></el-icon></button>
                <button class="tl-enlarge" title="复原为初始切分" @click="resetTimeline"><el-icon><Refresh /></el-icon>复原</button>
                <span class="tl-sep"></span>
                <button class="tl-zoom" title="缩小" @click="zoomOut"><el-icon><ZoomOut /></el-icon></button>
                <span class="tl-zoom-val">{{ Math.round(zoom * 100) }}%</span>
                <button class="tl-zoom" title="放大" @click="zoomIn"><el-icon><ZoomIn /></el-icon></button>
                <button class="tl-zoom" title="重置缩放" @click="zoomReset"><el-icon><FullScreen /></el-icon></button>
              </div>
            </div>
            <!-- 横向可滚动的缩放视口：trackEl 量取的是固定宽度的外层视口，
                 与内部会随缩放变宽的 .tl-inner 彻底解耦，避免 ResizeObserver 自反馈把轨道越撑越大 -->
            <div ref="trackEl" class="tl-viewport">
              <div class="tl-scroll tl-scroll-lg">
                <div class="tl-inner" :style="{ width: innerPx + 'px' }">
                <!-- 时间刻度 -->
                <div class="tl-ruler">
                  <span
                    v-for="mk in rulerMarks"
                    :key="mk.pct"
                    class="tl-tick"
                    :style="{ left: mk.pct + '%' }"
                  >{{ mk.label }}</span>
                </div>
                <!-- 片段轨道 -->
                <div class="tl-track tl-track-lg">
                  <el-popover
                    v-for="blk in timelineBlocks"
                    :key="blk.id"
                    placement="top"
                    :width="248"
                    trigger="click"
                    popper-class="assign-popover"
                  >
                    <template #reference>
                      <div
                        class="tl-block"
                        :class="{ 'is-idle': !blk.ids.length, 'is-chorus': blk.ids.length > 1, dragging: draggingId === blk.id }"
                        :style="{ left: blk.leftPct + '%', width: blk.widthPct + '%', ...blockStyle(blk.ids) }"
                        :title="`${fmtTime(blk.start)} - ${fmtTime(blk.end)}　${blk.text}`"
                      >
                        <span
                          class="tl-grip l"
                          title="拖动调整起点（吸附歌词时间）"
                          @pointerdown="beginDrag(blk.seg, 'start', $event)"
                          @click.stop
                        ></span>
                        <span v-if="blk.ids.length > 1" class="tl-block-chorus">{{ blk.ids.length }}</span>
                        <span class="tl-block-label">{{ blk.label }}</span>
                        <span
                          class="tl-grip r"
                          title="拖动调整终点（吸附歌词时间）"
                          @pointerdown="beginDrag(blk.seg, 'end', $event)"
                          @click.stop
                        ></span>
                      </div>
                    </template>
                    <div class="pick-pop">
                      <p class="pick-hint">{{ fmtTime(blk.start) }} – {{ fmtTime(blk.end) }} · {{ blk.text || '（无歌词）' }}</p>
                      <button
                        v-for="pm in pickedModels"
                        :key="pm.id"
                        class="pick-item"
                        :class="{ on: isAssigned(blk.id, pm.id) }"
                        :style="{ '--mc': pm.color }"
                        @click="toggleAssign(blk.id, pm.id)"
                      >
                        <span class="pick-dot" :style="{ background: pm.color }"></span>
                        <span class="pick-name">{{ pm.name }}</span>
                        <el-icon v-if="isAssigned(blk.id, pm.id)" class="pick-check"><Check /></el-icon>
                      </button>
                      <div class="pick-acts">
                        <button class="pick-act" title="从中点拆分" @click="splitSegment(blk.seg)">
                          <el-icon><Scissor /></el-icon>拆分
                        </button>
                        <button class="pick-act" title="与后一段合并" @click="mergeWithNext(blk.seg)">
                          <el-icon><Connection /></el-icon>合并
                        </button>
                        <button class="pick-act" title="设为间奏（不唱）" @click="clearSegModels(blk.id)">
                          <el-icon><Mute /></el-icon>间奏
                        </button>
                        <button class="pick-act danger" title="删除该片段" @click="removeSegment(blk.seg)">
                          <el-icon><Delete /></el-icon>删除
                        </button>
                      </div>
                    </div>
                  </el-popover>
                </div>
              </div>
              </div>
            </div>
            <p class="tl-hint muted">拖动色块左右边缘调整起止（自动吸附歌词时间）；点击色块指派模型 / 拆分 / 合并 / 删除；缩放放大局部精修；左上角可撤销 / 重做 / 复原。</p>
          </el-dialog>

          <!-- 片段逐段（与时间轴同一数据源）-->
          <div v-if="segments.length" class="lyric-list">
            <div
              v-for="blk in timelineBlocks"
              :key="blk.id"
              class="lyric-row"
              :class="{ 'is-chorus': blk.ids.length > 1, 'is-idle': !blk.ids.length }"
            >
              <span class="ly-time">{{ fmtTime(blk.start) }}<br />{{ fmtTime(blk.end) }}</span>
              <span class="ly-text" :title="blk.text">{{ blk.text || '（无歌词）' }}</span>
              <div class="ly-assign">
                <span v-if="blk.ids.length > 1" class="chorus-tag">
                  <el-icon><Microphone /></el-icon>合唱 ×{{ blk.ids.length }}
                </span>
                <span
                  v-for="id in visibleChips(blk.seg)"
                  :key="id"
                  class="model-chip"
                  :style="chipStyle(id)"
                >
                  <span class="chip-dot" :style="{ background: modelColor(id) }"></span>
                  <span class="chip-name">{{ modelName(id) }}</span>
                  <button class="chip-x" title="移除" @click.stop="removeAssign(blk.id, id)">
                    <el-icon><Close /></el-icon>
                  </button>
                </span>
                <button
                  v-if="blk.ids.length > visibleChips(blk.seg).length || (isExpanded(blk.id) && blk.ids.length > 3)"
                  class="more-chip"
                  @click.stop="toggleExpand(blk.id)"
                >{{ isExpanded(blk.id) ? '收起' : '+' + (blk.ids.length - 3) }}</button>
                <span v-if="!blk.ids.length" class="idle-chip">间奏 · 不唱</span>
                <el-popover
                  placement="bottom-end"
                  :width="232"
                  trigger="click"
                  popper-class="assign-popover"
                >
                  <template #reference>
                    <button class="add-chip" :title="blk.ids.length ? '增减演唱模型' : '指派模型'">
                      <el-icon><Plus /></el-icon>
                    </button>
                  </template>
                  <div class="pick-pop">
                    <p class="pick-hint">点选模型演唱本段，多选即「合唱」</p>
                    <button
                      v-for="pm in pickedModels"
                      :key="pm.id"
                      class="pick-item"
                      :class="{ on: isAssigned(blk.id, pm.id) }"
                      :style="{ '--mc': pm.color }"
                      @click="toggleAssign(blk.id, pm.id)"
                    >
                      <span class="pick-dot" :style="{ background: pm.color }"></span>
                      <span class="pick-name">{{ pm.name }}</span>
                      <el-icon v-if="isAssigned(blk.id, pm.id)" class="pick-check"><Check /></el-icon>
                    </button>
                  </div>
                </el-popover>
                <div class="seg-ops">
                  <button class="seg-op" title="从中点拆分" @click.stop="splitSegment(blk.seg)"><el-icon><Scissor /></el-icon></button>
                  <button class="seg-op" title="与后一段合并" @click.stop="mergeWithNext(blk.seg)"><el-icon><Connection /></el-icon></button>
                  <button class="seg-op danger" title="删除片段" @click.stop="removeSegment(blk.seg)"><el-icon><Delete /></el-icon></button>
                </div>
              </div>
            </div>
          </div>
          <div v-else-if="lyricTried && !lyricLoading" class="lyric-empty">
            未获取到歌词，请检查歌名 / 序号 / 曲库后重试，或导入 .lrc 歌词文件。
          </div>
        </section>

        <section class="card glass infer-tools">
          <div class="card-head">
            <span class="step-no">ECO</span>
            <h2>推理生态</h2>
          </div>
          <div class="infer-tool-row">
            <el-select v-model="selectedPresetId" class="preset-select" placeholder="选择参数预设" @change="applyPreset">
              <el-option v-for="p in presets" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-button round class="ghost-btn" :disabled="!selectedPresetId" @click="applyPreset">
              <el-icon class="el-icon--left"><Check /></el-icon>应用
            </el-button>
            <el-button round class="ghost-btn" @click="savePreset">
              <el-icon class="el-icon--left"><Plus /></el-icon>保存预设
            </el-button>
            <button class="preset-delete" :disabled="!selectedPresetId" title="删除预设" @click="deletePreset">
              <el-icon><Delete /></el-icon>
            </button>
          </div>
          <div class="infer-tool-row">
            <span class="queue-text">队列：{{ queueStatus.size }} 个等待</span>
            <el-button round class="ghost-btn" :disabled="mode !== 'single' || !selectedModel || (selectedFramework === 'seed-vc' && !seedVcReferenceAudio)" @click="batchGenerate">
              <el-icon class="el-icon--left"><Document /></el-icon>批量推理
            </el-button>
          </div>
        </section>

        <el-button
          size="large"
          round
          class="cta-btn generate-btn"
          :disabled="!canGenerate || isGenerating"
          @click="generate"
        >
          <el-icon class="el-icon--left"><MagicStick /></el-icon>
          {{ isGenerating ? '生成中...' : workflow === 'full_manual_editor' ? '进入全手动编辑' : '开始生成翻唱' }}
        </el-button>
      </div>

      <!-- 右侧：预览 / 进度 -->
      <div class="preview">
        <section class="card glass result-card">
          <div class="corner tl"></div>
          <div class="corner tr"></div>
          <div class="corner bl"></div>
          <div class="corner br"></div>

          <div class="result-head">
            <h2>输出预览</h2>
            <span class="result-state" :class="overallState.type">{{ overallState.text }}</span>
          </div>

          <div class="player">
            <div class="player-cover">
              <el-icon><Headset /></el-icon>
            </div>
            <div class="waveform" :class="{ playing: isPlaying }">
              <span v-for="n in 56" :key="n" :style="barStyle(n)"></span>
            </div>
            <div class="player-ctrl">
              <button class="play-main" :disabled="!done" @click="onTogglePlay">
                <el-icon v-if="!isPlaying"><VideoPlay /></el-icon>
                <el-icon v-else><VideoPause /></el-icon>
              </button>
              <el-button round class="ghost-btn" :disabled="!done" @click="onExport">
                <el-icon class="el-icon--left"><Download /></el-icon>导出
              </el-button>
              <el-button v-if="editorAvailable" round class="ghost-btn" @click="openCurrentWorkEditor">
                <el-icon class="el-icon--left"><Operation /></el-icon>进入编辑器
              </el-button>
            </div>
          </div>
          <audio
            ref="audioEl"
            style="display: none"
            @play="isPlaying = true"
            @pause="isPlaying = false"
            @ended="isPlaying = false"
          />
        </section>

        <section class="card glass">
          <div class="card-head"><h2>处理流程</h2></div>
          <div class="pipeline">
            <div
              v-for="(p, i) in pipeline"
              :key="p.label"
              class="pl-step"
              :class="p.status"
            >
              <div class="pl-icon">
                <el-icon v-if="p.status === 'done'"><Select /></el-icon>
                <el-icon v-else-if="p.status === 'active'" class="spin"><Loading /></el-icon>
                <span v-else>{{ i + 1 }}</span>
              </div>
              <div class="pl-text">
                <div class="pl-label">{{ p.label }}</div>
                <div class="pl-desc">{{ stepDesc(p.key) }}</div>
              </div>
            </div>
          </div>
        </section>

        <section v-if="failed" class="card glass error-card">
          <div class="card-head"><h2>失败原因</h2></div>
          <div class="error-msg">{{ currentWork?.error || '推理失败，请查看日志' }}</div>
          <div v-if="currentWork?.log_path" class="error-path" :title="currentWork.log_path">
            日志路径：{{ currentWork.log_path }}
          </div>
          <div class="error-actions">
            <el-button round class="ghost-btn" @click="openLog">
              <el-icon class="el-icon--left"><Document /></el-icon>打开日志文件夹
            </el-button>
            <el-button round class="ghost-btn" @click="retry">
              <el-icon class="el-icon--left"><RefreshRight /></el-icon>重试
            </el-button>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import {
  UploadFilled,
  Headset,
  Close,
  Right,
  Microphone,
  Select,
  MagicStick,
  VideoPlay,
  VideoPause,
  Download,
  Loading,
  Document,
  RefreshRight,
  Operation,
  Clock,
  Plus,
  Check,
  Upload,
  ZoomIn,
  ZoomOut,
  Refresh,
  Scissor,
  Connection,
  Mute,
  Delete,
  FullScreen,
  RefreshLeft,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  api,
  type WorkDTO,
  type PipelineStep,
  type DownloadedMusic,
  type LyricLine,
  type MusicSource,
  type BlendModel,
  type BlendSegment,
  type CreateWorkflow,
  type InferenceParams,
  type InferencePreset,
  type InferenceQueueStatus,
} from '@/api'
import { useModelsStore } from '@/stores/models'
import { useSystemStore } from '@/stores/system'
import { useWorksStore } from '@/stores/works'

defineOptions({ name: 'CreatePage' })

const modelsStore = useModelsStore()
const systemStore = useSystemStore()
const worksStore = useWorksStore()
const router = useRouter()
const { models, defaultId } = storeToRefs(modelsStore)

interface Song {
  name: string
  path: string
  hint: string
}

// 记忆上次使用的推理参数（localStorage，跨重启保留）
const PREFS_KEY = 'xb-create-prefs'
function loadPrefs(): Record<string, unknown> {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    if (raw) return JSON.parse(raw) as Record<string, unknown>
  } catch {
    /* ignore */
  }
  return {}
}
const prefs = loadPrefs()
const num = (v: unknown, d: number) => (typeof v === 'number' ? v : d)
const str = (v: unknown, d: string) => (typeof v === 'string' ? v : d)

const song = ref<Song | null>(null)
const selectedModel = ref<string>('')

const uvrModels = ['MDX-Net', 'Demucs v4', 'VR Arch']
const uvrModel = ref(str(prefs.uvrModel, 'MDX-Net'))

const f0Methods = ['rmvpe', 'crepe', 'harvest', 'pm']
const f0Method = ref(str(prefs.f0Method, 'rmvpe'))

const pitch = ref(num(prefs.pitch, 0))
const formantShift = ref(Math.max(-2, Math.min(2, num(prefs.formantShift, 0))))
const indexRate = ref(num(prefs.indexRate, 0.75))
const rmsMix = ref(num(prefs.rmsMix, 0.25))
const diffusionRatio = ref(num(prefs.diffusionRatio, 0.5))
const seedVcReferenceAudio = ref(str(prefs.seedVcReferenceAudio, ''))
const presets = ref<InferencePreset[]>([])
const selectedPresetId = ref('')
const queueStatus = ref<InferenceQueueStatus>({ running: false, pending: [], size: 0 })

/* RVC 专属参数 */
const rvcVersions = ['v2', 'v1']
const protect = ref(num(prefs.protect, 0.33))
const filterRadius = ref(num(prefs.filterRadius, 3))
const rvcVersion = ref(str(prefs.rvcVersion, 'v2'))

/* 模型框架辅助：用于单/多模型参数面板按框架切换、下拉显示框架标签 */
function frameworkOf(id: string): string {
  return models.value.find((m) => m.id === id)?.framework || 'so-vits-svc'
}
function frameworkLabel(id: string): string {
  const map: Record<string, string> = {
    'so-vits-svc': 'So-VITS-SVC',
    rvc: 'RVC',
    'seed-vc': 'SeedVC',
    'ddsp-svc': 'DDSP-SVC',
    other: '其他',
  }
  return map[id] || id || 'So-VITS-SVC'
}
function qualitySteps(ratio: number): number {
  return Math.max(1, Math.round(10 + Math.max(0, Math.min(1, ratio || 0)) * 40))
}
function ddspQualitySteps(ratio: number): number {
  return Math.round(50 + Math.max(0, Math.min(1, ratio || 0)) * 50)
}
function signedFormantShift(value: number): string {
  const normalized = Number(Math.max(-2, Math.min(2, value || 0)).toFixed(2))
  return `${normalized > 0 ? '+' : ''}${normalized.toFixed(2)}`
}
function baseName(p: string): string {
  return p ? p.split(/[/\\]/).pop() || p : ''
}
const selectedFramework = computed(() => frameworkOf(selectedModel.value))

/* 模型框架筛选：'' = 全部；只在存在多种框架时展示筛选条 */
const modelFilter = ref('')
const availableFrameworks = computed(() => {
  const seen: string[] = []
  for (const m of models.value) {
    const fw = m.framework || 'so-vits-svc'
    if (!seen.includes(fw)) seen.push(fw)
  }
  return seen
})
const filteredModels = computed(() =>
  modelFilter.value
    ? models.value.filter((m) => (m.framework || 'so-vits-svc') === modelFilter.value)
    : models.value,
)

function deviceOptionsFor(framework: string) {
  return systemStore.optionsForFramework([framework, 'uvr']).map((item) => ({
    v: item.value,
    label: item.label,
    name: item.name,
  }))
}
const deviceOptions = computed(() => deviceOptionsFor(selectedFramework.value))
const device = ref(str(prefs.device, 'auto'))
const deviceHint = computed(() => {
  const selected = deviceOptions.value.find((item) => item.v === device.value) || deviceOptions.value[0]
  if (!selected) return '当前环境未报告可用推理设备'
  const name = selected.name ? ` · ${selected.name}` : ''
  return `当前环境：${selected.label}${name}`
})

function normalizeDeviceForFramework(value: string, framework: string): string {
  const allowed = deviceOptionsFor(framework).map((item) => item.v)
  return allowed.some((item) => item === value) ? value : 'auto'
}

function normalizeDeviceSelections() {
  device.value = normalizeDeviceForFramework(device.value, selectedFramework.value)
  for (const [id, params] of Object.entries(modelParams)) {
    params.device = normalizeDeviceForFramework(params.device, frameworkOf(id))
  }
}

/* ===== 多模型混合翻唱 ===== */
type MultiParams = {
  pitch: number
  formantShift: number
  diffusionRatio: number
  f0Method: string
  device: string
  indexRate: number
  rmsMix: number
  protect: number
  filterRadius: number
  rvcVersion: string
  referenceAudio: string
}

type ParamValues = MultiParams

function paramsForFramework(framework: string, values: ParamValues): InferenceParams {
  const params: InferenceParams = {
    pitch: Math.round(values.pitch),
    uvr_model: uvrModel.value,
    device: values.device,
  }
  if (framework === 'seed-vc') {
    params.diffusion_ratio = values.diffusionRatio
    params.reference_audio = values.referenceAudio
  } else if (framework === 'rvc') {
    params.f0_method = values.f0Method
    params.index_rate = values.indexRate
    params.rms_mix = values.rmsMix
    params.protect = values.protect
    params.filter_radius = Math.round(values.filterRadius)
    params.rvc_version = values.rvcVersion
  } else if (framework === 'ddsp-svc') {
    params.f0_method = values.f0Method
    params.ddsp_infer_steps = ddspQualitySteps(values.diffusionRatio)
    params.ddsp_formant_shift = Number(Math.max(-2, Math.min(2, values.formantShift)).toFixed(2))
  } else {
    params.f0_method = values.f0Method
    params.diffusion_ratio = values.diffusionRatio
  }
  return params
}
const mode = ref<'single' | 'multi'>(prefs.mode === 'multi' ? 'multi' : 'single')
const workflowKeys: CreateWorkflow[] = [
  'auto_mix',
  'auto_vocal_merge',
  'manual_vocal_merge',
  'auto_then_editor',
  'full_manual_editor',
]
const vocalMergeWorkflows: CreateWorkflow[] = ['auto_vocal_merge', 'manual_vocal_merge']
const isWorkflow = (value: unknown): value is CreateWorkflow =>
  typeof value === 'string' && workflowKeys.includes(value as CreateWorkflow)
function isVocalMergeWorkflow(value: CreateWorkflow) {
  return vocalMergeWorkflows.includes(value)
}
function normalizeWorkflowForMode(value: CreateWorkflow, targetMode = mode.value): CreateWorkflow {
  return targetMode === 'single' && isVocalMergeWorkflow(value) ? 'auto_mix' : value
}
const workflow = ref<CreateWorkflow>(
  normalizeWorkflowForMode(isWorkflow(prefs.workflow) ? prefs.workflow : 'auto_mix', mode.value),
)
const workflowOptions: {
  key: CreateWorkflow
  no: string
  title: string
  desc: string
  tag?: string
}[] = [
  { key: 'auto_mix', no: '01', title: '自动混音合成', desc: '自动输出人声 + 伴奏的完整成品', tag: '默认' },
  { key: 'auto_vocal_merge', no: '02', title: '自动人声合并', desc: '自动合并转换后人声，只输出人声成品' },
  { key: 'manual_vocal_merge', no: '03', title: '手动人声合并', desc: '生成可编辑素材，完成后进入编辑器合并' },
  { key: 'auto_then_editor', no: '04', title: '自动 + 编辑器二次调整', desc: '先自动出成品，再进入编辑器微调' },
  { key: 'full_manual_editor', no: '05', title: '全手动编辑', desc: '不启动自动推理，直接创建编辑工程' },
]
const availableWorkflowOptions = computed(() =>
  workflowOptions.filter((item) => mode.value === 'multi' || !isVocalMergeWorkflow(item.key)),
)
function workflowOpensEditor(value: CreateWorkflow, targetMode: 'single' | 'multi') {
  return value === 'auto_then_editor' || (targetMode === 'multi' && value === 'manual_vocal_merge')
}

watch([mode, workflow], () => {
  const next = normalizeWorkflowForMode(workflow.value, mode.value)
  if (next !== workflow.value) workflow.value = next
})

// 已勾选模型的 id（保持勾选顺序）与各自参数
const selectedMulti = ref<string[]>([])
const modelParams = reactive<Record<string, MultiParams>>({})
const TIMELINE_MODEL_COLORS = [
  '#00d5ff',
  '#ff4f8b',
  '#35d07f',
  '#ffb02e',
  '#8b6dff',
  '#2dd4bf',
  '#ff6b35',
  '#5c8dff',
  '#f43f5e',
  '#84cc16',
  '#e879f9',
  '#14b8a6',
]

function timelineModelColor(index: number): string {
  if (index >= 0 && index < TIMELINE_MODEL_COLORS.length) {
    return TIMELINE_MODEL_COLORS[index]!
  }
  const hue = Math.round((index * 137.508) % 360)
  return `hsl(${hue} 78% 56%)`
}

function defaultParams(): MultiParams {
  return {
    pitch: pitch.value,
    formantShift: formantShift.value,
    diffusionRatio: diffusionRatio.value,
    f0Method: f0Method.value,
    device: device.value,
    indexRate: indexRate.value,
    rmsMix: rmsMix.value,
    protect: protect.value,
    filterRadius: filterRadius.value,
    rvcVersion: rvcVersion.value,
    referenceAudio: '',
  }
}
function mp(id: string): MultiParams {
  let p = modelParams[id]
  if (!p) {
    p = defaultParams()
    modelParams[id] = p
  }
  return p
}
function isPicked(id: string) {
  return selectedMulti.value.includes(id)
}
function pickedIndex(id: string) {
  return selectedMulti.value.indexOf(id)
}
function pickedModelColor(id: string): string {
  const idx = pickedIndex(id)
  if (idx >= 0) return timelineModelColor(idx)
  return models.value.find((m) => m.id === id)?.color || 'var(--xb-primary)'
}
function modelDisplayColor(id: string, fallback: string) {
  return isPicked(id) ? pickedModelColor(id) : fallback
}
function togglePick(id: string) {
  if (isPicked(id)) {
    selectedMulti.value = selectedMulti.value.filter((x) => x !== id)
  } else {
    if (!modelParams[id]) modelParams[id] = defaultParams()
    selectedMulti.value = [...selectedMulti.value, id]
  }
}
const pickedModels = computed(() =>
  selectedMulti.value
    .map((id, index) => {
      const model = models.value.find((m) => m.id === id)
      return model ? { id: model.id, name: model.name, color: timelineModelColor(index) } : null
    })
    .filter((m): m is { id: string; name: string; color: string } => !!m),
)

// 歌词获取与对齐
const songQuery = ref('')
const songIndex = ref(1)
const lyricSrc = ref('wy')
const lyricSources = ref<MusicSource[]>([{ id: 'wy', name: '网易云音乐', cookie: false }])
const lyrics = ref<LyricLine[]>([])
const offset = ref(0)
const lyricLoading = ref(false)
const lyricTried = ref(false)
const audioDuration = ref(0)

/* ====== 可编辑片段（多模型时间轴的唯一数据源） ======
   片段与歌词解耦：歌词只作为「初始切分」与「吸附锚点」，
   片段拥有独立的起止时间与模型指派，可拖动边界 / 拆分 / 合并。 */
interface EditSegment {
  id: string
  start: number
  end: number
  modelIds: string[]
  text: string
}
const segments = ref<EditSegment[]>([])
let segSeq = 0
function newSegId() {
  segSeq += 1
  return `seg_${segSeq}_${Date.now().toString(36)}`
}

/** 由当前歌词（含 offset）初始化片段：逐句一段，默认指派首个已选模型。 */
function buildSegmentsFromLyrics() {
  const arr = lyrics.value
  const first = pickedModels.value[0]?.id || ''
  const dur = audioDuration.value || (arr.length ? (arr[arr.length - 1]!.time + offset.value + 5) : 0)
  segments.value = arr.map((ln, i) => {
    const start = Math.max(0, ln.time + offset.value)
    const nextLine = arr[i + 1]
    const end = nextLine ? Math.max(start, nextLine.time + offset.value) : Math.max(start + 1, dur)
    return {
      id: newSegId(),
      start,
      end,
      modelIds: first ? [first] : [],
      text: ln.text,
    }
  })
}

/** 片段按起点排序（模板与生成都以此为准）。 */
const sortedSegments = computed(() =>
  [...segments.value].sort((a, b) => a.start - b.start),
)

async function fetchLyrics() {
  const q = songQuery.value.trim()
  if (!q) {
    ElMessage.info('请输入歌曲名')
    return
  }
  lyricLoading.value = true
  lyricTried.value = true
  try {
    const res = await api.getMusicLyrics(q, songIndex.value || 1, lyricSrc.value)
    if (!res.ok || !res.lines?.length) {
      lyrics.value = []
      segments.value = []
      ElMessage.error(res.error || '未获取到歌词')
      return
    }
    lyrics.value = res.lines
    if (song.value?.path) {
      audioDuration.value = await api.getAudioDuration(song.value.path)
    }
    buildSegmentsFromLyrics()
    clearHistory()
  } finally {
    lyricLoading.value = false
  }
}

/* ---- 导入本地带时间轴的歌词文件（.lrc）---- */
const lrcInput = ref<HTMLInputElement | null>(null)
function pickLrc() {
  lrcInput.value?.click()
}
function onLrcFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const reader = new FileReader()
  reader.onload = async () => {
    const lines = parseLrc(String(reader.result || ''))
    if (!lines.length) {
      ElMessage.error('未在文件中找到带时间轴的歌词（需 LRC 格式，形如 [00:12.34] 歌词）')
      return
    }
    lyrics.value = lines
    lyricTried.value = true
    if (song.value?.path && !audioDuration.value) {
      audioDuration.value = await api.getAudioDuration(song.value.path)
    }
    buildSegmentsFromLyrics()
    clearHistory()
    ElMessage.success(`已导入 ${lines.length} 句歌词`)
  }
  reader.onerror = () => ElMessage.error('读取歌词文件失败')
  reader.readAsText(file, 'utf-8')
}
/** 解析 LRC 文本为按时间排序的歌词行；支持一行多时间标签，忽略元数据与纯时间空行。 */
function parseLrc(text: string): LyricLine[] {
  const out: LyricLine[] = []
  const tagRe = /\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g
  for (const raw of text.split(/\r?\n/)) {
    tagRe.lastIndex = 0
    const times: number[] = []
    let m: RegExpExecArray | null
    while ((m = tagRe.exec(raw)) !== null) {
      const mm = parseInt(m[1]!, 10)
      const ss = parseInt(m[2]!, 10)
      let frac = 0
      if (m[3]) frac = parseInt(m[3], 10) / Math.pow(10, m[3].length)
      times.push(mm * 60 + ss + frac)
    }
    if (!times.length) continue
    const content = raw.replace(tagRe, '').trim()
    if (!content) continue
    for (const t of times) out.push({ time: Math.max(0, t), text: content })
  }
  out.sort((a, b) => a.time - b.time)
  return out
}

const MIN_SEG = 0.3 // 片段最短时长（秒），防止拖出零宽片段
const SNAP_PX = 8 // 吸附阈值（像素）

function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v))
}
function segById(id: string): EditSegment | undefined {
  return segments.value.find((s) => s.id === id)
}

/* ====== 撤销 / 重做 / 复原 ======
   每次会改动片段的操作前调用 commit() 存一份快照；
   undo/redo 在过去/未来栈之间搬运，reset 复原为歌词初始切分。 */
const past = ref<string[]>([])
const future = ref<string[]>([])
const HIST_MAX = 120
function snapshot(): string {
  return JSON.stringify(segments.value)
}
/** 在改动发生「之前」保存当前状态，并清空重做栈。 */
function commit() {
  past.value.push(snapshot())
  if (past.value.length > HIST_MAX) past.value.shift()
  future.value = []
}
function clearHistory() {
  past.value = []
  future.value = []
}
const canUndo = computed(() => past.value.length > 0)
const canRedo = computed(() => future.value.length > 0)
function undo() {
  if (!past.value.length) return
  future.value.push(snapshot())
  segments.value = JSON.parse(past.value.pop() as string)
}
function redo() {
  if (!future.value.length) return
  past.value.push(snapshot())
  segments.value = JSON.parse(future.value.pop() as string)
}
async function resetTimeline() {
  if (!lyrics.value.length) return
  try {
    await ElMessageBox.confirm(
      '将丢弃所有拖动 / 拆分 / 合并 / 指派的修改，恢复为按歌词时间的初始切分。是否继续？',
      '复原时间轴',
      { confirmButtonText: '复原', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  commit()
  buildSegmentsFromLyrics()
  ElMessage.success('已复原为初始时间轴')
}

/* ---- 片段模型指派（独立于歌词，按片段 id 操作）---- */
function assignAll(id: string) {
  commit()
  for (const s of segments.value) s.modelIds = [id]
}
function modelName(id: string): string {
  return pickedModels.value.find((x) => x.id === id)?.name || '未知模型'
}
function modelColor(id: string): string {
  return pickedModels.value.find((x) => x.id === id)?.color || 'var(--xb-primary)'
}
/** 已指派模型胶囊的配色（淡底 + 同色文字/描边）。 */
function chipStyle(id: string) {
  const c = modelColor(id)
  return {
    color: c,
    borderColor: c,
    background: `color-mix(in srgb, ${c} 14%, transparent)`,
  }
}
function isAssigned(segId: string, id: string): boolean {
  return !!segById(segId)?.modelIds.includes(id)
}
/** 切换某模型在该片段的「参与演唱 / 合唱」状态。 */
function toggleAssign(segId: string, id: string) {
  const s = segById(segId)
  if (!s) return
  commit()
  const idx = s.modelIds.indexOf(id)
  if (idx >= 0) s.modelIds.splice(idx, 1)
  else s.modelIds.push(id)
}
function removeAssign(segId: string, id: string) {
  const s = segById(segId)
  if (!s) return
  commit()
  s.modelIds = s.modelIds.filter((x) => x !== id)
}
function clearSegModels(segId: string) {
  const s = segById(segId)
  if (!s) return
  commit()
  s.modelIds = []
}

/* ---- 合唱多模型：超过上限折叠为 +N，避免撑破布局 ---- */
const CHIP_LIMIT = 3
const expandedSegs = ref<Set<string>>(new Set())
function isExpanded(id: string): boolean {
  return expandedSegs.value.has(id)
}
function toggleExpand(id: string) {
  const next = new Set(expandedSegs.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedSegs.value = next
}
function visibleChips(seg: EditSegment): string[] {
  if (isExpanded(seg.id) || seg.modelIds.length <= CHIP_LIMIT) return seg.modelIds
  return seg.modelIds.slice(0, CHIP_LIMIT)
}

/* ---- 拆分 / 合并 / 删除片段 ---- */
function splitSegment(seg: EditSegment) {
  const mid = (seg.start + seg.end) / 2
  if (mid - seg.start < MIN_SEG || seg.end - mid < MIN_SEG) {
    ElMessage.info('片段太短，无法拆分')
    return
  }
  commit()
  const right: EditSegment = {
    id: newSegId(),
    start: mid,
    end: seg.end,
    modelIds: [...seg.modelIds],
    text: seg.text,
  }
  seg.end = mid
  const idx = segments.value.findIndex((s) => s.id === seg.id)
  segments.value.splice(idx + 1, 0, right)
  rederiveTexts()
}
function mergeWithNext(seg: EditSegment) {
  const ord = sortedSegments.value
  const pos = ord.findIndex((s) => s.id === seg.id)
  const next = ord[pos + 1]
  if (!next) {
    ElMessage.info('已是最后一个片段')
    return
  }
  commit()
  seg.end = Math.max(seg.end, next.end)
  const merged = [...seg.modelIds]
  for (const m of next.modelIds) if (!merged.includes(m)) merged.push(m)
  seg.modelIds = merged
  seg.text = [seg.text, next.text].filter(Boolean).join(' ')
  segments.value = segments.value.filter((s) => s.id !== next.id)
  rederiveTexts()
}
function removeSegment(seg: EditSegment) {
  commit()
  segments.value = segments.value.filter((s) => s.id !== seg.id)
}

function fmtTime(t: number) {
  const s = Math.max(0, t)
  const mm = Math.floor(s / 60)
  const ss = Math.floor(s % 60)
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
}

/* ---- 时间轴尺寸 / 缩放 ---- */
const zoom = ref(1)
const trackEl = ref<HTMLElement | null>(null)
const trackW = ref(800)
function measureTrack() {
  // 仅在元素可见（宽度 > 0）时更新，避免对话框关闭/隐藏瞬间量到 0 造成换算错乱
  const w = trackEl.value?.clientWidth ?? 0
  if (w > 0) trackW.value = w
}
/** 时间轴内容像素宽（= 可视宽 × 缩放倍数），用于像素↔时间换算。 */
const innerPx = computed(() => Math.max(320, trackW.value * zoom.value))
function zoomIn() {
  zoom.value = Math.min(10, +(zoom.value * 1.5).toFixed(3))
}
function zoomOut() {
  zoom.value = Math.max(1, +(zoom.value / 1.5).toFixed(3))
}
function zoomReset() {
  zoom.value = 1
}

/* ---- 弹出放大编辑 ---- */
const tlDialog = ref(false)
function openTlDialog() {
  // 每次进入放大编辑都从 100% 起步，避免上次的缩放残留把轨道撑爆
  zoom.value = 1
  tlDialog.value = true
}
function onTlOpened() {
  // 对话框过渡结束后再量取轨道宽度，保证像素↔时间换算正确
  measureTrack()
}
function onTlClosed() {
  // 关闭即复位缩放，确保任何缩放状态都不会泄漏到关闭后的视图
  zoom.value = 1
}

/* ---- 时间轴总览 ---- */
/** 拖动期间冻结的总时长：拖动时锁定，避免「拖长片段→总时长变大→整轴重新缩放→边缘跑飞」的自反馈。 */
const frozenDur = ref(0)
/** 总时长（= 时间轴总宽度）：仅由音频时长 / 歌词兜底决定，是一条固定的轴。
    刻意不把「片段最末端」纳入计算——否则拉长某个片段会撑大总时长，导致整轴（含迷你预览）
    被等比例重新缩放。固定总宽后，编辑片段只是在这条轴上重新分配，永远不会超过总宽。
    拖动中返回冻结值保持比例稳定。 */
const timelineDuration = computed(() => {
  if (frozenDur.value > 0) return frozenDur.value
  const arr = lyrics.value
  const last = arr[arr.length - 1]
  const byLyric = last ? last.time + offset.value + 5 : 0
  return Math.max(1, audioDuration.value || 0, byLyric)
})

/** 吸附锚点：0 / 总时长 / 各歌词时间 / 其它片段边界。 */
function snapCandidates(excludeId: string): number[] {
  const out: number[] = [0, timelineDuration.value]
  for (const ln of lyrics.value) out.push(Math.max(0, ln.time + offset.value))
  for (const s of segments.value) {
    if (s.id === excludeId) continue
    out.push(s.start, s.end)
  }
  return out
}
/** 把时间吸附到最近的锚点（阈值内）。pxPerSec 传入拖动锁定值，确保吸附判定与屏幕一致。 */
function applySnap(t: number, excludeId: string, pxPerSec?: number): number {
  const pps = pxPerSec ?? innerPx.value / timelineDuration.value
  let best = t
  let bestDpx = SNAP_PX + 1
  for (const c of snapCandidates(excludeId)) {
    const dpx = Math.abs((c - t) * pps)
    if (dpx < bestDpx) {
      bestDpx = dpx
      best = c
    }
  }
  return bestDpx <= SNAP_PX ? best : t
}

/** 片段映射为时间轴色块（按片段排序，百分比定位于内容宽度内）。 */
const timelineBlocks = computed(() => {
  const dur = timelineDuration.value
  return sortedSegments.value.map((s) => {
    const ids = s.modelIds
    const label = ids.length === 0 ? '' : ids.length === 1 ? modelName(ids[0]!) : '合唱'
    const leftPct = clamp((s.start / dur) * 100, 0, 100)
    const rawWidthPct = ((s.end - s.start) / dur) * 100
    return {
      id: s.id,
      seg: s,
      start: s.start,
      end: s.end,
      ids,
      text: s.text,
      label,
      leftPct,
      // 宽度封顶到「轴右边界 - 左起点」，任何越界片段都被裁进 100% 内，绝不撑破轨道
      widthPct: clamp(Math.max(0.4, rawWidthPct), 0.4, Math.max(0.4, 100 - leftPct)),
    }
  })
})

/** 自适应时间刻度：随缩放在内容宽度上约每 ~90px 一格。 */
const rulerMarks = computed(() => {
  const dur = timelineDuration.value
  const target = Math.max(4, Math.round(innerPx.value / 90))
  const rawStep = dur / target
  const nice = [1, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 300]
  let step = nice.find((s) => s >= rawStep) || Math.ceil(rawStep)
  // 安全阀：刻度数量封顶，杜绝异常时长/缩放导致刷出成千上万个刻度撑爆 DOM
  if (dur / step > 400) step = Math.ceil(dur / 400)
  const marks: { pct: number; label: string }[] = []
  for (let t = 0; t <= dur + 0.001; t += step) {
    marks.push({ pct: (t / dur) * 100, label: fmtTime(t) })
  }
  return marks
})

/** 色块配色：无模型=间奏底色；单模型=该色；多模型=合唱渐变。 */
function blockStyle(ids: string[]) {
  if (!ids.length) return {}
  if (ids.length === 1) {
    const c = modelColor(ids[0]!)
    return { background: c, borderColor: c }
  }
  const stops = ids.map((id) => modelColor(id)).join(', ')
  return { background: `linear-gradient(90deg, ${stops})`, borderColor: 'transparent' }
}

/* ---- 边界拖动（pointer 事件，支持吸附）---- */
type DragEdge = 'start' | 'end' | 'move'
interface DragState {
  id: string
  edge: DragEdge
  startX: number
  origStart: number
  origEnd: number
  /** 拖动起始时锁定的「像素/秒」——取轨道真实渲染宽度，保证拖动距离与屏幕完全一致。 */
  pxPerSec: number
}
let drag: DragState | null = null
const draggingId = ref<string | null>(null)
/** 轨道真实渲染像素宽：以实际 DOM 宽度为准（而非 innerPx 计算值），
    避免 min-width / 量取滞后导致「像素↔秒」换算偏大，从而拖一点却拉伸很多。 */
function trackPxWidth(): number {
  const inner = trackEl.value?.querySelector('.tl-inner') as HTMLElement | null
  const w = inner?.getBoundingClientRect().width || 0
  return w > 0 ? w : Math.max(320, innerPx.value)
}
function beginDrag(seg: EditSegment, edge: DragEdge, ev: PointerEvent) {
  ev.preventDefault()
  ev.stopPropagation()
  commit() // 每次拖动存一份拖动前快照，便于撤销
  // 冻结总时长 + 像素基准：整段拖动期间比例完全稳定，不会越拖越长
  const durStart = timelineDuration.value
  frozenDur.value = durStart
  const pxPerSec = trackPxWidth() / durStart
  drag = { id: seg.id, edge, startX: ev.clientX, origStart: seg.start, origEnd: seg.end, pxPerSec }
  draggingId.value = seg.id
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragEnd)
}
function onDragMove(ev: PointerEvent) {
  if (!drag) return
  const seg = segById(drag.id)
  if (!seg) return
  const dur = timelineDuration.value
  const dt = (ev.clientX - drag.startX) / drag.pxPerSec
  if (drag.edge === 'start') {
    let ns = clamp(drag.origStart + dt, 0, seg.end - MIN_SEG)
    ns = clamp(applySnap(ns, seg.id, drag.pxPerSec), 0, seg.end - MIN_SEG)
    seg.start = ns
  } else if (drag.edge === 'end') {
    let ne = clamp(drag.origEnd + dt, seg.start + MIN_SEG, dur)
    ne = clamp(applySnap(ne, seg.id, drag.pxPerSec), seg.start + MIN_SEG, dur)
    seg.end = ne
  } else {
    const len = drag.origEnd - drag.origStart
    let ns = clamp(drag.origStart + dt, 0, dur - len)
    ns = clamp(applySnap(ns, seg.id, drag.pxPerSec), 0, dur - len)
    seg.start = ns
    seg.end = ns + len
  }
}
function onDragEnd() {
  if (drag) {
    const seg = segById(drag.id)
    const moved =
      !!seg && (Math.abs(seg.start - drag.origStart) > 1e-3 || Math.abs(seg.end - drag.origEnd) > 1e-3)
    const id = drag.id
    drag = null
    draggingId.value = null
    frozenDur.value = 0 // 解冻总时长
    window.removeEventListener('pointermove', onDragMove)
    window.removeEventListener('pointerup', onDragEnd)
    // 拉伸覆盖到邻居时：自动吞并 / 推挤消除重叠，再按覆盖到的歌词刷新文案
    if (moved) {
      consolidateOverlaps(id)
      rederiveTexts()
    } else {
      // 没有实际移动（只是点了下手柄）→ 回收刚才多存的快照，避免空撤销
      past.value.pop()
    }
    return
  }
  drag = null
  draggingId.value = null
  frozenDur.value = 0
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
}

/** 让被拖动片段 d 「吞并 / 推挤」与之重叠的邻居，保证片段不重叠。
    完全落入 d 范围的邻居被吞并（删除，覆盖权归 d）；部分重叠的邻居被推挤出 d。 */
function consolidateOverlaps(id: string) {
  const d = segById(id)
  if (!d) return
  const keep: EditSegment[] = []
  for (const o of segments.value) {
    if (o.id === id) {
      keep.push(o)
      continue
    }
    // 完全被 d 覆盖 → 吞并丢弃
    if (o.start >= d.start - 1e-3 && o.end <= d.end + 1e-3) continue
    // d 夹在 o 内部（极少见）→ 截到 d 左侧
    if (o.start < d.start && o.end > d.end) {
      o.end = d.start
    } else {
      // 右侧部分重叠：o 起点落在 d 内 → 推后
      if (o.start < d.end - 1e-3 && o.start >= d.start - 1e-3) o.start = d.end
      // 左侧部分重叠：o 终点落在 d 内 → 提前
      if (o.end > d.start + 1e-3 && o.end <= d.end + 1e-3) o.end = d.start
    }
    if (o.end - o.start >= MIN_SEG) keep.push(o)
  }
  segments.value = keep
}

/** 依据各片段「覆盖到的歌词起点」重算文案——拖动 / 拆分 / 合并后让歌词标注与覆盖范围保持一致。 */
function rederiveTexts() {
  const ls = lyrics.value.map((l) => ({
    t: Math.max(0, l.time + offset.value),
    text: l.text,
  }))
  for (const s of segments.value) {
    const hit = ls.filter((l) => l.t >= s.start - 1e-3 && l.t < s.end - 1e-3).map((l) => l.text)
    // 仅在确有歌词起点落入时才覆盖，避免把跨越长音的片段误清空
    if (hit.length) s.text = hit.join(' ')
  }
}

const alignStatus = computed(() => {
  const dur = audioDuration.value
  const arr = lyrics.value
  const lastLine = arr[arr.length - 1]
  if (!arr.length || !lastLine) return { type: 'idle', text: '' }
  const last = lastLine.time + offset.value
  if (!dur) return { type: 'warn', text: `共 ${lyrics.value.length} 句；未知音频时长，建议核对偏移` }
  const diff = last - dur
  if (last > dur + 2) {
    return { type: 'bad', text: `歌词末句 ${fmtTime(last)} 超出音频 ${fmtTime(dur)}，请调整偏移或核对版本` }
  }
  if (Math.abs(diff) <= 8 || last <= dur) {
    return { type: 'ok', text: `对齐良好：${lyrics.value.length} 句 · 音频 ${fmtTime(dur)}` }
  }
  return { type: 'warn', text: `请核对：歌词末句 ${fmtTime(last)} / 音频 ${fmtTime(dur)}` }
})

// 任一参数变化即写回 localStorage
watch(
  [uvrModel, f0Method, pitch, formantShift, indexRate, rmsMix, diffusionRatio, seedVcReferenceAudio, device, mode, workflow, protect, filterRadius, rvcVersion],
  () => {
    try {
      localStorage.setItem(
        PREFS_KEY,
        JSON.stringify({
          uvrModel: uvrModel.value,
          f0Method: f0Method.value,
          pitch: pitch.value,
          formantShift: formantShift.value,
          indexRate: indexRate.value,
          rmsMix: rmsMix.value,
          diffusionRatio: diffusionRatio.value,
          seedVcReferenceAudio: seedVcReferenceAudio.value,
          device: device.value,
          mode: mode.value,
          workflow: workflow.value,
          protect: protect.value,
          filterRadius: filterRadius.value,
          rvcVersion: rvcVersion.value,
        }),
      )
    } catch {
      /* ignore */
    }
  },
)

const isPlaying = ref(false)
const currentWork = ref<WorkDTO | null>(null)

const stepMeta: Record<string, string> = {
  separate: 'UVR 提取干声与伴奏',
  f0: '分析音高曲线',
  infer: '加载模型进行歌声转换',
  split: '按歌词时间轴切分人声',
  merge: '按顺序拼接各模型片段',
  mix: 'ffmpeg 合成与重采样',
}
const singlePipeline: PipelineStep[] = [
  { key: 'separate', label: '人声分离', status: 'wait' },
  { key: 'f0', label: 'F0 提取', status: 'wait' },
  { key: 'infer', label: '模型推理', status: 'wait' },
  { key: 'mix', label: '混音合成', status: 'wait' },
]
const multiPipeline: PipelineStep[] = [
  { key: 'separate', label: '人声分离', status: 'wait' },
  { key: 'split', label: '歌词分割', status: 'wait' },
  { key: 'infer', label: '逐段推理', status: 'wait' },
  { key: 'merge', label: '人声合并', status: 'wait' },
  { key: 'mix', label: '混音合成', status: 'wait' },
]

const pipeline = computed<PipelineStep[]>(
  () => currentWork.value?.steps ?? (mode.value === 'multi' ? multiPipeline : singlePipeline),
)
const stepDesc = (key: string) => stepMeta[key] ?? ''

const isGenerating = computed(
  () => currentWork.value?.status === 'running' || currentWork.value?.status === 'queue',
)
const done = computed(() => currentWork.value?.status === 'done')
const failed = computed(() => currentWork.value?.status === 'failed')
const activeWorkflow = computed<CreateWorkflow>(() => {
  const saved = currentWork.value?.workflow
  return isWorkflow(saved) ? saved : workflow.value
})
const activeMode = computed<'single' | 'multi'>(() =>
  currentWork.value?.mode === 'multi' ? 'multi' : mode.value,
)
const editorAvailable = computed(() =>
  done.value && workflowOpensEditor(activeWorkflow.value, activeMode.value),
)
const canGenerate = computed(() => {
  if (!song.value) return false
  if (workflow.value === 'full_manual_editor') return true
  if (mode.value === 'single') {
    if (!selectedModel.value) return false
    if (selectedFramework.value === 'seed-vc' && !seedVcReferenceAudio.value) return false
    return true
  }
  // 多模型：至少选 1 个模型，且至少 1 个片段已指派
  return (
    selectedMulti.value.length > 0 &&
    selectedMulti.value.every((id) => frameworkOf(id) !== 'seed-vc' || !!mp(id).referenceAudio) &&
    segments.value.some((s) => s.modelIds.length > 0)
  )
})

const audioEl = ref<HTMLAudioElement | null>(null)
const audioLoadedFor = ref<string | null>(null)
const editorOpenedFor = ref<string | null>(null)

async function onTogglePlay() {
  const work = currentWork.value
  const el = audioEl.value
  if (!work || work.status !== 'done' || !el) return
  if (audioLoadedFor.value !== work.id) {
    const data = await api.getWorkAudio(work.id)
    if (!data) {
      ElMessage.error('无法加载生成的音频')
      return
    }
    el.src = data
    audioLoadedFor.value = work.id
  }
  if (el.paused) await el.play()
  else el.pause()
}

async function onExport() {
  const work = currentWork.value
  if (!work || work.status !== 'done') return
  const dest = await api.exportWork(work.id)
  if (dest) ElMessage.success('已导出到：' + dest)
  else ElMessage.info('已取消导出')
}

async function openLog() {
  if (currentWork.value) await api.openWorkLog(currentWork.value.id)
}

function currentParams() {
  return paramsForFramework(selectedFramework.value, {
    pitch: pitch.value,
    formantShift: formantShift.value,
    f0Method: f0Method.value,
    indexRate: indexRate.value,
    rmsMix: rmsMix.value,
    diffusionRatio: diffusionRatio.value,
    device: device.value,
    protect: protect.value,
    filterRadius: filterRadius.value,
    rvcVersion: rvcVersion.value,
    referenceAudio: selectedFramework.value === 'seed-vc' ? seedVcReferenceAudio.value : '',
  })
}

function applyParams(raw: Record<string, unknown>) {
  const ddspSteps = raw.ddsp_infer_steps
  const savedQuality = typeof ddspSteps === 'number'
    ? Math.max(0, Math.min(1, (ddspSteps - 10) / 40))
    : num(raw.diffusion_ratio, diffusionRatio.value)
  const next = {
    pitch: num(raw.pitch, pitch.value),
    formantShift: Math.max(-2, Math.min(2, num(raw.ddsp_formant_shift, formantShift.value))),
    f0Method: str(raw.f0_method, f0Method.value),
    indexRate: num(raw.index_rate, indexRate.value),
    rmsMix: num(raw.rms_mix, rmsMix.value),
    uvrModel: str(raw.uvr_model, uvrModel.value),
    diffusionRatio: savedQuality,
    device: str(raw.device, device.value),
    protect: num(raw.protect, protect.value),
    filterRadius: num(raw.filter_radius, filterRadius.value),
    rvcVersion: str(raw.rvc_version, rvcVersion.value),
    referenceAudio: str(raw.reference_audio, seedVcReferenceAudio.value),
  }
  pitch.value = next.pitch
  formantShift.value = next.formantShift
  f0Method.value = next.f0Method
  indexRate.value = next.indexRate
  rmsMix.value = next.rmsMix
  uvrModel.value = next.uvrModel
  diffusionRatio.value = next.diffusionRatio
  device.value = next.device
  protect.value = next.protect
  filterRadius.value = next.filterRadius
  rvcVersion.value = next.rvcVersion
  seedVcReferenceAudio.value = next.referenceAudio
  for (const id of selectedMulti.value) {
    const p = mp(id)
    p.pitch = next.pitch
    p.formantShift = next.formantShift
    p.f0Method = next.f0Method
    p.indexRate = next.indexRate
    p.rmsMix = next.rmsMix
    p.diffusionRatio = next.diffusionRatio
    p.device = next.device
    p.protect = next.protect
    p.filterRadius = next.filterRadius
    p.rvcVersion = next.rvcVersion
    if (frameworkOf(id) === 'seed-vc') p.referenceAudio = next.referenceAudio
  }
}

function applyPreset() {
  const preset = presets.value.find((p) => p.id === selectedPresetId.value)
  if (!preset) return
  applyParams(preset.params as Record<string, unknown>)
  ElMessage.success('已应用预设：' + preset.name)
}

async function savePreset() {
  try {
    const { value } = await ElMessageBox.prompt('给当前参数起一个名字', '保存参数预设', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: `预设 ${presets.value.length + 1}`,
    })
    const preset = await api.saveInferencePreset(value, { ...currentParams() })
    presets.value = await api.listInferencePresets()
    selectedPresetId.value = preset.id
    ElMessage.success('参数预设已保存')
  } catch {
    /* cancelled */
  }
}

async function deletePreset() {
  const id = selectedPresetId.value
  const preset = presets.value.find((p) => p.id === id)
  if (!id || !preset) return
  try {
    await ElMessageBox.confirm(`确定删除预设「${preset.name}」吗？`, '删除预设', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    if (await api.deleteInferencePreset(id)) {
      presets.value = await api.listInferencePresets()
      selectedPresetId.value = ''
      ElMessage.success('预设已删除')
    }
  } catch {
    /* cancelled */
  }
}

async function openWorkEditor(work = currentWork.value, auto = false) {
  if (!work || work.status !== 'done') return
  const project = await api.createEditorProjectFromWork(work.id)
  if (!project) {
    ElMessage.error(auto ? '自动进入编辑器失败，请手动打开编辑器' : '无法从该作品创建编辑工程')
    return
  }
  await router.push({ path: '/editor', query: { project: project.id } })
}

async function openCurrentWorkEditor() {
  await openWorkEditor(currentWork.value, false)
}

async function maybeOpenEditor(work: WorkDTO) {
  if (work.status !== 'done') return
  const wf = isWorkflow(work.workflow) ? work.workflow : workflow.value
  const workMode = work.mode === 'multi' ? 'multi' : 'single'
  if (!workflowOpensEditor(wf, workMode) || editorOpenedFor.value === work.id) return
  editorOpenedFor.value = work.id
  await openWorkEditor(work, true)
}

async function openManualEditor(title: string) {
  if (!song.value) return
  const project = await api.createEditorProjectFromAudio(song.value.path, title)
  if (!project) {
    ElMessage.error('无法创建全手动编辑工程，请确认音频文件仍然存在')
    return
  }
  await router.push({ path: '/editor', query: { project: project.id } })
}

async function retry() {
  const id = currentWork.value?.id
  if (!id) return
  const ok = await api.retryWork(id)
  if (ok) {
    editorOpenedFor.value = null
    startPolling(id)
  }
}

const overallState = computed(() => {
  const s = currentWork.value?.status
  if (s === 'running' || s === 'queue') return { type: 'running', text: '处理中' }
  if (s === 'done') return { type: 'done', text: '已完成' }
  if (s === 'failed') return { type: 'idle', text: '失败' }
  return { type: 'idle', text: '待生成' }
})

async function onPickSong() {
  const path = await api.pickAudioFile()
  if (!path) return
  const name = path.split(/[/\\]/).pop() || path
  song.value = { name, path, hint: '本地音频已选择' }
}

async function pickSeedVcReference() {
  const path = await api.pickAudioFile()
  if (path) seedVcReferenceAudio.value = path
}

async function pickMultiReference(id: string) {
  const path = await api.pickAudioFile()
  if (path) mp(id).referenceAudio = path
}

// 已下载素材（来自「资源获取」页）
const route = useRoute()
const downloaded = ref<DownloadedMusic[]>([])

function pickDownloaded(d: DownloadedMusic) {
  song.value = { name: d.name, path: d.path, hint: '已下载素材' }
}

async function loadDownloaded() {
  downloaded.value = await api.listMusic()
}

let timer: ReturnType<typeof setInterval> | null = null
function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
function startPolling(id: string) {
  stopPolling()
  timer = setInterval(async () => {
    const w = await api.getWork(id)
    if (w) currentWork.value = w
    if (!w || w.status === 'done' || w.status === 'failed') {
      stopPolling()
      if (w?.status === 'done') void maybeOpenEditor(w)
    }
  }, 800)
}

watch(currentWork, (work) => {
  if (work?.status === 'done') void maybeOpenEditor(work)
})

const generate = async () => {
  if (!canGenerate.value || isGenerating.value || !song.value) return
  isPlaying.value = false
  const title = song.value.name.replace(/\.[^.]+$/, '')
  const currentWorkflow = normalizeWorkflowForMode(workflow.value, mode.value)
  if (currentWorkflow !== workflow.value) workflow.value = currentWorkflow

  if (currentWorkflow === 'full_manual_editor') {
    await openManualEditor(title)
    return
  }

  if (mode.value === 'multi') {
    const missing = selectedMulti.value.find((id) => frameworkOf(id) === 'seed-vc' && !mp(id).referenceAudio)
    if (missing) {
      const name = models.value.find((m) => m.id === missing)?.name || 'SeedVC 模型'
      ElMessage.warning(`请为「${name}」选择参考音频`)
      return
    }
    // 片段为唯一数据源：起止已是绝对时间（offset 已并入），直接产出
    const outSegments: BlendSegment[] = []
    for (const s of sortedSegments.value) {
      const mids = s.modelIds.filter(Boolean)
      if (mids.length === 0) continue
      const start = Math.max(0, s.start)
      const end = Math.max(start, s.end)
      if (end > start) outSegments.push({ start, end, model_id: mids[0]!, model_ids: mids })
    }
    const blendModels: BlendModel[] = pickedModels.value.map((pm) => {
      const p = mp(pm.id)
      const framework = frameworkOf(pm.id)
      return {
        model_id: pm.id,
        params: paramsForFramework(framework, {
          pitch: p.pitch,
          formantShift: p.formantShift,
          f0Method: p.f0Method,
          indexRate: p.indexRate,
          rmsMix: p.rmsMix,
          diffusionRatio: p.diffusionRatio,
          device: p.device,
          protect: p.protect,
          filterRadius: p.filterRadius,
          rvcVersion: p.rvcVersion,
          referenceAudio: framework === 'seed-vc' ? p.referenceAudio : '',
        }),
      }
    })
    const work = await worksStore.create({
      title,
      mode: 'multi',
      workflow: currentWorkflow,
      source_path: song.value.path,
      models: blendModels,
      segments: outSegments,
      params: blendModels[0]?.params,
    })
    currentWork.value = work
    editorOpenedFor.value = null
    startPolling(work.id)
    return
  }

  if (selectedFramework.value === 'seed-vc' && !seedVcReferenceAudio.value) {
    ElMessage.warning('请先选择 SeedVC 参考音频')
    return
  }
  const work = await worksStore.create({
    title,
    model_id: selectedModel.value,
    workflow: currentWorkflow,
    source_path: song.value.path,
    params: currentParams(),
  })
  currentWork.value = work
  editorOpenedFor.value = null
  startPolling(work.id)
}

async function batchGenerate() {
  if (mode.value !== 'single' || !selectedModel.value) return
  if (selectedFramework.value === 'seed-vc' && !seedVcReferenceAudio.value) {
    ElMessage.warning('请先选择 SeedVC 参考音频')
    return
  }
  const paths = await api.pickAudioFiles()
  if (!paths.length) return
  const created = await api.createBatchWork({
    source_paths: paths,
    model_id: selectedModel.value,
    workflow: normalizeWorkflowForMode(workflow.value, 'single'),
    params: currentParams(),
  })
  queueStatus.value = await api.getInferenceQueue()
  ElMessage.success(`已加入推理队列：${created.length} 个任务`)
  if (created[0]) {
    currentWork.value = created[0]
    editorOpenedFor.value = null
    startPolling(created[0].id)
  }
}

const barStyle = (n: number) => ({
  height: 18 + Math.abs(Math.sin(n * 0.6)) * 74 + '%',
  animationDelay: n * 0.03 + 's',
})

watch(defaultId, (id) => {
  if (id && !selectedModel.value) selectedModel.value = id
})

// 选中歌曲后默认带出歌名作为歌词搜索词；切歌时重置时长
watch(song, (s) => {
  if (s && !songQuery.value.trim()) songQuery.value = s.name.replace(/\.[^.]+$/, '')
  audioDuration.value = 0
})

// 整体偏移按增量平移所有片段，保留已做的拆分 / 合并 / 边界编辑
watch(offset, (nv, ov) => {
  const d = nv - ov
  if (!d || !segments.value.length) return
  for (const s of segments.value) {
    s.start = Math.max(0, s.start + d)
    s.end = Math.max(s.start + MIN_SEG, s.end + d)
  }
})

let trackRO: ResizeObserver | null = null
let roRaf = 0
watch(trackEl, (el) => {
  trackRO?.disconnect()
  if (roRaf) {
    cancelAnimationFrame(roRaf)
    roRaf = 0
  }
  if (el && 'ResizeObserver' in window) {
    // 用 rAF 合并量取，彻底规避 “ResizeObserver loop” 的同步自反馈
    trackRO = new ResizeObserver(() => {
      if (roRaf) return
      roRaf = requestAnimationFrame(() => {
        roRaf = 0
        measureTrack()
      })
    })
    trackRO.observe(el)
    measureTrack()
  }
})

onMounted(async () => {
  await modelsStore.load()
  if (systemStore.loaded) {
    normalizeDeviceSelections()
  } else {
    void systemStore.load().then(normalizeDeviceSelections).catch(() => undefined)
  }
  presets.value = await api.listInferencePresets()
  queueStatus.value = await api.getInferenceQueue()
  selectedModel.value = defaultId.value || models.value[0]?.id || ''
  // 默认勾选默认模型，便于直接进入多模型流程
  if (selectedModel.value && selectedMulti.value.length === 0) {
    togglePick(selectedModel.value)
  }
  await loadDownloaded()
  // 加载歌词曲库选项（与「资源获取」共用妖狐 API 来源）
  try {
    const [srcList, curSource] = await Promise.all([
      api.listMusicSources(),
      api.getMusicSource(),
    ])
    if (srcList.length) lyricSources.value = srcList
    if (srcList.some((s) => s.id === curSource)) lyricSrc.value = curSource
  } catch {
    /* ignore */
  }
  // 从「资源获取」页跳转而来时，预选传入的已下载素材
  const src = typeof route.query.source === 'string' ? route.query.source : ''
  if (src) {
    const name = typeof route.query.name === 'string' && route.query.name
      ? route.query.name
      : src.split(/[/\\]/).pop() || src
    song.value = { name, path: src, hint: '来自资源获取' }
    songQuery.value = name.replace(/\.[^.]+$/, '')
  }
})

watch(
  [selectedFramework, () => systemStore.inferenceDevices],
  normalizeDeviceSelections,
  { deep: true },
)
onUnmounted(() => {
  stopPolling()
  trackRO?.disconnect()
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
})
</script>

<style scoped>
.page {
  max-width: 1320px;
  margin: 0 auto;
  padding: 28px 24px 60px;
}
.page-head { margin-bottom: 24px; }
.eyebrow {
  color: var(--xb-primary);
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 14px;
  margin: 0 0 8px;
}
.page-head h1 { font-size: 30px; font-weight: 800; margin: 0 0 8px; }
.page-sub { color: var(--xb-muted); font-size: 15px; margin: 0; }

.layout {
  display: grid;
  grid-template-columns: 1fr 0.85fr;
  gap: 22px;
  align-items: start;
}
/* min-width:0 必不可少：grid 子项默认 min-width:auto，会被超长歌词等内容按内容固有宽度撑开，
   从而把整个布局顶出可视区。归零后列宽严格遵循 1fr / 0.85fr，长内容交由内部省略号 / 换行处理。 */
.config { display: flex; flex-direction: column; gap: 18px; min-width: 0; }
.preview {
  display: flex;
  flex-direction: column;
  gap: 18px;
  position: sticky;
  top: 84px;
  min-width: 0;
}

.glass {
  position: relative;
  background: var(--xb-panel);
  border: 1px solid var(--xb-border);
  backdrop-filter: blur(16px);
}
.card {
  border-radius: 6px;
  padding: 22px;
  min-width: 0;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
}
.card-head h2 { font-size: 17px; font-weight: 700; margin: 0; }
.step-no {
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 13px;
  font-weight: 800;
  color: var(--xb-on-primary);
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2));
  padding: 3px 8px;
  border-radius: 6px;
}
.head-link {
  margin-left: auto;
  color: var(--xb-muted);
  font-size: 13px;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.head-link:hover { color: var(--xb-primary); }

/* 切角 */
.corner { position: absolute; width: 14px; height: 14px; border-color: var(--xb-primary); }
.corner.tl { top: -1px; left: -1px; border-top: 2px solid; border-left: 2px solid; }
.corner.tr { top: -1px; right: -1px; border-top: 2px solid; border-right: 2px solid; }
.corner.bl { bottom: -1px; left: -1px; border-bottom: 2px solid; border-left: 2px solid; }
.corner.br { bottom: -1px; right: -1px; border-bottom: 2px solid; border-right: 2px solid; }

/* 按钮 */
.cta-btn {
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important;
  border: none !important;
  color: var(--xb-on-primary) !important;
  font-weight: 700;
  box-shadow: 0 0 22px rgba(var(--xb-primary-rgb), 0.4);
}
.cta-btn.is-disabled { opacity: 0.45; box-shadow: none; }
.ghost-btn {
  background: rgba(var(--xb-primary-rgb), 0.06) !important;
  border: 1px solid var(--xb-border) !important;
  color: var(--xb-text) !important;
  font-weight: 600;
}
.generate-btn { width: 100%; padding: 24px; font-size: 16px; }
.infer-tools { display: grid; gap: 12px; }
.infer-tool-row { display: flex; align-items: center; gap: 10px; min-width: 0; }
.preset-select { flex: 1; min-width: 0; }
.queue-text { flex: 1; color: var(--xb-muted); font-size: 13px; }
.preset-delete {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  border: 1px solid rgba(var(--xb-accent-rgb), 0.28);
  background: rgba(var(--xb-accent-rgb), 0.08);
  color: var(--xb-accent);
  display: grid;
  place-items: center;
  cursor: pointer;
}
.preset-delete:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

/* 上传 */
.dropzone {
  border: 1.5px dashed rgba(var(--xb-primary-rgb), 0.3);
  border-radius: 8px;
  padding: 32px 20px;
  text-align: center;
  background: rgba(var(--xb-primary-rgb), 0.03);
  transition: all 0.25s;
  cursor: pointer;
}
.dropzone:hover { border-color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.07); }
.dz-icon { font-size: 42px; color: var(--xb-primary); margin-bottom: 10px; }
.dz-main { font-size: 15px; font-weight: 600; margin: 0 0 6px; }
.dz-sub { font-size: 12.5px; color: var(--xb-muted); margin: 0; }
.song-file {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px;
  border-radius: 8px;
  background: rgba(var(--xb-primary-rgb), 0.05);
  border: 1px solid var(--xb-border);
}
.song-cover {
  width: 46px; height: 46px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 22px;
  color: var(--xb-on-primary);
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-accent));
}
.song-info { flex: 1; }
.song-name { font-weight: 600; font-size: 14.5px; }
.song-meta { font-size: 12.5px; color: var(--xb-muted); margin-top: 3px; }
.icon-x {
  width: 32px; height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 16px;
}
.icon-x:hover { color: var(--xb-accent); background: rgba(var(--xb-accent-rgb), 0.1); }

/* 已下载素材 */
.lib { margin-top: 16px; border-top: 1px solid var(--xb-border); padding-top: 14px; }
.lib-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--xb-muted);
  margin-bottom: 10px;
}
.lib-list { display: flex; flex-direction: column; gap: 8px; max-height: 220px; overflow-y: auto; }
.lib-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.02);
  color: var(--xb-text);
  cursor: pointer;
  text-align: left;
  transition: all 0.2s;
}
.lib-item:hover { border-color: rgba(var(--xb-primary-rgb), 0.45); }
.lib-item.active { border-color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.08); }
.lib-item .el-icon { color: var(--xb-primary); flex-shrink: 0; }
.lib-name {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lib-size { font-size: 12px; color: var(--xb-muted); flex-shrink: 0; }

/* 模型选择 */
.model-list { display: flex; flex-direction: column; gap: 10px; max-height: 460px; overflow-y: auto; padding-right: 2px; }
.model-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 9px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.02);
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}
.model-item:hover { border-color: rgba(var(--xb-primary-rgb), 0.45); }
.model-item.active {
  border-color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.08);
}
.model-dot {
  width: 38px; height: 38px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 18px;
  color: var(--xb-on-primary);
  background: var(--mc);
}
.model-text { flex: 1; }
.model-name { font-weight: 600; font-size: 14px; color: var(--xb-text); }
.model-tag { font-size: 12px; color: var(--xb-muted); margin-top: 2px; }
.fw-chip { display: inline-block; margin-left: 8px; padding: 0 7px; border-radius: 6px; font-size: 11px; font-weight: 700; vertical-align: middle; color: var(--xb-accent); background: rgba(var(--xb-accent-rgb), 0.14); border: 1px solid rgba(var(--xb-accent-rgb), 0.35); }
.model-filter { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.filter-chip { padding: 5px 14px; border-radius: 20px; border: 1px solid var(--xb-border); background: rgba(var(--xb-fill-rgb), 0.04); color: var(--xb-muted); font-size: 12.5px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
.filter-chip:hover { color: var(--xb-text); border-color: var(--xb-primary); }
.filter-chip.on { background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)); color: var(--xb-on-primary); border-color: transparent; }
.fw-banner { font-size: 12.5px; color: var(--xb-muted); margin-bottom: 14px; padding: 8px 12px; border-radius: 8px; background: rgba(var(--xb-primary-rgb), 0.06); border: 1px solid var(--xb-border); }
.fw-banner b { color: var(--xb-primary); }
.model-check { color: var(--xb-primary); font-size: 18px; }

/* 模式切换 */
.mode-card { display: flex; gap: 10px; padding: 12px; }
.mode-item {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.02);
  color: var(--xb-text);
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}
.mode-item .el-icon { font-size: 20px; color: var(--xb-muted); }
.mode-item:hover { border-color: rgba(var(--xb-primary-rgb), 0.45); }
.mode-item.active { border-color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.09); }
.mode-item.active .el-icon { color: var(--xb-primary); }
.mode-name { font-weight: 700; font-size: 14px; }
.mode-desc { font-size: 12px; color: var(--xb-muted); margin-top: 2px; }

.workflow-card { padding-top: 18px; }
.workflow-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.workflow-item {
  min-height: 82px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.02);
  color: var(--xb-text);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.18s ease, background 0.18s ease, transform 0.18s ease;
}
.workflow-item:hover {
  border-color: rgba(var(--xb-primary-rgb), 0.5);
  background: rgba(var(--xb-primary-rgb), 0.05);
}
.workflow-item.active {
  border-color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
  box-shadow: inset 0 0 0 1px rgba(var(--xb-primary-rgb), 0.26);
}
.workflow-no {
  min-width: 30px;
  height: 26px;
  display: inline-grid;
  place-items: center;
  border-radius: 7px;
  background: rgba(var(--xb-fill-rgb), 0.08);
  color: var(--xb-muted);
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 12px;
  font-weight: 800;
}
.workflow-item.active .workflow-no {
  color: var(--xb-on-primary);
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2));
}
.workflow-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.workflow-title {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  font-size: 13.5px;
  font-weight: 800;
}
.workflow-title i {
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(var(--xb-success-rgb), 0.12);
  color: var(--xb-success);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}
.workflow-desc {
  color: var(--xb-muted);
  font-size: 12.5px;
  line-height: 1.45;
}

/* 多模型：每个模型 + 参数 */
.multi-model { display: flex; flex-direction: column; }
.model-badge {
  min-width: 20px; height: 20px;
  border-radius: 6px;
  color: #fff;
  font-size: 12px;
  font-weight: 800;
  display: grid;
  place-items: center;
  padding: 0 5px;
}
.mp-params {
  margin: 6px 0 4px 8px;
  padding: 12px 14px;
  border-left: 2px solid var(--xb-border);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mp-row { display: flex; flex-direction: column; gap: 6px; }
.mp-row label { font-size: 12.5px; color: var(--xb-muted); }
.mp-inline { display: flex; gap: 10px; }
.mp-mini { flex: 1; display: flex; align-items: center; gap: 6px; }
.mp-mini span { font-size: 12.5px; color: var(--xb-muted); }
.mp-mini select {
  flex: 1;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  outline: none;
  font-size: 13px;
}

/* 歌词获取 */
.lyric-fetch { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.lyric-input {
  flex: 1;
  min-width: 140px;
  padding: 9px 12px;
  border-radius: 9px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  outline: none;
  font-size: 13.5px;
}
.lyric-input:focus { border-color: var(--xb-primary); }
.lyric-n {
  width: 52px;
  padding: 9px 8px;
  border-radius: 9px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  outline: none;
  text-align: center;
}
.lyric-src { width: 120px; }
.lyric-src :deep(.el-select__wrapper) {
  background: rgba(var(--xb-fill-rgb), 0.04);
  border: 1px solid var(--xb-border);
  border-radius: 9px;
  box-shadow: none;
  min-height: 38px;
}
.lyric-src :deep(.el-select__selected-item) { color: var(--xb-text); }

/* 对齐校验条 */
.align-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 9px;
  margin-bottom: 12px;
  font-size: 13px;
  border: 1px solid var(--xb-border);
  flex-wrap: wrap;
}
.align-bar .el-icon { font-size: 16px; flex-shrink: 0; }
.align-bar.ok { border-color: rgba(var(--xb-success-rgb), 0.4); color: var(--xb-success); }
.align-bar.warn { border-color: rgba(var(--xb-warn-rgb), 0.4); color: var(--xb-warn); }
.align-bar.bad { border-color: rgba(var(--xb-accent-rgb), 0.4); color: var(--xb-accent); }
.align-text { flex: 1; min-width: 120px; }
.offset-ctrl { display: flex; align-items: center; gap: 8px; }
.offset-ctrl label { font-size: 12px; color: var(--xb-muted); white-space: nowrap; }
.offset-ctrl input[type='range'] { width: 120px; }

/* 批量指派 */
.assign-quick { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.assign-quick .muted { font-size: 12.5px; color: var(--xb-muted); }
.assign-tip { margin-left: auto; }
.quick-btn {
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid var(--mc);
  background: transparent;
  color: var(--mc);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.quick-btn:hover { background: color-mix(in srgb, var(--mc) 14%, transparent); }

/* 可视化时间轴（总览）*/
.timeline-wrap {
  margin-bottom: 14px;
  padding: 12px 14px 10px;
  border-radius: 12px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.03);
}
.timeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.tl-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  color: var(--xb-text);
}
.tl-tools { display: inline-flex; align-items: center; gap: 4px; }
.tl-zoom {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  cursor: pointer;
  font-size: 14px;
  transition: all 0.14s ease;
}
.tl-zoom:hover { border-color: var(--xb-primary); color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.1); }
.tl-zoom-val {
  min-width: 42px;
  text-align: center;
  font-size: 12px;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  color: var(--xb-muted);
}
.tl-enlarge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 10px;
  border-radius: 7px;
  border: 1px solid var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
  color: var(--xb-primary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  transition: all 0.14s ease;
}
.tl-enlarge:hover { background: rgba(var(--xb-primary-rgb), 0.18); }
.tl-zoom:disabled { opacity: 0.4; cursor: not-allowed; }
.tl-sep { width: 1px; height: 18px; background: var(--xb-border); margin: 0 2px; }
/* 内联缩略预览：固定高度 + overflow:hidden + 宽度恒为 100%，绝不撑破布局 */
.tl-mini {
  position: relative;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  height: 26px;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  background: repeating-linear-gradient(
    90deg,
    rgba(var(--xb-fill-rgb), 0.05),
    rgba(var(--xb-fill-rgb), 0.05) 1px,
    transparent 1px,
    transparent 25%
  );
  border: 1px solid var(--xb-border);
  transition: border-color 0.14s ease;
}
.tl-mini:hover { border-color: var(--xb-primary); }
.tl-mini-block {
  position: absolute;
  top: 3px;
  bottom: 3px;
  border-radius: 4px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.12);
}
.tl-mini-block.is-idle { background: rgba(var(--xb-fill-rgb), 0.1); box-shadow: none; }
.tl-mini-block.is-chorus { box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.4); }
/* 放大编辑弹窗 */
.tl-dialog-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.tl-scroll-lg { padding-bottom: 8px; }
.tl-track-lg { height: 88px; }
.tl-legend { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
.tl-leg {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--xb-muted);
}
/* 固定宽度视口：始终 = 弹窗主体宽度，作为像素↔时间换算的稳定基准 */
.tl-viewport {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
}
.tl-scroll {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 4px;
}
.tl-scroll::-webkit-scrollbar { height: 8px; }
.tl-scroll::-webkit-scrollbar-thumb { background: rgba(var(--xb-fill-rgb), 0.25); border-radius: 4px; }
.tl-inner { position: relative; min-width: 100%; }
.tl-leg-dot {
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  color: #fff;
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.36), 0 0 8px rgba(0, 0, 0, 0.18);
}
.tl-leg-dot.idle {
  width: 9px;
  height: 9px;
  background: var(--xb-border);
  box-shadow: none;
  border: 1px solid var(--xb-muted);
}
.tl-ruler {
  position: relative;
  height: 16px;
  margin: 0 2px;
}
.tl-tick {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  font-size: 11px;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  color: var(--xb-muted);
  white-space: nowrap;
}
.tl-tick:first-child { transform: none; }
.tl-tick:last-child { transform: translateX(-100%); }
.tl-track {
  position: relative;
  height: 40px;
  border-radius: 8px;
  background: repeating-linear-gradient(
    90deg,
    rgba(var(--xb-fill-rgb), 0.05),
    rgba(var(--xb-fill-rgb), 0.05) 1px,
    transparent 1px,
    transparent 25%
  );
  overflow: hidden;
}
.tl-block {
  position: absolute;
  top: 4px;
  bottom: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: 0 4px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  overflow: hidden;
  white-space: nowrap;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.12);
  transition: filter 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
}
.tl-block:hover {
  filter: brightness(1.12);
  transform: translateY(-1px);
  z-index: 2;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}
.tl-block.is-idle {
  background: rgba(var(--xb-fill-rgb), 0.08);
  border-color: var(--xb-border);
  color: var(--xb-muted);
}
.tl-block.is-chorus { box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.35); }
.tl-block-label {
  overflow: hidden;
  text-overflow: ellipsis;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
}
.tl-block-chorus {
  display: grid;
  place-items: center;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.28);
  font-size: 10px;
  font-weight: 800;
  flex-shrink: 0;
}
.tl-block.dragging { z-index: 5; filter: brightness(1.18); box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4); }
/* 边界拖动手柄 */
.tl-grip {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 8px;
  cursor: ew-resize;
  z-index: 3;
  touch-action: none;
}
.tl-grip.l { left: -1px; border-radius: 6px 0 0 6px; }
.tl-grip.r { right: -1px; border-radius: 0 6px 6px 0; }
.tl-grip::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 2px;
  height: 56%;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.7);
  opacity: 0;
  transition: opacity 0.14s ease;
}
.tl-block:hover .tl-grip::after { opacity: 0.85; }
.tl-block.is-idle .tl-grip::after { background: var(--xb-muted); }
/* 弹窗内的片段操作 */
.pick-acts {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--xb-border);
}
.pick-act {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: 5px 4px;
  border-radius: 7px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  font-size: 11.5px;
  cursor: pointer;
  transition: all 0.14s ease;
}
.pick-act:hover { border-color: var(--xb-primary); color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.1); }
.pick-act.danger:hover { border-color: var(--xb-accent); color: var(--xb-accent); background: rgba(var(--xb-accent-rgb), 0.1); }
.tl-hint { margin: 8px 0 0; font-size: 11.5px; }

/* 歌词逐句 */
.lyric-list { max-height: 360px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
.lyric-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 8px;
  border-radius: 8px;
}
.lyric-row:hover { background: rgba(var(--xb-primary-rgb), 0.05); }
.lyric-row.is-idle { opacity: 0.72; }
.lyric-row.is-chorus {
  background: linear-gradient(90deg, rgba(var(--xb-primary-rgb), 0.07), transparent);
  box-shadow: inset 2px 0 0 var(--xb-primary);
}

/* 逐句指派：彩色模型胶囊 + 弹出选择 */
.ly-assign {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
  max-width: 60%;
}
.chorus-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 9px;
  border-radius: 999px;
  color: #fff;
  background: linear-gradient(90deg, var(--xb-primary), #b06bff);
  box-shadow: 0 2px 8px rgba(var(--xb-primary-rgb), 0.35);
  white-space: nowrap;
}
.chorus-tag .el-icon { font-size: 12px; }
.model-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 6px 3px 9px;
  border-radius: 999px;
  border: 1px solid;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.model-chip:hover { transform: translateY(-1px); }
.chip-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 6px currentColor;
}
.chip-name { max-width: 96px; overflow: hidden; text-overflow: ellipsis; }
.chip-x {
  display: grid;
  place-items: center;
  width: 15px;
  height: 15px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: 11px;
  opacity: 0.7;
}
.chip-x:hover { opacity: 1; background: color-mix(in srgb, currentColor 20%, transparent); }
.idle-chip {
  font-size: 12px;
  color: var(--xb-muted);
  padding: 2px 4px;
  font-style: italic;
}
.add-chip {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 50%;
  border: 1px dashed var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-muted);
  cursor: pointer;
  font-size: 14px;
  transition: all 0.16s ease;
}
.add-chip:hover {
  border-color: var(--xb-primary);
  border-style: solid;
  color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
  transform: rotate(90deg);
}
/* 合唱多模型折叠：+N / 收起 */
.more-chip {
  flex-shrink: 0;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.06);
  color: var(--xb-muted);
  font-size: 11.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.14s ease;
}
.more-chip:hover { border-color: var(--xb-primary); color: var(--xb-primary); }
/* 片段操作（拆分 / 合并 / 删除）*/
.seg-ops { display: inline-flex; gap: 3px; flex-shrink: 0; margin-left: 2px; }
.seg-op {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-muted);
  cursor: pointer;
  font-size: 13px;
  transition: all 0.14s ease;
}
.seg-op:hover { border-color: var(--xb-primary); color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.1); }
.seg-op.danger:hover { border-color: var(--xb-accent); color: var(--xb-accent); background: rgba(var(--xb-accent-rgb), 0.1); }
.ly-time {
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 11.5px;
  line-height: 1.35;
  text-align: center;
  color: var(--xb-muted);
  flex-shrink: 0;
  width: 48px;
}
.ly-text {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ly-model {
  width: 116px;
  flex-shrink: 0;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  outline: none;
  font-size: 12.5px;
}
.lyric-empty {
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--xb-muted);
}

/* 字段 */
.field { margin-bottom: 18px; }
.field:last-child { margin-bottom: 0; }
.field-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.field label, .field-block-label {
  font-size: 14px;
  color: var(--xb-text);
  font-weight: 500;
}
.field-block-label { display: block; margin-bottom: 10px; }
.field-val {
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 13px;
  font-weight: 700;
  color: var(--xb-primary);
}
.field-hint { font-size: 12px; color: var(--xb-muted); margin-top: 8px; }
.field-tip { font-size: 13px; color: var(--xb-muted); margin: -6px 0 12px; }
.path-picker {
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  padding: 0 12px;
  cursor: pointer;
}
.path-picker:hover {
  border-color: rgba(var(--xb-primary-rgb), 0.55);
  background: rgba(var(--xb-primary-rgb), 0.08);
}
.mp-ref {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--xb-muted);
}
.mini-picker {
  min-width: 0;
  height: 28px;
  border: 1px solid var(--xb-border);
  border-radius: 7px;
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  padding: 0 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.mini-picker:hover { border-color: rgba(var(--xb-primary-rgb), 0.55); }
input[type='range'] {
  width: 100%;
  accent-color: var(--xb-primary);
  cursor: pointer;
}
.ratio-range { accent-color: var(--xb-accent); }
.ratio-main { color: var(--xb-primary); font-style: normal; }
.ratio-diff { color: var(--xb-accent); font-style: normal; }

/* 分段控件 */
.seg {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.seg-item {
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.02);
  color: var(--xb-muted);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s;
}
.seg-item:hover { color: var(--xb-text); border-color: rgba(var(--xb-primary-rgb), 0.45); }
.seg-item.active {
  color: var(--xb-primary);
  border-color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
}

/* 预览 */
.result-card { box-shadow: 0 0 40px rgba(var(--xb-primary-rgb), 0.08); }
.result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}
.result-head h2 { font-size: 17px; font-weight: 700; margin: 0; }
.result-state {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 999px;
}
.result-state.idle { color: var(--xb-muted); background: rgba(var(--xb-fill-rgb), 0.06); }
.result-state.running { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.12); }
.result-state.done { color: var(--xb-success); background: rgba(var(--xb-success-rgb), 0.12); }

.player-cover {
  width: 70px; height: 70px;
  margin: 0 auto 18px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  font-size: 32px;
  color: var(--xb-on-primary);
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-accent));
  box-shadow: 0 0 26px rgba(var(--xb-primary-rgb), 0.4);
}
.waveform {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 2px;
  height: 64px;
  margin-bottom: 20px;
}
.waveform span {
  flex: 1;
  background: linear-gradient(180deg, var(--xb-primary), var(--xb-primary-2));
  border-radius: 2px;
  opacity: 0.4;
}
.waveform.playing span {
  opacity: 1;
  animation: bar 1s ease-in-out infinite alternate;
}
@keyframes bar { from { transform: scaleY(0.35); } to { transform: scaleY(1); } }
.player-ctrl {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
}
.play-main {
  width: 48px; height: 48px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2));
  color: var(--xb-on-primary);
  font-size: 20px;
  display: grid;
  place-items: center;
  box-shadow: 0 0 20px rgba(var(--xb-primary-rgb), 0.5);
}
.play-main:disabled { opacity: 0.4; box-shadow: none; cursor: not-allowed; }

/* 流程 */
.pipeline { display: flex; flex-direction: column; gap: 6px; }
.pl-step {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px;
  border-radius: 8px;
  transition: background 0.25s;
}
.pl-step.active { background: rgba(var(--xb-primary-rgb), 0.06); }
.pl-icon {
  width: 32px; height: 32px;
  flex-shrink: 0;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 14px;
  font-weight: 700;
  border: 1px solid var(--xb-border);
  color: var(--xb-muted);
  background: rgba(var(--xb-fill-rgb), 0.03);
}
.pl-step.active .pl-icon { color: var(--xb-primary); border-color: var(--xb-primary); }
.pl-step.done .pl-icon {
  color: var(--xb-on-primary);
  background: var(--xb-success);
  border-color: var(--xb-success);
}
.pl-label { font-size: 14px; font-weight: 600; }
.pl-desc { font-size: 12.5px; color: var(--xb-muted); margin-top: 2px; }
.pl-step.wait .pl-label { color: var(--xb-muted); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.error-card { border-color: rgba(var(--xb-accent-rgb), 0.35); }
.error-msg {
  font-size: 13px;
  line-height: 1.6;
  color: var(--xb-accent);
  background: rgba(var(--xb-accent-rgb), 0.08);
  border: 1px solid rgba(var(--xb-accent-rgb), 0.25);
  border-radius: 10px;
  padding: 10px 12px;
  word-break: break-word;
  max-height: 160px;
  overflow: auto;
}
.error-path {
  margin-top: 10px;
  font-size: 12px;
  color: var(--xb-muted);
  word-break: break-all;
}
.error-actions { display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }

@media (max-width: 980px) {
  .layout { grid-template-columns: 1fr; }
  .preview { position: static; }
  .workflow-grid { grid-template-columns: 1fr; }
}
</style>

<!-- 逐句指派弹出层会被传送到 body，需用非 scoped 样式命中 -->
<style>
.assign-popover.el-popover.el-popper {
  padding: 10px;
  border-radius: 14px;
  border: 1px solid var(--xb-border);
  background: var(--xb-bg-2);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.32);
}
.assign-popover .pick-pop { display: flex; flex-direction: column; gap: 4px; max-height: 60vh; overflow-y: auto; }
.assign-popover .pick-hint {
  margin: 0 4px 6px;
  font-size: 11.5px;
  color: var(--xb-muted);
}
.assign-popover .pick-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--xb-text);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: background 0.14s ease, border-color 0.14s ease;
}
.assign-popover .pick-item:hover {
  background: color-mix(in srgb, var(--mc) 12%, transparent);
}
.assign-popover .pick-item.on {
  border-color: var(--mc);
  background: color-mix(in srgb, var(--mc) 16%, transparent);
  color: var(--mc);
  font-weight: 700;
}
.assign-popover .pick-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 6px var(--mc);
}
.assign-popover .pick-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.assign-popover .pick-check { color: var(--mc); font-size: 15px; flex-shrink: 0; }

/* 时间轴放大编辑弹窗（el-dialog 传送到 body，需非 scoped 命中外框）*/
.tl-dialog.el-dialog {
  background: var(--xb-bg-2);
  border: 1px solid var(--xb-border);
  border-radius: 16px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.4);
}
/* 关键：弹窗主体禁止被超宽内容撑开，缩放后的超宽轨道只在 .tl-scroll 内部横向滚动 */
.tl-dialog .el-dialog__body { overflow: hidden; min-width: 0; }
.tl-dialog .el-dialog__title { color: var(--xb-text); font-weight: 700; }
.tl-dialog .el-dialog__headerbtn .el-dialog__close { color: var(--xb-muted); }
.tl-dialog .el-dialog__headerbtn:hover .el-dialog__close { color: var(--xb-primary); }
</style>
