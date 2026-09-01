<template>
  <Teleport to="body">
    <Transition name="interactive-guide">
      <div
        v-if="visible"
        class="interactive-guide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="interactive-guide-title"
        tabindex="-1"
        @keydown.esc="skip"
      >
        <div v-if="hasTarget" class="guide-focus" :style="focusStyle" aria-hidden="true"></div>

        <aside class="guide-callout" :class="{ 'is-centered': !hasTarget }" :style="calloutStyle">
          <header class="callout-header">
            <div class="callout-section"><el-icon><Guide /></el-icon>{{ activeStep.section }}</div>
            <div class="callout-count">{{ currentStep + 1 }} / {{ steps.length }}</div>
            <button type="button" class="callout-close" title="跳过引导" aria-label="跳过引导" @click="skip">
              <el-icon><Close /></el-icon>
            </button>
          </header>

          <div class="callout-heading">
            <div class="callout-icon"><el-icon><component :is="activeStep.icon" /></el-icon></div>
            <div class="callout-heading-copy">
              <p class="callout-target">正在查看 · {{ activeStep.targetLabel }}</p>
              <h1 id="interactive-guide-title">{{ activeStep.title }}</h1>
            </div>
          </div>
          <p class="callout-description">{{ activeStep.description }}</p>

          <div class="callout-details">
            <div v-for="detail in activeStep.details" :key="detail.label" class="callout-detail">
              <strong>{{ detail.label }}</strong>
              <span>{{ detail.value }}</span>
            </div>
          </div>
          <p v-if="locating" class="callout-locating"><i></i>正在打开页面并定位组件…</p>
          <p v-else-if="!hasTarget" class="callout-locating is-warning"><i></i>当前页面暂未找到该组件，可先阅读说明继续</p>

          <footer class="callout-footer">
            <button type="button" class="guide-skip" @click="skip">跳过引导</button>
            <div class="guide-actions">
              <button v-if="currentStep > 0" type="button" class="guide-back" :disabled="locating" @click="goToStep(currentStep - 1)">上一步</button>
              <button type="button" class="guide-next" :disabled="locating" @click="next">
                {{ currentStep === steps.length - 1 ? '完成并开始使用' : '下一步' }}
                <el-icon><ArrowRight /></el-icon>
              </button>
            </div>
          </footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Close, FolderOpened, Guide, MagicStick, Microphone, Operation, Setting, UploadFilled } from '@element-plus/icons-vue'

defineOptions({ name: 'FirstUseGuide' })

type GuidePlacement = 'top' | 'right' | 'bottom' | 'left'
interface GuideDetail { label: string; value: string }
interface GuideStep {
  section: string
  targetLabel: string
  title: string
  description: string
  details: GuideDetail[]
  route: string
  selector: string
  placement: GuidePlacement
  icon: typeof Microphone
  prepare?: 'multi' | 'multi-timeline' | 'enhancement' | 'open-player'
}

const STORAGE_KEY = 'xb-first-use-guide-v3'
const router = useRouter()
const route = useRoute()
const visible = ref(false)
const locating = ref(false)
const currentStep = ref(0)
const hasTarget = ref(false)
const targetRect = ref<DOMRect | null>(null)
let focusRaf = 0

const steps: GuideStep[] = [
  { section: '首页 · 01', targetLabel: 'AI 翻唱快捷入口', title: '从这里开始一次完整翻唱', description: 'AI 翻唱工作台负责导入歌曲、选择音色、设置推理并生成作品。点击快捷入口进入空白工作台；从首页拖入音频则会把该文件一并带入。', details: [{ label: '点击卡片', value: '进入空白工作台' }, { label: '拖拽音频', value: '自动跳转并预填这首歌' }], route: '/', selector: '[data-guide="home-ai-cover"]', placement: 'right', icon: Microphone },
  { section: '首页 · 02', targetLabel: '首页音频拖拽区', title: '拖入音频会自动带入翻唱', description: '把歌曲拖到首页这个区域，软件会校验格式和大小，然后跳转到 AI 翻唱并显示刚才的文件。直接点击区域仍然只是打开空白工作台。', details: [{ label: '格式', value: 'MP3、WAV、FLAC、M4A、OGG、AAC' }, { label: '限制', value: '单个文件不超过 50MB' }], route: '/', selector: '[data-guide="home-dropzone"]', placement: 'bottom', icon: UploadFilled },
  { section: '翻唱工作台 · 03', targetLabel: '单模型 / 多模型模式', title: '先决定整首歌还是逐句分配', description: '单模型适合整首歌保持一个音色，步骤少、最容易成功。多模型会显示歌词时间轴，可以按句选择不同音色，也可以多选形成合唱。', details: [{ label: '单模型', value: '整首统一音色，适合快速生成' }, { label: '多模型', value: '逐句分配模型，适合角色切换与和声' }, { label: '切换', value: '已填写的歌曲与常用参数会保留' }], route: '/create', selector: '[data-guide="cover-mode"]', placement: 'right', icon: Operation },
  { section: '翻唱工作台 · 04', targetLabel: '歌曲导入区', title: '点击选择或拖拽歌曲', description: '工作台的导入区与首页行为一致。你可以点击选择本地文件，也可以直接拖入；已下载的曲库素材会列在下方，一键即可使用。', details: [{ label: '本地文件', value: '桌面端选择路径，网页端读取文件' }, { label: '已下载', value: '从资源获取页下载的歌曲可直接复用' }, { label: '试听', value: '导入后先确认歌曲和时长再推理' }], route: '/create', selector: '[data-guide="cover-upload"]', placement: 'right', icon: UploadFilled },
  { section: '翻唱工作台 · 05', targetLabel: '高级功能开关', title: '先选择需要的工作流', description: '这里集中放置前期处理和歌声增强等工作流。普通用户可以保持默认关闭；需要更细的声音处理时再进入对应模块。', details: [{ label: '前期处理', value: '先分离人声、去混响，再送进模型' }, { label: '歌声增强', value: '生成前做自然修音与动态处理' }, { label: '普通流程', value: '不打开高级功能也可以直接生成' }], route: '/create', selector: '[data-guide="cover-workflow"]', placement: 'right', icon: Setting },
  { section: '前期人声处理 · 06', targetLabel: '前期人声处理', title: '在推理前清理输入人声', description: '打开前期处理后，软件会先把歌曲拆成人声和伴奏。干净的人声能减少伴奏串音，让后面的音高检测和音色转换更稳定。', details: [{ label: '关闭', value: '直接使用原始音频，速度最快' }, { label: '开启', value: '先分离再进入翻唱流水线' }, { label: '注意', value: '处理本身会增加耗时，先试听结果再决定' }], route: '/create', selector: '[data-guide="preprocess"]', placement: 'right', icon: MagicStick },
  { section: '前期人声处理 · 07', targetLabel: '分离引擎选择', title: '按环境选择 UVR 或 PyMSS', description: 'UVR 适合已有本地环境的快速分离；PyMSS 可以使用已下载的专用分离或去混响模型。先选引擎，再选具体模型，状态提示会告诉你是否可用。', details: [{ label: 'UVR', value: 'MDX-Net、Demucs v4、VR Arch 等通用方案' }, { label: 'PyMSS', value: '可下载人声分离与去混响模型' }, { label: '去混响', value: '可额外开启，改善房间声和尾音' }], route: '/create', selector: '[data-guide="preprocess-engine"], [data-guide="preprocess"]', placement: 'bottom', icon: FolderOpened },
  { section: '翻唱工作台 · 08', targetLabel: '模型选择区', title: '选择适合的音色模型', description: '模型卡片会显示框架、采样率和类型。先按框架筛选，再点击模型。模型的音域配置会参与高音保护，不同模型不会共用一个固定阈值。', details: [{ label: '筛选', value: '按 So-VITS-SVC、RVC、SeedVC、DDSP-SVC 等框架过滤' }, { label: '单模型', value: '点击一张卡片作为整首歌曲的音色' }, { label: '多模型', value: '勾选多张卡片后按歌词分配' }], route: '/create', selector: '[data-guide="model-select"]', placement: 'right', icon: FolderOpened },
  { section: '单模型推理 · 09', targetLabel: '推理参数面板', title: '默认模式先调常用参数', description: '关闭全参数时，变调、F0 算法、设备、检索率、响度混合、保护、滤波半径等常用参数仍然可调。软件默认值保持原有推理效果，隐藏的高级值不会污染本次运行。', details: [{ label: '变调', value: '按男女声或歌曲音域做半音级调整' }, { label: 'F0 / 设备', value: '选择音高算法和 CPU / GPU 推理设备' }, { label: 'RVC 参数', value: '检索率、响度混合、保护、滤波半径、版本' }], route: '/create', selector: '[data-guide="inference-params"]', placement: 'right', icon: Setting },
  { section: '单模型推理 · 10', targetLabel: '主模型 / 扩散模型比例', title: '理解主模型和浅扩散的分工', description: '这个比例决定主模型路径与浅扩散路径对成品的贡献。它不是“越大越好”，而是速度、音色稳定性、细节、显存之间的取舍。', details: [{ label: '主模型高', value: '速度快、音色轮廓稳定、显存压力较小' }, { label: '浅扩散高', value: '细节与自然度通常更丰富，但更慢且更吃显存' }, { label: '调法', value: '先用默认值，出现毛刺或细节不足时小步调整' }], route: '/create', selector: '[data-guide="ratio-control"]', placement: 'bottom', icon: MagicStick },
  { section: '单模型推理 · 11', targetLabel: '全参数手动调整开关', title: '打开后才让高级值参与推理', description: '全参数默认关闭。关闭时目标说话人 / 音色 ID、F0 过滤阈值和手动高音起点不会发送给推理引擎；普通参数仍然有效。应用预设也不会偷偷打开开关。', details: [{ label: '默认关闭', value: '保证新手直接生成时维持原有模型效果' }, { label: '开启后', value: '显示并发送模型支持的全部高级参数' }, { label: '预设隔离', value: '预设只载入数值，开关状态由你决定' }], route: '/create', selector: '[data-guide="manual-switch"]', placement: 'bottom', icon: Setting },
  { section: '单模型推理 · 12', targetLabel: '高音保护与 F0 阈值', title: '按模型音域保护高音', description: '高音保护先读取当前模型的音域 profile，不再用统一固定阈值。只有打开高音保护后，且全参数开关已开启，才显示可手动编辑的保护起点。', details: [{ label: '自动', value: '0 表示使用当前模型的音域配置' }, { label: '手动起点', value: '仅全参数开启 + 高音保护开启时出现' }, { label: 'F0 过滤', value: '仅全参数开启时出现，数值越高越严格' }], route: '/create', selector: '[data-guide="high-pitch-toggle"]', placement: 'bottom', icon: Microphone },
  { section: '多模型推理 · 13', targetLabel: '多模型模式', title: '切换到逐句混合推理', description: '多模型模式会为每个已勾选模型保存独立参数。为便于完整展示，导览会临时选中示例模型并打开全参数；退出这一段后会恢复你原来的模式和开关。', details: [{ label: '适合', value: '主唱 / 和声 / 对话角色切换' }, { label: '独立保存', value: '每个模型的变调、比例和保护互不覆盖' }, { label: '合唱', value: '同一句勾选多个模型即可叠唱' }], route: '/create', selector: '[data-guide="multi-mode"]', placement: 'bottom', icon: Operation, prepare: 'multi' },
  { section: '多模型推理 · 14', targetLabel: '逐模型参数', title: '为每个模型单独调音', description: '勾选模型后会展开它自己的参数区。普通参数一直可调；高级字段只在全参数开启时出现，并且只作用于当前模型。', details: [{ label: '音色比例', value: '每个模型可以使用不同的主模型 / 扩散比例' }, { label: '框架专属', value: 'DDSP 的 formant、SeedVC 的参考音频按框架显示' }, { label: '目标音色', value: 'So-VITS / DDSP 可填目标说话人或音色 ID' }], route: '/create', selector: '[data-guide="multi-model-params"], [data-guide="model-select"]', placement: 'right', icon: Setting, prepare: 'multi' },
  { section: '多模型推理 · 15', targetLabel: '歌词与分句', title: '获取歌词并校准时间轴', description: '可以按歌名从曲库获取歌词，也可以导入带时间轴的 LRC / TXT。整体偏移用于把歌词和音频对齐，之后每段都能继续精修。', details: [{ label: '获取', value: '输入歌名、序号和曲库后在线获取' }, { label: '导入', value: '选择本地 .lrc 或纯文本歌词' }, { label: '偏移', value: '用滑杆整体前后移动，单位为秒' }], route: '/create', selector: '[data-guide="multi-lyrics"]', placement: 'right', icon: UploadFilled, prepare: 'multi' },
  { section: '多模型推理 · 16', targetLabel: '多模型时间轴', title: '先弹出时间轴，再学习逐句编排', description: '时间轴只有在多模型模式完成歌词分句后才会出现。导览会临时准备一组演示分句并自动打开“放大编辑”弹窗，让你看到真实的时间轴组件；不会提交或保存演示内容。', details: [{ label: '批量指派', value: '一键把所有句子交给某个模型' }, { label: '局部编辑', value: '拖动边界、拆分、合并、撤销 / 重做' }, { label: '间奏', value: '清空模型后该段不会生成演唱' }], route: '/create', selector: '[data-guide="multi-timeline-dialog"]', placement: 'top', icon: MagicStick, prepare: 'multi-timeline' },
  { section: '翻唱工作台 · 17', targetLabel: 'AI Vocal Enhancement 开关', title: '生成前开启 AI 歌声增强', description: '介绍这一段时，导览会临时打开 AI Vocal Enhancement，让你直接看到增强层级和控制项。离开本段或结束引导后，开关和原来的选择会自动恢复。', details: [{ label: 'Clean Voice', value: '轻量降噪、自然修音、并行轻母带' }, { label: 'Natural Voice', value: '真实细节保护、宽带校正和自然度母带' }, { label: '恢复', value: '演示结束自动恢复你进入引导前的状态' }], route: '/create', selector: '[data-guide="enhancement-toggle"]', placement: 'right', icon: MagicStick, prepare: 'enhancement' },
  { section: '翻唱工作台 · 18', targetLabel: 'AI 增强层级与参数', title: '分别控制增强强度', description: '基础层适合快速清理，高级层会显示更多细节控制。每个参数都可以独立调整，最终效果要以人声是否自然、是否出现泵动和齿音为准。', details: [{ label: '自然修音 / 对齐', value: '改善音高稳定性和原曲节奏贴合度' }, { label: '角色共振峰', value: '保留或强化目标音色的共鸣特征' }, { label: 'EQ / 压缩 / 激励', value: '平衡频段、动态和清晰度' }, { label: 'Stereo / 响度', value: '调整空间宽度和整体动态包络' }], route: '/create', selector: '[data-guide="enhancement-levels"], [data-guide="enhancement-controls"]', placement: 'left', icon: Setting, prepare: 'enhancement' },
  { section: '翻唱工作台 · 18', targetLabel: '预设与推理队列', title: '保存配置并管理批量推理', description: '推理生态区域可以保存、应用、删除参数预设，也能查看排队数量。批量推理会把当前模型配置加入队列，适合一次尝试多个版本。', details: [{ label: '预设', value: '保存常用普通参数和高级参数数值' }, { label: '隔离', value: '预设不会改变全参数开关' }, { label: '队列', value: '查看等待任务，避免重复点击生成' }], route: '/create', selector: '[data-guide="cover-ecosystem"]', placement: 'right', icon: FolderOpened },
  { section: '翻唱工作台 · 19', targetLabel: '开始生成与输出预览', title: '提交任务并试听成品', description: '确认歌曲、模型和参数后开始生成。右侧会显示处理流水线；完成后可以播放、拖动进度条和导出成品，后续也可在作品库继续管理。', details: [{ label: '生成', value: '任务进入队列并显示分离、推理、增强等阶段' }, { label: '试听', value: '播放按钮与可拖动进度条支持定位副歌和高音段' }, { label: '导出', value: '选择可用格式保存当前成品' }], route: '/create', selector: '[data-guide="cover-generate"]', placement: 'top', icon: MagicStick },
  { section: '实时翻唱 · 20', targetLabel: '播放源', title: '选择系统音频或歌曲文件', description: '实时翻唱可以监听回环 / 虚拟线路中的系统声音，也可以让软件播放一首歌曲文件并实时转换。系统模式要先选择输入和输出设备。', details: [{ label: '系统音频', value: '适合直播、播放器和麦克风回环' }, { label: '歌曲文件', value: '选择本地或已下载素材实时播放' }, { label: '设备', value: '刷新并确认输入线路、耳机或扬声器' }], route: '/create/realtime', selector: '[data-guide="realtime-source"]', placement: 'right', icon: Microphone },
  { section: '实时翻唱 · 21', targetLabel: '实时推理参数', title: '实时模式同样支持普通与全参数', description: '实时工作台的每个模型都有独立参数。普通字段适合低延迟使用；打开全参数后才能调整 F0 过滤阈值、目标音色和高音保护起点。', details: [{ label: '低延迟', value: '先降低质量参数和块大小，确保声音连续' }, { label: '多模型', value: '实时可在已选模型间切换或叠加' }, { label: '保护', value: '高音起点仍按模型 profile 自动推断' }], route: '/create/realtime', selector: '[data-guide="realtime-params"]', placement: 'right', icon: Setting },
  { section: '实时翻唱 · 22', targetLabel: '实时监控与播放', title: '开始、暂停并观察实时状态', description: '监控区会显示会话状态、延迟和播放控制。设备切换或参数修改前先停止会话，避免输入输出线路被占用。', details: [{ label: '开始', value: '确认设备和模型后启动实时会话' }, { label: '播放', value: '文件模式可以暂停、继续和停止' }, { label: '故障', value: '状态提示会指出设备或引擎问题' }], route: '/create/realtime', selector: '[data-guide="realtime-monitor"]', placement: 'top', icon: Microphone },
  { section: '资源获取 · 23', targetLabel: '在线曲库搜索', title: '搜索、试听并下载歌曲素材', description: '资源获取页可以选择曲库、搜索歌名或歌手、试听结果并下载。配置 API Key 后，下载的素材会出现在翻唱工作台的已下载列表。', details: [{ label: '曲库', value: '按已配置的网易云、QQ、酷我等来源切换' }, { label: '试听', value: '先确认版本，再点击下载或去翻唱' }, { label: '设置', value: 'API Key 和会员 Cookie 只保存在本地' }], route: '/music', selector: '[data-guide="music-search"]', placement: 'bottom', icon: FolderOpened },
  { section: '资源获取 · 24', targetLabel: '搜索结果与已下载素材', title: '把歌曲直接送入翻唱', description: '搜索结果可以单独下载，也可以下载完成后直接跳转翻唱。已下载列表支持试听、去翻唱和删除，翻唱页会复用本地路径。', details: [{ label: '去翻唱', value: '自动带入选中的歌曲和曲库信息' }, { label: '本地复用', value: '无需重复下载即可再次使用' }, { label: '清理', value: '删除只移除本地素材，不影响已生成作品' }], route: '/music', selector: '[data-guide="music-results"], [data-guide="music-downloads"]', placement: 'right', icon: UploadFilled },
  { section: 'AI 歌声增强 · 32', targetLabel: '增强目标和原始歌曲', title: '选择要增强的成品与参考原曲', description: '增强工作台可以选择作品库里的翻唱，也可以导入已有音频。再提供原始歌曲作为音高、节奏、音色和动态校正参考。', details: [{ label: '增强目标', value: '作品库成品或本地导入音频' }, { label: '原始歌曲', value: '本地选择，或从在线曲库搜索下载' }, { label: '要求', value: '两者越对应，校正结果越可靠' }], route: '/enhancement', selector: '[data-guide="enhancement-target"], [data-guide="enhancement-original"]', placement: 'right', icon: MagicStick },
  { section: 'AI 歌声增强 · 33', targetLabel: '增强参数与任务', title: '选择层级、调整强度并提交', description: '基础层适合快速清理，高级层会显示更多 AI EQ、压缩器、激励、立体声和响度包络。提交后在右侧监控任务进度，完成后可播放成品。', details: [{ label: '层级', value: 'Clean Voice 或 Natural Voice' }, { label: '强度', value: '每个控制项都可以独立微调' }, { label: '结果', value: '任务完成后打开播放器或我的作品' }], route: '/enhancement', selector: '[data-guide="enhancement-controls"], [data-guide="enhancement-run"]', placement: 'left', icon: MagicStick },
  { section: '我的作品 · 34', targetLabel: '作品筛选与列表', title: '管理所有生成任务和成品', description: '作品库按全部、已完成、生成中、排队和失败筛选，也能搜索作品名或模型名。每行都有试听、下载、增强、重试、日志和删除操作。', details: [{ label: '状态', value: '生成中和排队中的任务会自动刷新进度' }, { label: '失败', value: '打开日志查看原因并重试' }, { label: '作品', value: '重命名、下载、试听或删除成品' }], route: '/works', selector: '[data-guide="works-filter"], [data-guide="works-list"]', placement: 'bottom', icon: FolderOpened },
  { section: '作品播放器 · 35', targetLabel: '播放器与歌词', title: '试听作品并同步歌词', description: '播放器可以导入图片或 MV 作为画面，也可以搜索或导入 LRC 歌词。点击歌词行会跳到对应时间，适合检查咬字和高音段。', details: [{ label: '画面', value: '导入、更换或移除图片 / 视频 MV' }, { label: '歌词', value: '曲库获取或导入 LRC 时间轴' }, { label: '定位', value: '点击歌词行跳转到该句' }], route: '/player', selector: '[data-guide="player-visual"], [data-guide="player-lyrics"], [data-guide="player-empty"]', placement: 'right', icon: Microphone, prepare: 'open-player' },
  { section: '作品播放器 · 36', targetLabel: '播放进度与音量', title: '拖动进度条检查最终成品', description: '底部播放条支持播放、暂停、任意时间定位和音量调整。与翻唱工作台的输出进度条一样，定位后可以快速回到问题段落。', details: [{ label: '播放', value: '播放 / 暂停成品音频' }, { label: '进度', value: '拖动滑杆定位到任意时间' }, { label: '导出', value: '右上角下载当前作品文件' }], route: '/player', selector: '[data-guide="player-transport"], [data-guide="player-empty"]', placement: 'top', icon: MagicStick, prepare: 'open-player' },
  { section: '我的模型 · 37', targetLabel: '模型导入与检测', title: '导入、检查和整理本地模型', description: '模型管理页按框架提供对应文件选择器。导入后可以检测元数据、修复可推断配置、收藏、设为默认或分享到模型站。', details: [{ label: '导入', value: '按框架选择权重、配置、索引和扩散文件' }, { label: '检测', value: '发现缺失元数据时可尝试修复' }, { label: '默认', value: '设为默认后新建翻唱会优先选它' }], route: '/models', selector: '[data-guide="model-list"]', placement: 'right', icon: FolderOpened },
  { section: '我的模型 · 38', targetLabel: '模型重命名', title: '给自己的模型起一个容易记的名字', description: '点击模型行的编辑按钮即可重命名。名称只影响界面显示和作品标签，不会改动权重文件、路径或模型 ID。', details: [{ label: '建议', value: '用“角色 · 音域 · 风格”组合命名' }, { label: '同步', value: '翻唱工作台、多模型时间轴和作品库都会显示新名称' }, { label: '安全', value: '不会移动、覆盖或重写模型文件' }], route: '/models', selector: '[data-guide="model-rename"]', placement: 'top', icon: Setting },
  { section: '插件中心 · 39', targetLabel: '插件设置与安装', title: '按需扩展工作台', description: '插件中心的总开关默认可以保持关闭。需要扩展时先配置市场地址或安装本地 .xbplugin / .zip，再单独启用可信插件。', details: [{ label: '总开关', value: '关闭时不影响原有翻唱流程' }, { label: '安装', value: '市场安装或本地插件包安装' }, { label: '权限', value: '查看插件运行环境和权限摘要后再启用' }], route: '/plugins', selector: '[data-guide="plugin-settings"]', placement: 'right', icon: FolderOpened },
  { section: '插件中心 · 40', targetLabel: '已安装插件与市场', title: '管理插件页面和运行状态', description: '市场区域用于发现和安装扩展，已安装区域可以逐个打开、启用或卸载。前端页面插件和运行时插件都会显示自己的状态。', details: [{ label: '单独启用', value: '某个插件异常时可只关闭它' }, { label: '打开', value: '进入插件提供的工作页面' }, { label: '卸载', value: '移除插件包，不影响模型和作品' }], route: '/plugins', selector: '[data-guide="plugin-installed"], [data-guide="plugin-market"]', placement: 'bottom', icon: MagicStick },
  { section: 'API 接入 · 41', targetLabel: '服务配置', title: '需要外部调用时再启动 API', description: 'API 服务默认停止，只在本次运行期间手动启动。可以选择仅本机或局域网、修改端口、复制 API Key 并做连通性测试。', details: [{ label: '安全', value: '优先使用仅本机监听，局域网只在可信网络开启' }, { label: '密钥', value: '调用受保护接口时放在 X-API-Key 请求头' }, { label: '生命周期', value: '停止服务后外部任务无法继续访问' }], route: '/api', selector: '[data-guide="api-service"]', placement: 'right', icon: Setting },
  { section: 'API 接入 · 42', targetLabel: '调用文档', title: '按文档接入上传、任务和下载', description: '调用文档提供 Python 和 PowerShell 示例，以及完整的 v1 接口列表。典型流程是上传音频、读取模型、创建任务、轮询状态，最后下载成品。', details: [{ label: '示例', value: '切换语言后复制完整请求代码' }, { label: '异步任务', value: '创建返回 202，轮询到 done 再下载' }, { label: '接口', value: '健康检查、模型、上传、任务、结果和重试' }], route: '/api', selector: '[data-guide="api-docs"]', placement: 'top', icon: FolderOpened },
]

const activeStep = computed(() => steps[currentStep.value] ?? steps[0]!)
const focusStyle = computed(() => {
  const rect = targetRect.value
  if (!rect) return {}
  const pad = 8
  return {
    top: `${Math.max(8, rect.top - pad)}px`,
    left: `${Math.max(8, rect.left - pad)}px`,
    width: `${Math.max(12, rect.width + pad * 2)}px`,
    height: `${Math.max(12, rect.height + pad * 2)}px`,
  }
})
const calloutStyle = computed(() => {
  const rect = targetRect.value
  if (!rect) return { top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }
  const margin = 18
  const width = Math.min(380, Math.max(280, window.innerWidth - 32))
  const estimatedHeight = Math.min(430, Math.max(260, window.innerHeight - 40))
  let top = rect.bottom + margin
  let left = rect.left
  if (activeStep.value.placement === 'top') top = rect.top - estimatedHeight - margin
  if (activeStep.value.placement === 'left') left = rect.left - width - margin
  if (activeStep.value.placement === 'right') left = rect.right + margin
  if (activeStep.value.placement === 'right' || activeStep.value.placement === 'left') top = rect.top + (rect.height - estimatedHeight) / 2
  if (top + estimatedHeight > window.innerHeight - 16) top = window.innerHeight - estimatedHeight - 16
  if (top < 16) top = 16
  if (left + width > window.innerWidth - 16) left = window.innerWidth - width - 16
  if (left < 16) left = 16
  return { top: `${top}px`, left: `${left}px`, width: `${width}px` }
})

function wait(ms: number) { return new Promise<void>((resolve) => window.setTimeout(resolve, ms)) }

function findTarget() {
  const selectors = activeStep.value.selector.split(',').map((item) => item.trim()).filter(Boolean)
  for (const selector of selectors) {
    const target = document.querySelector<HTMLElement>(selector)
    if (target) return target
  }
  return null
}

async function locateTarget() {
  locating.value = true
  hasTarget.value = false
  targetRect.value = null
  let target: HTMLElement | null = null
  for (let attempt = 0; attempt < 75; attempt += 1) {
    target = findTarget()
    if (target) break
    await wait(40)
  }
  if (target) {
    target.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' })
    await wait(220)
    targetRect.value = target.getBoundingClientRect()
    hasTarget.value = targetRect.value.width > 0 && targetRect.value.height > 0
  }
  locating.value = false
}

type GuideDemoKind = 'multi' | 'multi-timeline' | 'enhancement'
let activeDemo: GuideDemoKind | null = null
function emitDemo(kind: GuideDemoKind) {
  window.dispatchEvent(new CustomEvent('xb-guide-demo', { detail: { action: 'prepare', kind } }))
}
function restoreDemo() {
  if (!activeDemo) return
  window.dispatchEvent(new CustomEvent('xb-guide-demo', { detail: { action: 'restore' } }))
  activeDemo = null
}

async function prepareStep(step: GuideStep) {
  if (step.prepare === 'multi' || step.prepare === 'multi-timeline' || step.prepare === 'enhancement') {
    const kind: GuideDemoKind = step.prepare
    if (activeDemo !== kind) {
      restoreDemo()
      emitDemo(kind)
      activeDemo = kind
      await wait(kind === 'multi-timeline' ? 260 : 160)
    }
    return
  }
  if (step.prepare !== 'open-player') {
    restoreDemo()
    return
  }
  if (step.prepare === 'open-player') {
    restoreDemo()
    if (route.path !== '/works') {
      await router.push('/works')
      await nextTick()
    }
    const play = document.querySelector<HTMLElement>('[data-guide="works-list"] .work-play:not(:disabled)')
    if (play) {
      play.click()
      await wait(180)
    }
  }
}

async function goToStep(index: number) {
  if (locating.value || index < 0 || index >= steps.length) return
  currentStep.value = index
  const targetRoute = activeStep.value.route
  locating.value = true
  try {
    if (activeStep.value.prepare === 'open-player') {
      await prepareStep(activeStep.value)
      if (route.path !== targetRoute) await router.push(targetRoute)
    } else {
      if (route.path !== targetRoute) await router.push(targetRoute)
      await nextTick()
      await prepareStep(activeStep.value)
    }
    await nextTick()
    await locateTarget()
  } catch {
    locating.value = false
  }
}

function next() {
  if (currentStep.value >= steps.length - 1) {
    finish()
    return
  }
  void goToStep(currentStep.value + 1)
}

function finish() {
  restoreDemo()
  visible.value = false
  hasTarget.value = false
  targetRect.value = null
  try {
    localStorage.setItem(STORAGE_KEY, '1')
  } catch {
    /* The guide can still be dismissed for this session when storage is blocked. */
  }
}

function skip() { finish() }

function updateFocus() {
  if (!visible.value || !hasTarget.value) return
  if (focusRaf) cancelAnimationFrame(focusRaf)
  focusRaf = requestAnimationFrame(() => {
    focusRaf = 0
    const target = findTarget()
    if (target) targetRect.value = target.getBoundingClientRect()
  })
}

watch(() => route.path, () => {
  if (visible.value && !locating.value) void locateTarget()
})

onMounted(() => {
  window.addEventListener('resize', updateFocus, { passive: true })
  window.addEventListener('scroll', updateFocus, { passive: true })
  let shouldShow = false
  try {
    shouldShow = localStorage.getItem(STORAGE_KEY) !== '1'
  } catch {
    shouldShow = true
  }
  if (shouldShow) {
    window.setTimeout(() => {
      visible.value = true
      void goToStep(0)
    }, 240)
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', updateFocus)
  window.removeEventListener('scroll', updateFocus)
  if (focusRaf) cancelAnimationFrame(focusRaf)
})
</script>

<style scoped>
.interactive-guide { position: fixed; inset: 0; z-index: 3000; pointer-events: none; color: var(--xb-text); }
.guide-focus { position: fixed; z-index: 1; border: 2px solid var(--xb-primary); border-radius: 9px; box-shadow: 0 0 0 9999px rgba(var(--xb-bg-rgb), .76), 0 0 0 5px rgba(var(--xb-primary-rgb), .14), 0 0 30px rgba(var(--xb-primary-rgb), .36); pointer-events: none; transition: top .28s ease, left .28s ease, width .28s ease, height .28s ease; }
.guide-focus::after { content: ''; position: absolute; inset: -7px; border: 1px solid rgba(var(--xb-primary-rgb), .68); border-radius: 13px; animation: guide-focus-pulse 1.8s ease-in-out infinite; }
.guide-callout { position: fixed; z-index: 2; max-height: min(470px, calc(100vh - 32px)); overflow-y: auto; padding: 16px; border: 1px solid rgba(var(--xb-primary-rgb), .34); border-radius: 12px; background: linear-gradient(145deg, rgba(var(--xb-primary-rgb), .11), transparent 46%), var(--xb-bg-2); box-shadow: 0 20px 50px rgba(var(--xb-bg-rgb), .58), 0 0 0 1px rgba(var(--xb-fill-rgb), .06) inset; pointer-events: auto; }
.callout-header { display: flex; align-items: center; gap: 10px; min-height: 24px; }
.callout-section { display: inline-flex; align-items: center; gap: 6px; color: var(--xb-primary); font-size: 11px; font-weight: 800; letter-spacing: .08em; }
.callout-count { margin-left: auto; color: var(--xb-muted); font: 11px ui-monospace, monospace; }
.callout-close { display: grid; place-items: center; width: 28px; height: 28px; margin-left: 2px; border: 0; border-radius: 7px; background: rgba(var(--xb-fill-rgb), .06); color: var(--xb-muted); cursor: pointer; }
.callout-close:hover { color: var(--xb-text); background: rgba(var(--xb-primary-rgb), .14); }
.callout-heading { display: flex; align-items: center; gap: 11px; margin-top: 15px; }
.callout-icon { display: grid; flex: 0 0 auto; place-items: center; width: 42px; height: 42px; border: 1px solid rgba(var(--xb-primary-rgb), .32); border-radius: 10px; background: rgba(var(--xb-primary-rgb), .12); color: var(--xb-primary); font-size: 20px; }
.callout-heading-copy { min-width: 0; }
.callout-target { margin: 0 0 3px; overflow: hidden; color: var(--xb-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.callout-heading h1 { margin: 0; font-size: 19px; line-height: 1.28; }
.callout-description { margin: 14px 0 12px; color: var(--xb-muted); font-size: 13px; line-height: 1.65; }
.callout-details { display: grid; gap: 7px; }
.callout-detail { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 8px; padding: 8px 9px; border-left: 2px solid rgba(var(--xb-primary-rgb), .52); background: rgba(var(--xb-fill-rgb), .045); font-size: 12px; line-height: 1.45; }
.callout-detail strong { color: var(--xb-text); }
.callout-detail span { color: var(--xb-muted); }
.callout-locating { display: flex; align-items: center; gap: 7px; margin: 11px 0 0; color: var(--xb-primary); font-size: 11px; }
.callout-locating i { width: 7px; height: 7px; border-radius: 50%; background: var(--xb-primary); box-shadow: 0 0 10px var(--xb-primary); animation: guide-dot-pulse 1s ease-in-out infinite; }
.callout-locating.is-warning { color: var(--xb-warn); }
.callout-locating.is-warning i { background: var(--xb-warn); box-shadow: 0 0 10px var(--xb-warn); animation: none; }
.callout-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 16px; padding-top: 13px; border-top: 1px solid rgba(var(--xb-fill-rgb), .1); }
.guide-skip, .guide-back, .guide-next { border: 0; font: inherit; cursor: pointer; }
.guide-skip { padding: 6px 0; background: none; color: var(--xb-muted); font-size: 12px; }
.guide-skip:hover { color: var(--xb-text); }
.guide-actions { display: flex; align-items: center; gap: 8px; }
.guide-back { padding: 8px 11px; border: 1px solid var(--xb-border); border-radius: 6px; background: transparent; color: var(--xb-text); font-size: 12px; }
.guide-back:hover:not(:disabled) { border-color: var(--xb-primary); }
.guide-next { display: inline-flex; align-items: center; gap: 7px; padding: 9px 13px; border-radius: 6px; background: var(--xb-primary); color: var(--xb-on-primary); font-size: 12px; font-weight: 800; box-shadow: 0 8px 18px rgba(var(--xb-primary-rgb), .22); }
.guide-next:hover:not(:disabled) { filter: brightness(1.08); transform: translateY(-1px); }
.guide-back:disabled, .guide-next:disabled { opacity: .5; cursor: wait; }
.interactive-guide-enter-active, .interactive-guide-leave-active { transition: opacity .2s ease; }
.interactive-guide-enter-active .guide-callout, .interactive-guide-leave-active .guide-callout { transition: opacity .22s ease, transform .22s ease; }
.interactive-guide-enter-from, .interactive-guide-leave-to { opacity: 0; }
.interactive-guide-enter-from .guide-callout, .interactive-guide-leave-to .guide-callout { opacity: 0; transform: translateY(10px) scale(.98); }
@keyframes guide-focus-pulse { 0%, 100% { opacity: .35; transform: scale(1); } 50% { opacity: .9; transform: scale(1.015); } }
@keyframes guide-dot-pulse { 0%, 100% { opacity: .45; } 50% { opacity: 1; } }
@media (max-width: 700px) { .guide-callout { max-height: min(520px, calc(100vh - 24px)); } }
@media (max-width: 520px) {
  .guide-callout { width: calc(100vw - 24px) !important; max-height: calc(100vh - 24px); padding: 14px; }
  .callout-heading h1 { font-size: 17px; }
  .callout-detail { grid-template-columns: 64px minmax(0, 1fr); }
  .callout-footer { align-items: stretch; }
  .guide-actions { flex: 1; justify-content: flex-end; }
}
@media (prefers-reduced-motion: reduce) {
  .guide-focus { transition: none; }
  .guide-focus::after, .callout-locating i { animation: none; }
  .interactive-guide-enter-active, .interactive-guide-leave-active, .interactive-guide-enter-active .guide-callout, .interactive-guide-leave-active .guide-callout { transition: none; }
  .guide-next:hover:not(:disabled) { transform: none; }
}
</style>
