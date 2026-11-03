import { computed, readonly, ref, watch } from 'vue'
import { enExtraPhrases, jaExtraPhrases, translateDynamicPhrase } from './extraPhrases'

export type AppLocale = 'zh-CN' | 'en-US' | 'ja-JP'

const STORAGE_KEY = 'xb-locale'

export const localeOptions: ReadonlyArray<{
  value: AppLocale
  short: string
  label: string
  nativeLabel: string
}> = [
  { value: 'zh-CN', short: '中', label: 'Chinese', nativeLabel: '简体中文' },
  { value: 'en-US', short: 'EN', label: 'English', nativeLabel: 'English' },
  { value: 'ja-JP', short: '日', label: 'Japanese', nativeLabel: '日本語' },
]

const messages = {
  'zh-CN': {
    'language.title': '界面语言',
    'language.current': '当前语言：{language}',
    'nav.home': '首页',
    'nav.cover': 'AI 翻唱',
    'nav.enhancement': 'AI 增强',
    'nav.editor': '音频编辑',
    'nav.library': '资料库',
    'nav.music': '资源获取',
    'nav.musicDesc': '找歌与伴奏素材',
    'nav.models': '我的模型',
    'nav.modelsDesc': '管理声音模型',
    'nav.works': '我的作品',
    'nav.worksDesc': '查看生成任务',
    'nav.api': 'API 接入',
    'nav.apiDesc': '外部程序调用与测试',
    'nav.plugins': '插件中心',
    'nav.pluginsDesc': '市场、扩展与开发入口',
    'header.search': '搜索作品、模型…',
    'header.ready': '环境就绪',
    'header.degraded': '降级模式',
    'header.checking': '正在检测集成工具…',
    'header.noResult': '没有匹配「{query}」的结果',
    'header.model': '模型',
    'header.work': '作品',
  },
  'en-US': {
    'language.title': 'Interface language',
    'language.current': 'Language: {language}',
    'nav.home': 'Home',
    'nav.cover': 'AI Cover',
    'nav.enhancement': 'AI Enhance',
    'nav.editor': 'Audio Editor',
    'nav.library': 'Library',
    'nav.music': 'Resources',
    'nav.musicDesc': 'Find songs and instrumentals',
    'nav.models': 'My Models',
    'nav.modelsDesc': 'Manage voice models',
    'nav.works': 'My Works',
    'nav.worksDesc': 'View generated jobs',
    'nav.api': 'API Access',
    'nav.apiDesc': 'External integration and testing',
    'nav.plugins': 'Plugins',
    'nav.pluginsDesc': 'Marketplace and extensions',
    'header.search': 'Search works and models…',
    'header.ready': 'Ready',
    'header.degraded': 'Limited mode',
    'header.checking': 'Checking integrated tools…',
    'header.noResult': 'No results for “{query}”',
    'header.model': 'Model',
    'header.work': 'Work',
  },
  'ja-JP': {
    'language.title': '表示言語',
    'language.current': '現在の言語：{language}',
    'nav.home': 'ホーム',
    'nav.cover': 'AIカバー',
    'nav.enhancement': 'AI強化',
    'nav.editor': '音声編集',
    'nav.library': 'ライブラリ',
    'nav.music': '素材取得',
    'nav.musicDesc': '楽曲と伴奏素材を検索',
    'nav.models': 'マイモデル',
    'nav.modelsDesc': '音声モデルを管理',
    'nav.works': 'マイ作品',
    'nav.worksDesc': '生成タスクを確認',
    'nav.api': 'API連携',
    'nav.apiDesc': '外部アプリ連携とテスト',
    'nav.plugins': 'プラグイン',
    'nav.pluginsDesc': 'マーケットと拡張機能',
    'header.search': '作品・モデルを検索…',
    'header.ready': '準備完了',
    'header.degraded': '制限モード',
    'header.checking': '統合ツールを確認中…',
    'header.noResult': '「{query}」に一致する結果はありません',
    'header.model': 'モデル',
    'header.work': '作品',
  },
} as const

type MessageKey = keyof (typeof messages)['zh-CN']

const enPhrases: Record<string, string> = {
  ...enExtraPhrases,
  '欢迎回来': 'Welcome back', '// 欢迎回来，Lkpap': '// Welcome back, Lkpap', '首页': 'Home', '资料库': 'Library', '资源获取': 'Resources',
  '我的模型': 'My Models', '我的作品': 'My Works', '插件中心': 'Plugins', 'API 接入': 'API Access',
  'AI 翻唱': 'AI Cover', 'AI 增强': 'AI Enhance', '音频编辑': 'Audio Editor',
  '歌声转换工作台': 'Voice Conversion Studio', 'AI 歌声增强工作台': 'AI Vocal Enhancement Studio',
  '实时翻唱工作台': 'Realtime Cover Studio', '音频编辑工作台': 'Audio Editor',
  '翻唱作品库': 'Cover Library', '在线曲库': 'Online Music Library', '声音模型': 'Voice Models',
  '编辑工程': 'Editor Projects', '新建工程': 'New Project', '暂无编辑工程': 'No editor projects yet',
  '快捷功能': 'Quick Actions', '集成工具': 'Integrated Tools', '最近作品': 'Recent Works',
  '上传歌曲': 'Upload Song', '选择你的模型': 'Choose a Model', '选择参与模型': 'Select Models',
  '单模型翻唱': 'Single Model', '多模型混合': 'Multi-model Mix', '整首歌用一个模型': 'Use one model for the full song',
  '逐句指派不同模型': 'Assign models by phrase', '高级功能': 'Advanced', '实时翻唱': 'Realtime Cover',
  '上传歌曲 → 选择模型 → 调整参数 → 一键生成翻唱': 'Upload song → Choose model → Adjust settings → Generate cover',
  '拖拽音频到此处': 'Drop audio here', '点击选择或拖拽音频文件': 'Click or drop an audio file',
  '支持 MP3 / WAV / FLAC 等音频格式，不设固定大小上限': 'Supports MP3, WAV, FLAC and more, with no fixed size limit',
  '从已下载素材选择': 'Choose from downloaded files', '选择音频': 'Choose Audio', '选择模型': 'Choose Model',
  '管理模型': 'Manage Models', '导入模型': 'Import Model', '导入 SVC 模型': 'Import SVC Model',
  '模型框架': 'Model Framework', '模型名称': 'Model Name', '模型架构': 'Architecture', '模型简介': 'Description',
  '主模型权重': 'Main Model Weights', '主模型配置': 'Main Model Config', '扩散模型（可选）': 'Diffusion Model (optional)',
  '扩散配置（可选）': 'Diffusion Config (optional)', '检索特征 .index（可选）': 'Feature Index .index (optional)',
  '全部框架': 'All Frameworks', '全部': 'All', '默认': 'Default', '收藏': 'Favorite', '公开': 'Public',
  '可推理': 'Ready', '预留': 'Reserved', '已检测': 'Checked', '需修复': 'Needs Repair',
  '默认（模型首位）': 'Default (first voice)', '未设置': 'Not set', '未选择': 'Not selected', '未分配': 'Unassigned',
  '版本待检测': 'Version pending', '依赖检查': 'Dependency Check', '有更新': 'Update available', '最新': 'Latest',
  '模型站': 'Model Hub', '打开模型站': 'Open Model Hub', '下载模型': 'Download Model', '正在读取模型清单…': 'Loading model catalog…',
  '没有找到相关模型': 'No matching models', '暂无可用模型': 'No models available', '模型已就绪': 'Model ready',
  '已下载': 'Downloaded', '未下载': 'Not downloaded', '下载中…': 'Downloading…', '下载失败，可重试': 'Download failed. Try again.',
  '前期人声处理': 'Vocal Preprocessing', '启用前期人声分离': 'Enable vocal separation', '分离引擎': 'Separation Engine',
  '人声分离模型': 'Vocal Separation Model', '去混响 / 人声净化模型': 'Dereverb / Vocal Cleanup Model',
  '分离后去混响 / 净化人声': 'Dereverb / clean vocals after separation', '通用': 'General', '高质量': 'High Quality',
  '推理参数': 'Inference Settings', '全参数手动调整': 'Manual Advanced Settings', '已启用': 'Enabled',
  '基础可调 · 高级默认': 'Basic controls · Advanced defaults', '高级使用默认': 'Advanced defaults',
  '变调': 'Pitch Shift', '变调（半音）': 'Pitch Shift (semitones)', '共振峰偏移': 'Formant Shift',
  '共振峰偏移（半音）': 'Formant Shift (semitones)', '参考音频': 'Reference Audio', '目标音色参考音频': 'Target Voice Reference',
  '说话人': 'Speaker', '目标说话人 / 音色 ID': 'Target Speaker / Voice ID', '设备': 'Device', '推理设备': 'Inference Device',
  '版本': 'Version', '模型版本': 'Model Version', 'RVC 模型版本': 'RVC Model Version', 'F0 提取算法': 'F0 Method',
  'F0 算法': 'F0 Method', 'F0 过滤阈值': 'F0 Filter Threshold', 'F0 中值滤波半径': 'F0 Median Filter Radius',
  '索引比率': 'Index Rate', '检索比率': 'Index Rate', '检索率': 'Index Rate', '响度包络融合': 'RMS Envelope Mix',
  '清辅音保护': 'Consonant Protection', '清辅音保护 (protect)': 'Consonant Protection (protect)', '滤波半径': 'Filter Radius',
  '自动高音保护': 'Automatic High-note Protection', '高音保护': 'High-note Protection', '高音保护轮次': 'Protection Rounds',
  '选择性降调/复原，减少高音失真': 'Selective pitch lowering and restoration reduces high-note distortion',
  '轮次为 0 时由系统自动接管': '0 lets the system choose automatically',
  '轮次为 0 时由系统自动接管，行为与普通模式一致': 'At 0, the system takes over automatically, matching normal mode',
  '每轮失败后会根据实际哑音位置自动降低内部保护起点': 'After each failed pass, the protection threshold follows the detected dropout',
  '歌词分句指派': 'Assign by Lyric Phrase', '（无歌词）': '(No lyrics)', '间奏 · 不唱': 'Instrumental · No vocal',
  '点选模型演唱本段，多选即「合唱」': 'Select models for this phrase; multiple models create a chorus',
  '处理流程': 'Processing', '输出预览': 'Output Preview', '失败原因': 'Failure Details', '推理失败，请查看日志': 'Inference failed. Check the log.',
  '队列': 'Queue', '等待': 'Waiting', '处理中': 'Processing', '正在处理': 'Processing', '完成': 'Done', '失败': 'Failed',
  '取消': 'Cancel', '保存': 'Save', '确认': 'Confirm', '删除': 'Delete', '编辑': 'Edit', '重试': 'Retry',
  '刷新': 'Refresh', '重置': 'Reset', '清除': 'Clear', '移除': 'Remove', '关闭': 'Close', '打开': 'Open',
  '搜索': 'Search', '下载': 'Download', '上传': 'Upload', '导入': 'Import', '导出': 'Export', '使用': 'Use',
  '更换': 'Change', '选择': 'Choose', '添加': 'Add', '创建': 'Create', '复制': 'Copy', '粘贴': 'Paste',
  '开始': 'Start', '结束': 'End', '暂停': 'Pause', '继续': 'Resume', '停止': 'Stop', '预览': 'Preview',
  '基础层': 'Basic', '高级层': 'Advanced', '基础增强': 'Basic Enhancement', '高级增强': 'Advanced Enhancement',
  '增强参数': 'Enhancement Settings', '增强任务': 'Enhancement Job', '增强目标': 'Enhancement Target', '增强层级': 'Enhancement Level',
  '选择增强目标': 'Choose Enhancement Target', '提供原始歌曲': 'Provide Original Song', '原始歌曲': 'Original Song',
  '本地文件': 'Local File', '当前原始歌曲': 'Current Original Song',
  '创建翻唱': 'Create Cover', '开始 AI 增强': 'Start AI Enhancement', '重新创建增强任务': 'Recreate Enhancement Job',
  '播放增强成品': 'Play Enhanced Result', '打开我的作品': 'Open My Works', '返回 AI 翻唱': 'Back to AI Cover',
  '自然修音': 'Natural Pitch Correction', 'AI 对齐': 'AI Alignment', 'AI 角色共振峰': 'AI Formant Matching',
  'AI 响度包络': 'AI Loudness Envelope', '真实细节保护': 'Natural Detail Protection', '宽带校正': 'Broadband Correction',
  '播放源': 'Playback Source', '系统音频变声器': 'System Audio Voice Changer', '歌曲文件实时播放': 'Realtime Song Playback',
  '系统混合音频输入': 'System Mix Input', '变声输出设备': 'Voice Output Device', '刷新设备': 'Refresh Devices',
  '演唱编排': 'Voice Arrangement', '实时参数': 'Realtime Settings', '输出缓冲': 'Output Buffer', '转换块': 'Conversion Chunk',
  '转换人声': 'Converted Vocal', '伴奏': 'Instrumental', '原始伴奏保持不变': 'Keep original instrumental unchanged',
  '启动实时翻唱': 'Start Realtime Cover', '实时工程运行中': 'Realtime session running', '系统音频': 'System Audio',
  '已处理音频': 'Processed Audio', '转换缓冲': 'Conversion Buffer', '实时处理倍率': 'Realtime Speed', '导出成品': 'Export Result',
  '工程': 'Project', '工程文件 (.xbproject)': 'Project File (.xbproject)', '音轨': 'Track', '片段': 'Clip', '角色': 'Role',
  '角色管理': 'Role Manager', '未关联模型': 'No linked model', '效果': 'Effects', '效果器': 'Effects', '插件窗口': 'Plugin Window',
  '当前作用范围尚未添加效果': 'No effects in the current scope', '人声编辑': 'Vocal Editing', '局部重推理': 'Local Re-inference',
  '选择一个片段': 'Select a clip', '剪切': 'Split', '静音切句': 'Split on Silence', '复制音轨': 'Duplicate Track',
  '粘贴音频': 'Paste Audio', '未导出': 'Not exported', '吸附': 'Snap', '缩放': 'Zoom', '音量': 'Volume',
  '时间拉伸': 'Time Stretch', '淡入': 'Fade In', '淡出': 'Fade Out', '偏移': 'Offset', '节点': 'Nodes',
  '音量包络': 'Volume Envelope', '默认源': 'Default Source', '工程时间': 'Project Time', '片段时间': 'Clip Time',
  '当前片段 AI 增强': 'Enhance Current Clip', '重推理后自动美声': 'Auto-enhance after re-inference',
  '新建音轨': 'New Track', '时间轴模板': 'Timeline Templates', '还没有角色': 'No roles yet',
  '管理、试听并导出你生成的所有 AI 翻唱作品': 'Manage, preview, and export all generated AI covers',
  '作品': 'Work', '使用模型': 'Model', '时长': 'Duration', '状态': 'Status', '创建时间': 'Created', '操作': 'Actions',
  '暂无作品': 'No works yet', '去创作': 'Create Now', '作品播放': 'Work Player', '作品库': 'Works',
  '正在准备播放页面…': 'Preparing player…', '歌词': 'Lyrics', '未载入': 'Not loaded', '未知歌手': 'Unknown Artist',
  '曲库设置': 'Music Library Settings', '让歌词跟着音乐亮起来': 'Sync lyrics with the music',
  '找不到这首作品': 'Work not found', '它可能已被删除，或仍在生成中。': 'It may have been deleted or is still being generated.',
  '返回作品库': 'Back to Works', '尚未配置 API Key': 'API Key not configured', '前往设置': 'Open Settings',
  '搜索结果': 'Search Results', '已下载素材': 'Downloaded Resources', '不可播放': 'Unavailable', '换个关键词试试吧': 'Try another keyword',
  '服务配置': 'Service Settings', '监听范围': 'Listen Scope', '仅本机': 'Local Only', '局域网': 'LAN',
  '监听端口': 'Port', '绑定域名': 'Domain', '访问地址': 'Access URL', 'API 密钥': 'API Keys', '调用文档': 'API Guide',
  '上传限制': 'Upload Limits', '外部访问': 'External Access', '异步任务': 'Async Jobs', '永不过期': 'Never expires',
  '插件功能': 'Plugin Runtime', '插件市场': 'Plugin Marketplace', '刷新市场': 'Refresh Marketplace',
  '安装本地插件包': 'Install Local Plugin Package', '开发目录': 'Development Directory', '已安装插件': 'Installed Plugins',
  '插件运行中': 'Plugins running', '插件已暂停': 'Plugins paused', '官方': 'Official', '市场': 'Marketplace',
  '暂无说明': 'No description', '未知作者': 'Unknown author', '安装': 'Install', '仅索引': 'Index only', '卸载': 'Uninstall',
  '主题': 'Theme', '自定义主题': 'Custom Theme', '背景与粒子': 'Background & Particles', '添加背景': 'Add Background',
  '更换背景': 'Change Background', '背景遮罩': 'Background Overlay', '动态粒子': 'Animated Particles',
  '粒子数量': 'Particle Count', '粒子大小': 'Particle Size', '恢复默认': 'Restore Default', '更换头像': 'Change Avatar',
  '昵称': 'Nickname', '消息': 'Messages', '消息通知': 'Notifications', '全部已读': 'Mark All Read', '暂无消息': 'No notifications',
  '传输任务': 'Transfers', '清除已完成': 'Clear Finished', '暂无传输任务': 'No transfers',
  '环境就绪': 'Ready', '降级模式': 'Limited mode', '正在检测集成工具…': 'Checking integrated tools…',
  'WAV 无损': 'WAV Lossless', 'FLAC 无损压缩': 'FLAC Lossless', 'MP3 通用格式': 'MP3 Universal', 'M4A 移动设备': 'M4A Mobile',
  '数据存储位置': 'Data Storage', '已用': 'Used', '所在磁盘可用': 'Disk available', '未知时间': 'Unknown time',
  '用你自己的': 'Use Your Own', 'SVC 模型': 'SVC Model', '翻唱': 'to Create Covers',
  '导入你的 SVC 歌声模型，上传一首歌，软件会自动用 Ultimate Vocal Remover 分离人声、用 ffmpeg 处理音频，数十秒生成高保真翻唱作品。': 'Import an SVC voice model and upload a song. The app separates vocals with Ultimate Vocal Remover, processes audio with ffmpeg, and creates a high-quality cover in moments.',
  '上传歌曲开始': 'Upload a Song', '打开目录': 'Open Folder', '选择目录': 'Choose Folder', '迁移数据': 'Move Data',
  '已导入模型': 'Imported Models', '已完成': 'Completed', '运行环境就绪': 'Runtime Ready', '部分工具降级': 'Some Tools Limited',
  '全部模型': 'All Models', '配置文件': 'config file', '.pth / .onnx + 配置文件': '.pth / .onnx + config', '模型管理': 'Model Management', '试听': 'Preview', '尚未完成': 'Not finished',
  '选择格式下载': 'Choose Download Format', '更多': 'More', '重命名': 'Rename', '重新生成': 'Generate Again', '查看日志': 'View Log',
  '在「我的作品」中查看': 'View in My Works', '还没有作品，去「AI 翻唱」生成第一首吧。': 'No works yet. Create your first one in AI Cover.',
  '加载 SVC 模型，一键换声生成翻唱': 'Load an SVC model and generate a cover in one click',
  '人声分离': 'Vocal Separation', '由 Ultimate Vocal Remover 提取干声与伴奏': 'Extract clean vocals and instrumentals with Ultimate Vocal Remover',
  '管理 .pth / .onnx 的 SVC 歌声模型': 'Manage .pth / .onnx SVC voice models', '从本地导入新的 SVC 歌声模型': 'Import a new SVC voice model from your computer',
  '首页 · 01': 'Home · 01', '首页 · 02': 'Home · 02',
  '翻唱工作台 · 03': 'AI Cover · 03', '翻唱工作台 · 04': 'AI Cover · 04', '翻唱工作台 · 05': 'AI Cover · 05',
  '前期人声处理 · 06': 'Vocal Preprocessing · 06', '前期人声处理 · 07': 'Vocal Preprocessing · 07',
  '翻唱工作台 · 08': 'AI Cover · 08', '单模型推理 · 09': 'Single-model Inference · 09', '单模型推理 · 10': 'Single-model Inference · 10',
  '从这里开始一次完整翻唱': 'Start a Complete Cover Here', '正在查看 · AI 翻唱快捷入口': 'Viewing · AI Cover shortcut',
  'AI 翻唱工作台负责导入歌曲、选择音色、设置推理并生成作品。点击快捷入口进入空白工作台；从首页拖入音频则会把该文件一并带入。': 'The AI Cover studio imports songs, selects voices, configures inference, and generates your work. Open it from this shortcut, or drop audio on the home page to bring the file with you.',
  '点击卡片': 'Click card', '进入空白工作台': 'Open an empty studio', '拖拽音频': 'Drop audio', '自动跳转并预填这首歌': 'Open the studio with this song prefilled',
  '拖入音频会自动带入翻唱': 'Dropped Audio Follows You to the Studio', '首页音频拖拽区': 'Home audio drop zone',
  '把歌曲拖到首页这个区域，软件会校验格式，然后跳转到 AI 翻唱并显示刚才的文件。直接点击区域仍然只是打开空白工作台。': 'Drop a song here to validate it and open AI Cover with the file selected. Clicking the area opens an empty studio.',
  '格式': 'Formats', '大小': 'Size', '不设固定大小上限': 'No fixed size limit',
  '先决定整首歌还是逐句分配': 'Choose One Voice or Phrase-by-Phrase Assignment', '单模型 / 多模型模式': 'Single / multi-model mode',
  '单模型适合整首歌保持一个音色，步骤少、最容易成功。多模型会显示歌词时间轴，可以按句选择不同音色，也可以多选形成合唱。': 'Single-model mode keeps one voice across the song and is the simplest option. Multi-model mode adds a lyric timeline for assigning voices by phrase or creating choruses.',
  '单模型': 'Single model', '多模型': 'Multi-model', '整首统一音色，适合快速生成': 'One voice for the full song; ideal for quick results',
  '逐句分配模型，适合角色切换与和声': 'Assign each phrase for character changes and harmonies', '切换': 'Switching', '已填写的歌曲与常用参数会保留': 'The song and common settings are retained',
  '点击选择或拖拽歌曲': 'Click or Drop a Song', '歌曲导入区': 'Song import area',
  '工作台的导入区与首页行为一致。你可以点击选择本地文件，也可以直接拖入；已下载的曲库素材会列在下方，一键即可使用。': 'The studio import area works like the home page. Choose a local file or drop one here; downloaded library items appear below for quick reuse.',
  '桌面端选择路径，网页端读取文件': 'Choose a path on desktop or read a file in the browser',
  '从资源获取页下载的歌曲可直接复用': 'Songs from Resources can be reused directly', '导入后先确认歌曲和时长再推理': 'Verify the song and duration before inference',
  '先选择需要的工作流': 'Choose the Workflow You Need', '高级功能开关': 'Advanced workflow switches',
  '这里集中放置前期处理和歌声增强等工作流。普通用户可以保持默认关闭；需要更细的声音处理时再进入对应模块。': 'Preprocessing and vocal enhancement workflows are grouped here. Keep them off for a simple run, or enable them when you need finer audio processing.',
  '前期处理': 'Preprocessing', '先分离人声、去混响，再送进模型': 'Separate and dereverb vocals before inference', '歌声增强': 'Vocal enhancement',
  '生成前做自然修音与动态处理': 'Apply natural tuning and dynamics before output', '普通流程': 'Standard workflow', '不打开高级功能也可以直接生成': 'Generate directly without advanced features',
  '在推理前清理输入人声': 'Clean Input Vocals Before Inference',
  '打开前期处理后，软件会先把歌曲拆成人声和伴奏。干净的人声能减少伴奏串音，让后面的音高检测和音色转换更稳定。': 'With preprocessing enabled, the app separates vocals and instrumental first. Cleaner vocals reduce bleed and improve pitch tracking and voice conversion.',
  '开启': 'On', '直接使用原始音频，速度最快': 'Use original audio for maximum speed', '先分离再进入翻唱流水线': 'Separate before entering the cover pipeline',
  '注意': 'Note', '处理本身会增加耗时，先试听结果再决定': 'Processing takes longer; preview the result before deciding',
  '按环境选择 UVR 或 PyMSS': 'Choose UVR or PyMSS for Your Setup', '分离引擎选择': 'Separation engine selection',
  'UVR 适合已有本地环境的快速分离；PyMSS 可以使用已下载的专用分离或去混响模型。先选引擎，再选具体模型，状态提示会告诉你是否可用。': 'UVR provides fast local separation. PyMSS supports downloaded specialist separation and dereverb models. Choose an engine, then a model; its status shows availability.',
  '可下载人声分离与去混响模型': 'Download vocal separation and dereverb models', '去混响': 'Dereverb', '可额外开启，改善房间声和尾音': 'Optionally reduce room sound and reverb tails',
  '选择适合的音色模型': 'Choose a Suitable Voice Model', '模型选择区': 'Model selection',
  '模型卡片会显示框架、采样率和类型。先按框架筛选，再点击模型。模型的音域配置会参与高音保护，不同模型不会共用一个固定阈值。': 'Model cards show framework, sample rate, and type. Filter by framework and select a model. Each model uses its own vocal range for high-note protection.',
  '筛选': 'Filter', '按 So-VITS-SVC、RVC、SeedVC、DDSP-SVC 等框架过滤': 'Filter by So-VITS-SVC, RVC, SeedVC, DDSP-SVC, and more',
  '点击一张卡片作为整首歌曲的音色': 'Choose one card as the voice for the full song', '勾选多张卡片后按歌词分配': 'Select multiple cards and assign them by lyric phrase',
  '默认模式先调常用参数': 'Start with Common Settings', '推理参数面板': 'Inference settings panel',
  '关闭全参数时，变调、F0 算法、设备、检索率、响度混合、保护、滤波半径等常用参数仍然可调。软件默认值保持原有推理效果，隐藏的高级值不会污染本次运行。': 'With manual advanced settings off, pitch, F0 method, device, index rate, loudness mix, protection, and filter radius remain available. Hidden advanced values do not affect the run.',
  '按男女声或歌曲音域做半音级调整': 'Adjust by semitones for voice type or song range', 'F0 / 设备': 'F0 / Device',
  '选择音高算法和 CPU / GPU 推理设备': 'Choose the pitch method and CPU / GPU device', 'RVC 参数': 'RVC settings', '检索率、响度混合、保护、滤波半径、版本': 'Index rate, loudness mix, protection, filter radius, and version',
  '理解主模型和浅扩散的分工': 'Understand Main and Diffusion Model Roles', '主模型 / 扩散模型比例': 'Main / diffusion model ratio',
  '这个比例决定主模型路径与浅扩散路径对成品的贡献。它不是“越大越好”，而是速度、音色稳定性、细节、显存之间的取舍。': 'This ratio balances the main and shallow diffusion paths. Higher is not always better; it trades speed, voice stability, detail, and GPU memory.',
  '主模型高': 'More main model', '速度快、音色轮廓稳定、显存压力较小': 'Faster, stable voice shape, and lower GPU memory use',
  '浅扩散高': 'More diffusion', '细节与自然度通常更丰富，但更慢且更吃显存': 'Often more detailed and natural, but slower and more memory intensive', '调法': 'Tuning', '先用默认值，出现毛刺或细节不足时小步调整': 'Start with defaults and make small changes when detail is lacking',
  '跳过引导': 'Skip Guide', '下一步': 'Next',
}

const jaPhrases: Record<string, string> = {
  ...enPhrases,
  ...jaExtraPhrases,
  '欢迎回来': 'おかえりなさい', '// 欢迎回来，Lkpap': '// おかえりなさい、Lkpap', '首页': 'ホーム', '资料库': 'ライブラリ', '资源获取': '素材取得',
  '我的模型': 'マイモデル', '我的作品': 'マイ作品', '插件中心': 'プラグイン', 'API 接入': 'API連携',
  'AI 翻唱': 'AIカバー', 'AI 增强': 'AI強化', '音频编辑': '音声編集',
  '歌声转换工作台': '歌声変換スタジオ', 'AI 歌声增强工作台': 'AI歌声強化スタジオ', '实时翻唱工作台': 'リアルタイムカバースタジオ',
  '音频编辑工作台': '音声編集ワークスペース', '翻唱作品库': 'カバー作品ライブラリ', '在线曲库': 'オンライン楽曲ライブラリ',
  '声音模型': '音声モデル', '编辑工程': '編集プロジェクト', '新建工程': '新規プロジェクト', '暂无编辑工程': '編集プロジェクトはありません',
  '快捷功能': 'クイック操作', '集成工具': '統合ツール', '最近作品': '最近の作品',
  '上传歌曲': '楽曲をアップロード', '选择你的模型': 'モデルを選択', '选择参与模型': '使用モデルを選択',
  '单模型翻唱': '単一モデル', '多模型混合': '複数モデル', '整首歌用一个模型': '曲全体で1つのモデルを使用',
  '逐句指派不同模型': 'フレーズごとにモデルを割り当て', '高级功能': '高度な機能', '实时翻唱': 'リアルタイムカバー',
  '上传歌曲 → 选择模型 → 调整参数 → 一键生成翻唱': '楽曲をアップロード → モデル選択 → 設定調整 → カバー生成',
  '拖拽音频到此处': 'ここに音声をドロップ', '点击选择或拖拽音频文件': 'クリックまたは音声ファイルをドロップ',
  '支持 MP3 / WAV / FLAC 等音频格式，不设固定大小上限': 'MP3 / WAV / FLAC などに対応。固定サイズ上限なし',
  '从已下载素材选择': 'ダウンロード済み素材から選択', '选择音频': '音声を選択', '选择模型': 'モデルを選択',
  '管理模型': 'モデル管理', '导入模型': 'モデルをインポート', '导入 SVC 模型': 'SVCモデルをインポート',
  '模型框架': 'モデル方式', '模型名称': 'モデル名', '模型架构': 'アーキテクチャ', '模型简介': 'モデル説明',
  '主模型权重': 'メインモデル重み', '主模型配置': 'メインモデル設定', '扩散模型（可选）': '拡散モデル（任意）',
  '扩散配置（可选）': '拡散設定（任意）', '检索特征 .index（可选）': '特徴インデックス .index（任意）',
  '全部框架': 'すべての方式', '全部': 'すべて', '默认': 'デフォルト', '收藏': 'お気に入り', '公开': '公開',
  '可推理': '使用可能', '预留': '予約済み', '已检测': '確認済み', '需修复': '修復が必要',
  '默认（模型首位）': 'デフォルト（先頭音声）', '未设置': '未設定', '未选择': '未選択', '未分配': '未割り当て',
  '版本待检测': 'バージョン未確認', '依赖检查': '依存関係チェック', '有更新': '更新あり', '最新': '最新',
  '模型站': 'モデルハブ', '打开模型站': 'モデルハブを開く', '下载模型': 'モデルをダウンロード', '正在读取模型清单…': 'モデル一覧を読み込み中…',
  '没有找到相关模型': '該当するモデルはありません', '暂无可用模型': '利用可能なモデルはありません', '模型已就绪': 'モデル準備完了',
  '已下载': 'ダウンロード済み', '未下载': '未ダウンロード', '下载中…': 'ダウンロード中…', '下载失败，可重试': 'ダウンロード失敗。再試行できます',
  '前期人声处理': 'ボーカル前処理', '启用前期人声分离': 'ボーカル分離を有効化', '分离引擎': '分離エンジン',
  '人声分离模型': 'ボーカル分離モデル', '去混响 / 人声净化模型': '残響除去 / ボーカル浄化モデル',
  '分离后去混响 / 净化人声': '分離後に残響除去 / ボーカル浄化', '通用': '標準', '高质量': '高品質',
  '推理参数': '推論設定', '全参数手动调整': '全パラメータ手動調整', '已启用': '有効',
  '基础可调 · 高级默认': '基本調整可 · 詳細はデフォルト', '高级使用默认': '詳細設定はデフォルト',
  '变调': 'ピッチ変更', '变调（半音）': 'ピッチ変更（半音）', '共振峰偏移': 'フォルマントシフト',
  '共振峰偏移（半音）': 'フォルマントシフト（半音）', '参考音频': '参照音声', '目标音色参考音频': '目標音色の参照音声',
  '说话人': '話者', '目标说话人 / 音色 ID': '対象話者 / 音色ID', '设备': 'デバイス', '推理设备': '推論デバイス',
  '版本': 'バージョン', '模型版本': 'モデルバージョン', 'RVC 模型版本': 'RVCモデルバージョン', 'F0 提取算法': 'F0抽出方式',
  'F0 算法': 'F0方式', 'F0 过滤阈值': 'F0フィルターしきい値', 'F0 中值滤波半径': 'F0メディアン半径',
  '索引比率': 'インデックス率', '检索比率': 'インデックス率', '检索率': 'インデックス率', '响度包络融合': '音量包絡ミックス',
  '清辅音保护': '子音保護', '清辅音保护 (protect)': '子音保護 (protect)', '滤波半径': 'フィルター半径',
  '自动高音保护': '高音自動保護', '高音保护': '高音保護', '高音保护轮次': '保護回数',
  '选择性降调/复原，减少高音失真': '選択的なピッチ下降と復元で高音の歪みを低減',
  '轮次为 0 时由系统自动接管': '0の場合はシステムが自動管理',
  '轮次为 0 时由系统自动接管，行为与普通模式一致': '0の場合は通常モードと同様にシステムが自動管理します',
  '每轮失败后会根据实际哑音位置自动降低内部保护起点': '失敗ごとに検出位置に応じて保護しきい値を自動調整します',
  '处理流程': '処理フロー', '输出预览': '出力プレビュー', '失败原因': '失敗の詳細', '推理失败，请查看日志': '推論に失敗しました。ログを確認してください',
  '队列': 'キュー', '等待': '待機中', '处理中': '処理中', '正在处理': '処理中', '完成': '完了', '失败': '失敗',
  '取消': 'キャンセル', '保存': '保存', '确认': '確認', '删除': '削除', '编辑': '編集', '重试': '再試行',
  '刷新': '更新', '重置': 'リセット', '清除': 'クリア', '移除': '削除', '关闭': '閉じる', '打开': '開く',
  '搜索': '検索', '下载': 'ダウンロード', '上传': 'アップロード', '导入': 'インポート', '导出': 'エクスポート', '使用': '使用',
  '更换': '変更', '选择': '選択', '添加': '追加', '创建': '作成', '复制': 'コピー', '粘贴': '貼り付け',
  '开始': '開始', '结束': '終了', '暂停': '一時停止', '继续': '再開', '停止': '停止', '预览': 'プレビュー',
  '基础层': '基本', '高级层': '高度', '基础增强': '基本強化', '高级增强': '高度な強化',
  '增强参数': '強化設定', '增强任务': '強化タスク', '增强目标': '強化対象', '增强层级': '強化レベル',
  '选择增强目标': '強化対象を選択', '提供原始歌曲': '原曲を指定', '原始歌曲': '原曲', '本地文件': 'ローカルファイル',
  '当前原始歌曲': '現在の原曲', '创建翻唱': 'カバーを作成', '开始 AI 增强': 'AI強化を開始', '重新创建增强任务': '強化タスクを再作成',
  '播放增强成品': '強化結果を再生', '打开我的作品': 'マイ作品を開く', '返回 AI 翻唱': 'AIカバーへ戻る',
  '自然修音': '自然ピッチ補正', 'AI 对齐': 'AIアライメント', 'AI 角色共振峰': 'AIフォルマント調整', 'AI 响度包络': 'AI音量包絡',
  '播放源': '再生ソース', '系统音频变声器': 'システム音声ボイスチェンジャー', '歌曲文件实时播放': '楽曲ファイルのリアルタイム再生',
  '系统混合音频输入': 'システムミックス入力', '变声输出设备': '変換音声の出力先', '刷新设备': 'デバイスを更新',
  '演唱编排': '歌唱アレンジ', '实时参数': 'リアルタイム設定', '输出缓冲': '出力バッファ', '转换块': '変換チャンク',
  '转换人声': '変換ボーカル', '伴奏': '伴奏', '原始伴奏保持不变': '元の伴奏を維持', '启动实时翻唱': 'リアルタイムカバーを開始',
  '实时工程运行中': 'リアルタイム処理中', '系统音频': 'システム音声', '已处理音频': '処理済み音声', '转换缓冲': '変換バッファ',
  '实时处理倍率': 'リアルタイム処理倍率', '导出成品': '完成品を書き出す',
  '工程': 'プロジェクト', '工程文件 (.xbproject)': 'プロジェクトファイル (.xbproject)', '音轨': 'トラック', '片段': 'クリップ', '角色': 'ロール',
  '角色管理': 'ロール管理', '未关联模型': 'モデル未連携', '效果': 'エフェクト', '效果器': 'エフェクト', '插件窗口': 'プラグイン画面',
  '当前作用范围尚未添加效果': '現在の範囲にエフェクトはありません', '人声编辑': 'ボーカル編集', '局部重推理': '部分再推論',
  '选择一个片段': 'クリップを選択', '剪切': '分割', '静音切句': '無音で分割', '复制音轨': 'トラックを複製', '粘贴音频': '音声を貼り付け',
  '未导出': '未書き出し', '吸附': 'スナップ', '缩放': 'ズーム', '音量': '音量', '时间拉伸': 'タイムストレッチ',
  '淡入': 'フェードイン', '淡出': 'フェードアウト', '偏移': 'オフセット', '节点': 'ポイント', '音量包络': '音量エンベロープ',
  '新建音轨': '新規トラック', '时间轴模板': 'タイムラインテンプレート', '还没有角色': 'ロールはまだありません',
  '作品': '作品', '使用模型': '使用モデル', '时长': '長さ', '状态': '状態', '创建时间': '作成日時', '操作': '操作',
  '暂无作品': '作品はありません', '去创作': '作成する', '作品播放': '作品プレーヤー', '作品库': '作品一覧', '正在准备播放页面…': '再生画面を準備中…',
  '歌词': '歌詞', '未载入': '未読み込み', '未知歌手': '不明なアーティスト', '曲库设置': '楽曲ライブラリ設定',
  '找不到这首作品': '作品が見つかりません', '它可能已被删除，或仍在生成中。': '削除されたか、まだ生成中の可能性があります', '返回作品库': '作品一覧へ戻る',
  '尚未配置 API Key': 'API Keyが未設定です', '前往设置': '設定を開く', '搜索结果': '検索結果', '已下载素材': 'ダウンロード済み素材',
  '不可播放': '再生不可', '换个关键词试试吧': '別のキーワードをお試しください',
  '服务配置': 'サービス設定', '监听范围': '待受範囲', '仅本机': 'このPCのみ', '局域网': 'LAN', '监听端口': 'ポート',
  '绑定域名': 'ドメイン', '访问地址': 'アクセスURL', 'API 密钥': 'APIキー', '调用文档': 'APIガイド', '上传限制': 'アップロード制限',
  '外部访问': '外部アクセス', '异步任务': '非同期タスク', '永不过期': '無期限',
  '插件功能': 'プラグイン機能', '插件市场': 'プラグインマーケット', '刷新市场': 'マーケットを更新',
  '安装本地插件包': 'ローカルプラグインをインストール', '开发目录': '開発ディレクトリ', '已安装插件': 'インストール済みプラグイン',
  '插件运行中': 'プラグイン稼働中', '插件已暂停': 'プラグイン停止中', '官方': '公式', '市场': 'マーケット',
  '暂无说明': '説明なし', '未知作者': '作者不明', '安装': 'インストール', '仅索引': 'インデックスのみ', '卸载': 'アンインストール',
  '主题': 'テーマ', '自定义主题': 'カスタムテーマ', '背景与粒子': '背景とパーティクル', '添加背景': '背景を追加', '更换背景': '背景を変更',
  '背景遮罩': '背景オーバーレイ', '动态粒子': 'アニメーション粒子', '粒子数量': '粒子数', '粒子大小': '粒子サイズ',
  '恢复默认': 'デフォルトに戻す', '更换头像': 'アバターを変更', '昵称': 'ニックネーム', '消息': 'メッセージ',
  '消息通知': '通知', '全部已读': 'すべて既読', '暂无消息': '通知はありません', '传输任务': '転送タスク',
  '清除已完成': '完了済みをクリア', '暂无传输任务': '転送タスクはありません', '环境就绪': '準備完了', '降级模式': '制限モード',
  '正在检测集成工具…': '統合ツールを確認中…', 'WAV 无损': 'WAV ロスレス', 'FLAC 无损压缩': 'FLAC ロスレス',
  'MP3 通用格式': 'MP3 汎用', 'M4A 移动设备': 'M4A モバイル', '数据存储位置': 'データ保存場所', '已用': '使用済み',
  '所在磁盘可用': 'ディスク空き容量', '未知时间': '日時不明',
  '用你自己的': '自分の', 'SVC 模型': 'SVCモデル', '翻唱': 'でカバーを作成',
  '导入你的 SVC 歌声模型，上传一首歌，软件会自动用 Ultimate Vocal Remover 分离人声、用 ffmpeg 处理音频，数十秒生成高保真翻唱作品。': 'SVC歌声モデルを読み込み、楽曲をアップロードすると、Ultimate Vocal Removerでボーカルを分離し、ffmpegで処理して高品質なカバーを生成します。',
  '上传歌曲开始': '楽曲をアップロード', '打开目录': 'フォルダーを開く', '选择目录': 'フォルダーを選択', '迁移数据': 'データを移動',
  '已导入模型': 'インポート済みモデル', '已完成': '完了', '运行环境就绪': '実行環境準備完了', '部分工具降级': '一部ツールが制限中',
  '全部模型': 'すべてのモデル', '配置文件': '設定ファイル', '.pth / .onnx + 配置文件': '.pth / .onnx + 設定ファイル', '模型管理': 'モデル管理', '试听': '試聴', '尚未完成': '未完了',
  '选择格式下载': '形式を選んでダウンロード', '更多': 'その他', '重命名': '名前を変更', '重新生成': '再生成', '查看日志': 'ログを表示',
  '在「我的作品」中查看': 'マイ作品で表示', '还没有作品，去「AI 翻唱」生成第一首吧。': '作品はまだありません。AIカバーで最初の作品を作成しましょう。',
  '加载 SVC 模型，一键换声生成翻唱': 'SVCモデルを読み込み、ワンクリックでカバーを生成', '人声分离': 'ボーカル分離',
  '由 Ultimate Vocal Remover 提取干声与伴奏': 'Ultimate Vocal Removerでボーカルと伴奏を抽出',
  '管理 .pth / .onnx 的 SVC 歌声模型': '.pth / .onnx のSVC歌声モデルを管理', '从本地导入新的 SVC 歌声模型': 'ローカルからSVC歌声モデルをインポート',
  '首页 · 01': 'ホーム · 01', '首页 · 02': 'ホーム · 02',
  '翻唱工作台 · 03': 'AIカバー · 03', '翻唱工作台 · 04': 'AIカバー · 04', '翻唱工作台 · 05': 'AIカバー · 05',
  '前期人声处理 · 06': 'ボーカル前処理 · 06', '前期人声处理 · 07': 'ボーカル前処理 · 07',
  '翻唱工作台 · 08': 'AIカバー · 08', '单模型推理 · 09': '単一モデル推論 · 09', '单模型推理 · 10': '単一モデル推論 · 10',
  '从这里开始一次完整翻唱': 'ここからカバー制作を開始', '正在查看 · AI 翻唱快捷入口': '表示中 · AIカバーショートカット',
  'AI 翻唱工作台负责导入歌曲、选择音色、设置推理并生成作品。点击快捷入口进入空白工作台；从首页拖入音频则会把该文件一并带入。': 'AIカバースタジオでは、楽曲の読み込み、音色選択、推論設定、作品生成を行います。ショートカットから空のスタジオを開くか、ホームに音声をドロップしてファイルを引き継げます。',
  '点击卡片': 'カードをクリック', '进入空白工作台': '空のスタジオを開く', '拖拽音频': '音声をドロップ', '自动跳转并预填这首歌': 'この楽曲を設定してスタジオを開く',
  '拖入音频会自动带入翻唱': 'ドロップした音声をスタジオへ引き継ぐ', '首页音频拖拽区': 'ホームの音声ドロップ領域',
  '把歌曲拖到首页这个区域，软件会校验格式，然后跳转到 AI 翻唱并显示刚才的文件。直接点击区域仍然只是打开空白工作台。': 'ここに楽曲をドロップすると形式を確認し、ファイルを選択した状態でAIカバーを開きます。クリックだけの場合は空のスタジオを開きます。',
  '格式': '形式', '大小': 'サイズ', '不设固定大小上限': '固定サイズ上限なし',
  '先决定整首歌还是逐句分配': '全曲1音色かフレーズ割り当てかを選択', '单模型 / 多模型模式': '単一 / 複数モデルモード',
  '单模型适合整首歌保持一个音色，步骤少、最容易成功。多模型会显示歌词时间轴，可以按句选择不同音色，也可以多选形成合唱。': '単一モデルは全曲で同じ音色を使う最も簡単な方法です。複数モデルでは歌詞タイムラインでフレーズごとに音色を割り当て、コーラスも作成できます。',
  '单模型': '単一モデル', '多模型': '複数モデル', '整首统一音色，适合快速生成': '全曲を同じ音色で素早く生成',
  '逐句分配模型，适合角色切换与和声': 'フレーズごとに割り当て、役割切替やハモリに最適', '切换': '切替', '已填写的歌曲与常用参数会保留': '楽曲と基本設定は保持されます',
  '点击选择或拖拽歌曲': 'クリックまたは楽曲をドロップ', '歌曲导入区': '楽曲インポート領域',
  '工作台的导入区与首页行为一致。你可以点击选择本地文件，也可以直接拖入；已下载的曲库素材会列在下方，一键即可使用。': 'スタジオのインポート領域はホームと同じです。ローカルファイルを選択またはドロップでき、ダウンロード済み素材も下から再利用できます。',
  '桌面端选择路径，网页端读取文件': 'デスクトップではパスを選択し、ブラウザーではファイルを読み込み', '从资源获取页下载的歌曲可直接复用': '素材取得でダウンロードした楽曲を直接再利用',
  '导入后先确认歌曲和时长再推理': 'インポート後に楽曲と長さを確認してから推論',
  '先选择需要的工作流': '必要なワークフローを選択', '高级功能开关': '高度な機能スイッチ',
  '这里集中放置前期处理和歌声增强等工作流。普通用户可以保持默认关闭；需要更细的声音处理时再进入对应模块。': '前処理や歌声強化のワークフローをここで選択します。通常はオフのままで、細かな処理が必要な場合のみ有効にできます。',
  '前期处理': '前処理', '先分离人声、去混响，再送进模型': 'ボーカル分離と残響除去後にモデルへ送る', '歌声增强': '歌声強化',
  '生成前做自然修音与动态处理': '生成前に自然なピッチ補正とダイナミクス処理', '普通流程': '標準フロー', '不打开高级功能也可以直接生成': '高度な機能なしでも直接生成可能',
  '在推理前清理输入人声': '推論前に入力ボーカルを整理',
  '打开前期处理后，软件会先把歌曲拆成人声和伴奏。干净的人声能减少伴奏串音，让后面的音高检测和音色转换更稳定。': '前処理を有効にすると、楽曲をボーカルと伴奏に分離します。クリーンなボーカルは伴奏の混入を減らし、ピッチ検出と音色変換を安定させます。',
  '开启': 'オン', '直接使用原始音频，速度最快': '元の音声をそのまま使い最速で処理', '先分离再进入翻唱流水线': '分離してからカバーフローへ',
  '注意': '注意', '处理本身会增加耗时，先试听结果再决定': '処理時間が増えるため、結果を試聴して判断してください',
  '按环境选择 UVR 或 PyMSS': '環境に合わせてUVRまたはPyMSSを選択', '分离引擎选择': '分離エンジン選択',
  'UVR 适合已有本地环境的快速分离；PyMSS 可以使用已下载的专用分离或去混响模型。先选引擎，再选具体模型，状态提示会告诉你是否可用。': 'UVRはローカルでの高速分離に適し、PyMSSは専用の分離・残響除去モデルを使用できます。エンジンとモデルを選ぶと状態が表示されます。',
  '可下载人声分离与去混响模型': 'ボーカル分離・残響除去モデルをダウンロード可能', '去混响': '残響除去', '可额外开启，改善房间声和尾音': '追加で有効にし、部屋鳴りや残響を改善',
  '选择适合的音色模型': '適切な音色モデルを選択', '模型选择区': 'モデル選択領域',
  '模型卡片会显示框架、采样率和类型。先按框架筛选，再点击模型。模型的音域配置会参与高音保护，不同模型不会共用一个固定阈值。': 'モデルカードには方式、サンプルレート、種類が表示されます。方式で絞り込み、モデルを選択します。高音保護には各モデル固有の音域設定を使用します。',
  '筛选': 'フィルター', '按 So-VITS-SVC、RVC、SeedVC、DDSP-SVC 等框架过滤': 'So-VITS-SVC、RVC、SeedVC、DDSP-SVCなどで絞り込み',
  '点击一张卡片作为整首歌曲的音色': '1枚のカードを全曲の音色として選択', '勾选多张卡片后按歌词分配': '複数カードを選び、歌詞フレーズごとに割り当て',
  '默认模式先调常用参数': 'まず基本設定を調整', '推理参数面板': '推論設定パネル',
  '关闭全参数时，变调、F0 算法、设备、检索率、响度混合、保护、滤波半径等常用参数仍然可调。软件默认值保持原有推理效果，隐藏的高级值不会污染本次运行。': '全パラメータをオフにしても、ピッチ、F0方式、デバイス、インデックス率、音量ミックス、保護、フィルター半径は調整できます。非表示の高度な値は今回の推論に影響しません。',
  '按男女声或歌曲音域做半音级调整': '声種や楽曲音域に合わせて半音単位で調整', 'F0 / 设备': 'F0 / デバイス', '选择音高算法和 CPU / GPU 推理设备': 'ピッチ方式とCPU / GPUデバイスを選択',
  'RVC 参数': 'RVC設定', '检索率、响度混合、保护、滤波半径、版本': 'インデックス率、音量ミックス、保護、フィルター半径、バージョン',
  '理解主模型和浅扩散的分工': 'メインモデルと拡散モデルの役割', '主模型 / 扩散模型比例': 'メイン / 拡散モデル比率',
  '这个比例决定主模型路径与浅扩散路径对成品的贡献。它不是“越大越好”，而是速度、音色稳定性、细节、显存之间的取舍。': 'この比率はメインモデルと浅い拡散経路の寄与を決めます。大きいほど良いわけではなく、速度、音色安定性、細部、GPUメモリのバランスです。',
  '主模型高': 'メインモデル寄り', '速度快、音色轮廓稳定、显存压力较小': '高速で音色が安定し、GPUメモリ使用量が少ない',
  '浅扩散高': '拡散モデル寄り', '细节与自然度通常更丰富，但更慢且更吃显存': '細部と自然さが増す一方、低速でGPUメモリを多く使用', '调法': '調整方法',
  '先用默认值，出现毛刺或细节不足时小步调整': 'まずデフォルトを使い、ノイズや細部不足がある場合に少しずつ調整', '跳过引导': 'ガイドをスキップ', '下一步': '次へ',
}

const phraseTables: Record<AppLocale, Record<string, string>> = {
  'zh-CN': {},
  'en-US': enPhrases,
  'ja-JP': jaPhrases,
}

function detectLocale(): AppLocale {
  if (typeof localStorage !== 'undefined') {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'zh-CN' || stored === 'en-US' || stored === 'ja-JP') return stored
  }
  const browser = typeof navigator === 'undefined' ? '' : navigator.language.toLowerCase()
  if (browser.startsWith('ja')) return 'ja-JP'
  if (browser.startsWith('en')) return 'en-US'
  return 'zh-CN'
}

const currentLocale = ref<AppLocale>(detectLocale())

function interpolate(text: string, params: Record<string, string | number> = {}) {
  return text.replace(/\{(\w+)\}/g, (_match, key: string) => String(params[key] ?? `{${key}}`))
}

export function translate(
  key: MessageKey,
  params: Record<string, string | number> = {},
): string {
  const table = messages[currentLocale.value] as Record<MessageKey, string>
  return interpolate(table[key] ?? messages['zh-CN'][key] ?? key, params)
}

function translateExact(source: string, targetLocale = currentLocale.value): string {
  if (targetLocale === 'zh-CN' || !source) return source
  const table = phraseTables[targetLocale]
  const direct = table[source]
  if (direct) return direct
  const dynamic = translateDynamicPhrase(source, targetLocale)
  if (dynamic) return dynamic
  if (source.startsWith('// ')) {
    const translated = table[source.slice(3)]
    if (translated) return `// ${translated}`
  }
  return source
}

export function translateUiText(source: string, targetLocale = currentLocale.value): string {
  const match = source.match(/^(\s*)(.*?)(\s*)$/s)
  if (!match) return source
  return `${match[1] ?? ''}${translateExact(match[2] ?? '', targetLocale)}${match[3] ?? ''}`
}

export function setLocale(next: AppLocale) {
  if (!localeOptions.some((item) => item.value === next)) return
  currentLocale.value = next
}

export function applyStoredLocaleBeforeMount() {
  applyLocaleToDocument(currentLocale.value)
}

function applyLocaleToDocument(next: AppLocale) {
  if (typeof document === 'undefined') return
  document.documentElement.lang = next
  document.documentElement.dataset.locale = next
  document.title = next === 'en-US' ? 'XB-SVCB · AI Cover Studio' : next === 'ja-JP' ? 'XB-SVCB · AIカバースタジオ' : 'XB-SVCB · AI 翻唱工作台'
}

const originalText = new WeakMap<Text, string>()
const originalAttributes = new WeakMap<Element, Map<string, string>>()
const localizedAttributes = ['title', 'placeholder', 'aria-label', 'data-empty-text'] as const

function skipped(element: Element | null) {
  return Boolean(element?.closest('script, style, code, pre, textarea, [contenteditable="true"], [data-i18n-skip]'))
}

function matchesKnownTranslation(source: string, rendered: string) {
  return (['zh-CN', 'en-US', 'ja-JP'] as AppLocale[]).some(
    (candidate) => translateUiText(source, candidate) === rendered,
  )
}

function localizeTextNode(node: Text) {
  if (skipped(node.parentElement)) return
  const rendered = node.data
  let source = originalText.get(node)
  if (source === undefined || !matchesKnownTranslation(source, rendered)) {
    source = rendered
    originalText.set(node, source)
  }
  const translated = translateUiText(source)
  if (translated !== rendered) node.data = translated
}

function localizeElement(element: Element) {
  if (skipped(element)) return
  let sourceMap = originalAttributes.get(element)
  if (!sourceMap) {
    sourceMap = new Map()
    originalAttributes.set(element, sourceMap)
  }
  for (const name of localizedAttributes) {
    const rendered = element.getAttribute(name)
    if (rendered === null) continue
    let source = sourceMap.get(name)
    if (source === undefined || !matchesKnownTranslation(source, rendered)) {
      source = rendered
      sourceMap.set(name, source)
    }
    const translated = translateUiText(source)
    if (translated !== rendered) element.setAttribute(name, translated)
  }
}

function localizeTree(root: Node) {
  if (root instanceof Text) {
    localizeTextNode(root)
    return
  }
  if (!(root instanceof Element)) return
  localizeElement(root)
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT)
  let node = walker.nextNode()
  while (node) {
    if (node instanceof Text) localizeTextNode(node)
    else if (node instanceof Element) localizeElement(node)
    node = walker.nextNode()
  }
}

let observer: MutationObserver | null = null

export function startDomLocalization() {
  if (typeof document === 'undefined' || observer) return
  localizeTree(document.body)
  observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === 'characterData') localizeTree(mutation.target)
      if (mutation.type === 'attributes' && mutation.target instanceof Element) localizeElement(mutation.target)
      for (const node of mutation.addedNodes) localizeTree(node)
    }
  })
  observer.observe(document.body, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: [...localizedAttributes],
  })
}

watch(currentLocale, (next) => {
  if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, next)
  applyLocaleToDocument(next)
  if (typeof document !== 'undefined') queueMicrotask(() => localizeTree(document.body))
})

export function useI18n() {
  const activeOption = computed(
    () => localeOptions.find((item) => item.value === currentLocale.value) ?? localeOptions[0]!,
  )
  return {
    locale: readonly(currentLocale),
    activeOption,
    options: localeOptions,
    setLocale,
    t: translate,
  }
}
