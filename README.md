# Meeting Translator - 实时会议翻译系统

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

**从"茶壶里装汤圆"到流畅对话：打造零延迟实时会议翻译系统**

一个真正零延迟、双向实时、完全本地化、与会议软件无关的翻译系统。

---

## 核心亮点

- 🎯 **完全本地运行**：只在你的电脑上，其他参会者无感知，不需要任何配合
- 🌐 **会议软件无关**：支持 Zoom、Teams、Google Meet、腾讯会议等所有会议平台
- ⚡ **真正零延迟**：<500ms 端到端延迟，不打断对话节奏
- 🔄 **模型无关架构**：可随时切换更好的翻译服务
- 🎭 **虚拟化身模式**：通过"Mike"这样的虚拟角色，让资深专家用中文自信表达

---

## 功能特性

### 双模式实时翻译

**说模式（Speak Mode）：**
- 捕获你的麦克风输入（中文）
- 实时翻译成英文
- 发送到虚拟麦克风 → 会议中所有人听到英文
- **延迟 <500ms**

**听模式（Listen Mode）：**
- 捕获系统音频（会议中其他人说的英语）
- 实时翻译成中文
- **屏幕上显示中文字幕**（考虑到中国用户习惯看字幕）
- **延迟 <300ms**（无TTS环节，更快）

**多人会议支持：**
- 无论会议中有多少人，系统都能正常工作
- 所有参会者完全不知道你在使用翻译

---

## 演示视频

📺 查看完整演示和技术细节：[Meeting Translator 项目分享](https://www.superlinear.academy/c/share-your-projects/f2e629)

---

## 快速开始

### 前置要求

1. **操作系统**: Windows 10/11, macOS
2. **Python**: 3.9 - 3.11
3. **虚拟音频设备**:
   - Windows: [Voicemeeter](https://voicemeeter.com/)
   - macOS: BlackHole
4. **API Key**: 阿里云 DashScope API（[申请地址](https://dashscope.console.aliyun.com/)）

### 安装步骤

#### 1. 克隆仓库

```bash
git clone https://github.com/eerenyuan/meeting_translator.git
cd meeting_translator
```

#### 2. 创建虚拟环境

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS
source .venv/bin/activate
```

#### 3. 安装依赖

```bash
pip install -r requirements.txt
```

> **注意**: PyAudio 在 Windows 上可能需要手动安装：
> ```bash
> pip install pipwin
> pipwin install pyaudio
> ```

#### 4. 安装虚拟音频驱动

**Windows用户：**

下载并安装 [Voicemeeter](https://voicemeeter.com/)（推荐 Voicemeeter Banana 或 Potato 版本），安装后重启电脑。

**macOS用户：**

```bash
brew install portaudio blackhole-2ch
```

#### 5. 配置环境变量

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env 文件，填入你的 API Key
# DASHSCOPE_API_KEY=your_api_key_here
```

#### 6. 运行程序

**Windows**:
```bash
# 方法1: 使用批处理文件（推荐）
run.bat

# 方法2: 手动运行
cd meeting_translator && python main_app.py
```

**macOS**:
```bash
cd meeting_translator && python main_app.py
```

---

## 使用指南

### 基本使用

1. **启动程序**

   **Windows**:
   ```bash
   # 方法1: 使用批处理文件（推荐）
   run.bat

   # 方法2: 手动运行
   cd meeting_translator && python main_app.py
   ```

   **macOS**:
   ```bash
   cd meeting_translator && python main_app.py
   ```

2. **选择模式**
   - 按 `F1` 切换到"说模式"（中译英）
   - 按 `F2` 切换到"听模式"（英译中）

3. **设置会议软件**
   - 在会议软件中选择**"Voicemeeter Input"**（或 "VoiceMeeter Input"）作为麦克风
   - 系统音频输出设置为 "Voicemeeter Input"

4. **开始会议**
   - 说模式：直接说中文，对方听到英文
   - 听模式：看屏幕字幕，实时理解对方说的英文

### 高级功能

#### 自定义术语库

编辑 `meeting_translator/glossary.json` 添加专业术语：

```json
{
  "description": "Translation glossary for meeting translator",
  "glossary": {
    "产品A": "Product A",
    "业务系统": "Business System",
    "你的公司名": "Your Company Name",
    "张总": "Mr. Zhang"
  }
}
```

详细说明请查看：[词汇表使用指南](docs/GLOSSARY_GUIDE.md)

---

## 技术架构

### 核心技术

- **虚拟音频劫持**：在操作系统音频层面工作，与会议软件解耦
- **流式翻译API**：端到端实时处理，延迟极低
- **服务端VAD**：自动检测语音活动，优化断句
- **多模态输出**：说模式输出语音，听模式输出字幕

### 系统要求

| 组件 | 要求 |
|------|------|
| CPU | 双核以上 |
| 内存 | 4GB+ |
| 网络 | 稳定网络连接 |
| 音频设备 | 麦克风、扬声器 |

---

## 常见问题

### 1. 听不到翻译的英文语音？

**问题**: 说模式下，对方听不到我的翻译。

**解决方案**:
- 确认会议软件的麦克风设置为 "Voicemeeter Input"
- 检查 Voicemeeter 是否正在运行
- 重启程序和会议软件

### 2. 字幕不显示？

**问题**: 听模式下，看不到中文字幕。

**解决方案**:
- 确认字幕窗口没有被最小化
- 检查系统音频输出是否正常
- 查看控制台是否有错误信息

### 3. 延迟太高？

**解决方案**:
- 检查网络连接质量
- 降低 VAD 阈值（在 .env 中设置）
- 确认没有其他程序占用大量带宽

更多问题请查看：[完整 FAQ](docs/FAQ.md)

---

## 项目结构

```
meeting_translator/
├── meeting_translator/       # 核心程序
│   ├── main_app.py          # 主程序入口
│   ├── translation_service.py   # 翻译服务
│   ├── audio_capture_thread.py  # 音频捕获
│   ├── audio_output_thread.py   # 音频输出
│   ├── subtitle_window.py   # 字幕窗口
│   ├── glossary.json        # 术语库
│   └── styles/              # UI样式
├── docs/                    # 文档
├── .env.example             # 配置模板
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 贡献指南

欢迎贡献代码、报告问题或提出建议！

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的修改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 Pull Request

---

## 致谢

- 感谢阿里云通义千问团队提供的实时翻译API
- 感谢 VB-Audio 提供的 Voicemeeter 虚拟音频设备

---

## 联系方式

- **作者**: Ren Yuan
- **GitHub**: [@eerenyuan](https://github.com/eerenyuan)
- **项目地址**: [https://github.com/eerenyuan/meeting_translator](https://github.com/eerenyuan/meeting_translator)

---

**如果这个项目对你有帮助，请给个⭐️ Star支持一下！**
