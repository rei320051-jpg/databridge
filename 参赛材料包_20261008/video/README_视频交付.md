# 演示视频交付

录制依据为本目录两份已审核分镜。用户以“那你继续”确认继续录制；历史分镜文件保持原样，不为更新审核标记而改写已经跟踪的文件。

## 提交文件

| 作品 | 软字幕版 | 硬字幕版 | 外挂字幕 | 计划时长 |
| --- | --- | --- | --- | --- |
| 数桥 DataBridge 产品演示 | `赛题二_演示视频_软字幕.mp4` | `赛题二_演示视频_硬字幕.mp4` | `赛题二_演示视频.srt` | 270 秒 |
| DataClawHub 平台运营方案 | `赛题一_演示视频_软字幕.mp4` | `赛题一_演示视频_硬字幕.mp4` | `赛题一_演示视频.srt` | 285 秒 |

播放兼容性优先时用硬字幕版。软字幕版含中文 `mov_text` 字幕轨；播放器若没有默认显示字幕，请选择中文字幕轨，或加载同名 SRT。

## 事实与状态边界

- 主办方口径：数联科技 × 华东师范大学（阿里云赛事冠名赞助）。
- 赛题二录屏始终使用 `rules` 模式，连接正式 `demo-v1.1` 模拟数据。金额来自真实接口及页面明细，不代表真实经营。
- 查询计划和 SQL 可在 `query_trace_evidence.json` 中复核；该执行层响应金额单位为“分”，页面按响应中的换算规则显示“元”。精确结果镜头放大原界面的明细，而不是伪造页面 KPI。
- 业务题验收与真实模型复测成绩来自归档报告。模型复测并非本次现场调用；确定性 Text-to-SQL 对照也不冒充真实模型实验。
- 赛题一展示已有方案、当前线上物料、归档实拍和空白模板。邀请码、制品上架、全链路走查及增长数据仍待真实执行，视频不代填成果。

## 实际技术路线

- Playwright + 本机 Edge（`msedge`），使用独立无头浏览器会话，不操作用户已登录的浏览器标签页。
- 每 100ms 截图，逐镜编码，再由 ffmpeg 拼接。最终输出 1920×1080、H.264 视频和 AAC 音频。
- 在线 `edge-tts` 出现连接/无音频返回故障，统一使用 Windows 中文 SAPI 兜底；每条配音归一化并置入分镜累计时间轴，音色与时间同步保持一致。
- ffmpeg 经 winget 安装到系统用户目录。没有将工具二进制或字体复制到仓库；现有 requirements 文件未修改。
- `验收报告.json` 记录时长、编码、分辨率、声音强度、字幕轨、字幕抽样时间和文件哈希。`qa/` 保存最终字幕抽查图片。

## 可复现脚本

使用分镜记录的同一个解释器，在仓库根目录运行以下命令。不要使用另一个环境或改写 requirements：

```powershell
$videoPython = (Resolve-Path '赛题二/.venv/Scripts/python.exe').Path
$env:PYTHONDONTWRITEBYTECODE = '1'
& $videoPython '参赛材料包_20261008/video/video_pipeline.py' start
& $videoPython '参赛材料包_20261008/video/video_pipeline.py' preflight
& $videoPython '参赛材料包_20261008/video/video_pipeline.py' subtitles
& $videoPython '参赛材料包_20261008/video/video_pipeline.py' narrate
& $videoPython '参赛材料包_20261008/video/video_pipeline.py' record --video 赛题二
& $videoPython '参赛材料包_20261008/video/video_pipeline.py' record --video 赛题一
& $videoPython '参赛材料包_20261008/video/video_pipeline.py' compose --video 赛题二
& $videoPython '参赛材料包_20261008/video/video_pipeline.py' compose --video 赛题一
& $videoPython '参赛材料包_20261008/video/video_pipeline.py' check
```

命令会生成或覆盖本目录视频产物；请在要重录时使用，不要与正在运行的录制进程重复启动。已上传的原始分镜和仓库源代码均不修改。

所有截图序列、单镜编码、临时 HTML、查询日志与原始 WAV 都留在本目录内，仅作为本地录制中间件，不纳入 Git。GitHub 交付六个成片文件及分镜、脚本、复核证据与验收报告；不提交工具二进制、海量帧或重复音频中间件。
