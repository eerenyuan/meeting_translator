# Meeting Translator - 实时会议翻译系统

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

**[中文](#中文) | [English](#english)**

---

<a name="中文"></a>

## 中文

**从"茶壶里装汤圆"到流畅对话：打造零延迟实时会议翻译系统**

一个真正零延迟、双向实时、完全本地化、与会议软件无关的翻译系统。

### 核心亮点

- 🎯 **完全本地运行**：只在你的电脑上，其他参会者无感知，不需要任何配合
- 🌐 **会议软件无关**：支持 Zoom、Teams、Google Meet、腾讯会议等所有会议平台
- ⚡ **真正零延迟**：<500ms 端到端延迟，不打断对话节奏
- 🔄 **多提供商支持**：支持阿里云、OpenAI 等多个翻译服务，可随时切换
- 🎭 **虚拟化身模式**：通过"Mike"这样的虚拟角色，让资深专家用中文自信表达
- 🌍 **多语言界面**：支持中文和英文界面，可在配置文件中切换

### 功能特性

#### 双模式实时翻译

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

### 演示视频

📺 查看完整演示和技术细节：[Meeting Translator 项目分享](https://www.superlinear.academy/c/share-your-projects/f2e629)

### 快速开始

#### 前置要求

1. **操作系统**: Windows 10/11, macOS
2. **Python**: 3.9 - 3.11
3. **虚拟音频设备**:
   - Windows: [Voicemeeter](https://voicemeeter.com/)
   - macOS: BlackHole
4. **翻译服务 API Key** (选择其一):
   - **阿里云 DashScope** (默认): [申请地址](https://dashscope.console.aliyun.com/)
   - **OpenAI Realtime API**: [申请地址](https://platform.openai.com/api-keys)

#### 安装步骤

##### 1. 克隆仓库

```bash
git clone https://github.com/eerenyuan/meeting_translator.git
cd meeting_translator
```

##### 2. 创建虚拟环境

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS
source .venv/bin/activate
```

##### 3. 安装依赖

```bash
pip install -r requirements.txt
```

> **注意**: PyAudio 在 Windows 上可能需要手动安装：
> ```bash
> pip install pipwin
> pipwin install pyaudio
> ```

##### 4. 安装虚拟音频驱动

**Windows用户：**

下载并安装 [Voicemeeter](https://voicemeeter.com/)（推荐 Voicemeeter Banana 或 Potato 版本），安装后重启电脑。

**macOS用户：**

```bash
brew install portaudio blackhole-2ch
```

##### 5. 配置环境变量

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env 文件，配置翻译服务提供商和 API Key
```

**使用阿里云（默认）：**
```bash
TRANSLATION_PROVIDER=aliyun
DASHSCOPE_API_KEY=your_dashscope_api_key_here
```

**使用 OpenAI：**
```bash
TRANSLATION_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
```

##### 6. 配置界面语言（可选）

编辑配置文件 `~/Documents/meeting_translator/config/config.json`：

```json
{
  "lang": "zh_CN"  // 中文界面（默认）
  // 或
  "lang": "en_US"  // 英文界面
}
```

支持的语言代码：
- `zh_CN` 或 `zh` 或 `cn` - 中文
- `en_US` 或 `en` - 英文

> **注意**: 首次运行后会自动创建配置文件，默认为中文界面。

##### 7. 运行程序

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

### 使用 UV（推荐用于 Git Worktrees）

**UV** 是现代 Python 包管理器，提供自动环境管理和依赖安装，特别适合使用 git worktree 的多分支开发场景。

#### 为什么使用 UV？

- ✅ **无需手动激活虚拟环境** - 自动管理 Python 环境
- ✅ **Git Worktree 友好** - 多个工作树共享依赖缓存，无需重复安装
- ✅ **一键运行** - `uv run main.py` 即可启动
- ✅ **跨平台支持** - Windows、macOS、Linux 统一体验
- ✅ **更快的依赖安装** - 并行安装，缓存友好

#### 安装 UV

**macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**或使用 pip:**
```bash
pip install uv
```

#### 使用 UV 运行程序

##### 方法 1: 使用 uv run（推荐）

```bash
# 从仓库根目录直接运行
uv run main.py
```

首次运行时，UV 会：
1. 自动检测 Python 版本（根据 `.python-version`）
2. 创建虚拟环境
3. 安装所有依赖
4. 启动应用程序

后续运行会重用已安装的环境，秒启动！

##### 方法 2: 使用启动脚本

**macOS/Linux:**
```bash
./run.sh
```

**Windows:**
```bash
run.bat
```

启动脚本会自动检查：
- ✓ `.env` 配置文件是否存在
- ✓ `uv` 是否已安装
- ✓ 提供友好的错误提示

### 使用指南

#### 基本使用

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

#### 高级功能

##### 切换翻译服务提供商

系统支持多个翻译服务提供商，可通过配置文件轻松切换：

| 提供商 | 特点 | 配置方式 |
|--------|------|---------|
| **阿里云 DashScope** | 默认，针对中英互译优化 | `TRANSLATION_PROVIDER=aliyun` |
| **OpenAI Realtime API** | GPT-realtime 驱动，支持多语言 | `TRANSLATION_PROVIDER=openai` |

**切换步骤：**
1. 编辑 `.env` 文件
2. 修改 `TRANSLATION_PROVIDER` 设置
3. 配置对应的 API Key
4. 重启程序

> 注意：不同提供商支持的语音选项不同，切换后请在界面中选择合适的语音。

##### 自定义术语库

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

### 技术架构

#### 核心技术

- **虚拟音频劫持**：在操作系统音频层面工作，与会议软件解耦
- **流式翻译API**：端到端实时处理，延迟极低
- **服务端VAD**：自动检测语音活动，优化断句
- **多模态输出**：说模式输出语音，听模式输出字幕

#### 系统要求

| 组件 | 要求 |
|------|------|
| CPU | 双核以上 |
| 内存 | 4GB+ |
| 网络 | 稳定网络连接 |
| 音频设备 | 麦克风、扬声器 |

### 常见问题

#### 1. 听不到翻译的英文语音？

**问题**: 说模式下，对方听不到我的翻译。

**解决方案**:
- 确认会议软件的麦克风设置为 "Voicemeeter Input"
- 检查 Voicemeeter 是否正在运行
- 重启程序和会议软件

#### 2. 字幕不显示？

**问题**: 听模式下，看不到中文字幕。

**解决方案**:
- 确认字幕窗口没有被最小化
- 检查系统音频输出是否正常
- 查看控制台是否有错误信息

#### 3. 延迟太高？

**解决方案**:
- 检查网络连接质量
- 降低 VAD 阈值（在 .env 中设置）
- 确认没有其他程序占用大量带宽

#### 4. 如何切换界面语言？

**解决方案**:
- 编辑配置文件 `~/Documents/meeting_translator/config/config.json`
- 修改 `"lang"` 字段为 `"zh_CN"`（中文）或 `"en_US"`（英文）
- 重启应用程序

更多问题请查看：[完整 FAQ](docs/FAQ.md)

### 已知问题

#### OpenAI 提供商的 LLM 提示词解析问题

**现象**: 使用 OpenAI 作为翻译提供商时（特别是在说模式下），某些句子可能会被 LLM 误解为指令而不是待翻译的内容。

**示例**:
```
输入: 不要翻译这句话
预期翻译: Don't translate this sentence
实际输出: Understood. I won't translate that sentence. Please go ahead with what you'd like me to translate next.
```

**原因**: OpenAI Realtime API 使用 GPT 模型 + 提示词的方式进行翻译，而非专用的翻译模型。某些包含指令性语义的句子可能触发模型的对话模式。

**影响**:
- 主要影响说模式（Speak Mode）
- 偶发性问题，不是所有句子都会触发
- 正常对话内容通常不受影响

**建议**:
- 如果需要更稳定的翻译质量，建议使用阿里云提供商（`TRANSLATION_PROVIDER=aliyun`）
- 阿里云使用专用的翻译模型，不存在此问题

### 项目结构

```
meeting_translator/
├── meeting_translator/              # 核心程序
│   ├── main_app.py                 # 主程序入口
│   ├── translation_service.py      # 翻译服务封装
│   ├── translation_client_base.py  # 翻译客户端基类
│   ├── translation_client_factory.py # 客户端工厂
│   ├── qwen_client.py              # 阿里云客户端
│   ├── openai_client.py            # OpenAI 客户端
│   ├── doubao_client.py            # 豆包客户端
│   ├── audio_capture_thread.py     # 音频捕获
│   ├── audio_output_thread.py      # 音频输出
│   ├── subtitle_window.py          # 字幕窗口
│   ├── i18n.py                     # 国际化管理
│   ├── locales/                    # 翻译文件
│   │   ├── zh_CN.json             # 中文翻译
│   │   └── en_US.json             # 英文翻译
│   ├── glossary.json               # 术语库
│   └── styles/                     # UI样式
├── docs/                           # 文档
├── .env.example                    # 配置模板
├── .gitignore
├── requirements.txt
└── README.md
```

### 贡献指南

欢迎贡献代码、报告问题或提出建议！

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的修改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 Pull Request

### 致谢

- 感谢阿里云通义千问团队提供的实时翻译 API
- 感谢 OpenAI 提供的 Realtime API
- 感谢 VB-Audio 提供的 Voicemeeter 虚拟音频设备

### 联系方式

- **作者**: Ren Yuan
- **GitHub**: [@eerenyuan](https://github.com/eerenyuan)
- **项目地址**: [https://github.com/eerenyuan/meeting_translator](https://github.com/eerenyuan/meeting_translator)

**如果这个项目对你有帮助，请给个⭐️ Star支持一下！**

**[返回顶部](#meeting-translator---实时会议翻译系统) | [English](#english)**

---

<a name="english"></a>

## English

**From "Dumplings in a Teapot" to Fluent Conversations: Building a Zero-Latency Real-Time Meeting Translation System**

A truly zero-latency, bidirectional, fully local, meeting-software-agnostic translation system.

### Key Highlights

- 🎯 **Fully Local Operation**: Runs only on your computer, completely invisible to other meeting participants, no cooperation required
- 🌐 **Meeting Software Agnostic**: Supports all meeting platforms including Zoom, Teams, Google Meet, Tencent Meeting, etc.
- ⚡ **True Zero Latency**: <500ms end-to-end latency, doesn't interrupt conversation flow
- 🔄 **Multiple Provider Support**: Supports Alibaba Cloud, OpenAI, and other translation services, easily switchable
- 🎭 **Virtual Avatar Mode**: Express confidently in Chinese through virtual characters like "Mike"
- 🌍 **Multilingual Interface**: Supports Chinese and English interfaces, switchable in configuration

### Features

#### Dual-Mode Real-Time Translation

**Speak Mode (S2S):**
- Captures your microphone input (Chinese)
- Translates in real-time to English
- Outputs to virtual microphone → Everyone in the meeting hears English
- **Latency <500ms**

**Listen Mode (S2T):**
- Captures system audio (English spoken by others in the meeting)
- Translates in real-time to Chinese
- **Displays Chinese subtitles on screen** (considering Chinese users' habit of reading subtitles)
- **Latency <300ms** (faster without TTS stage)

**Multi-Participant Meeting Support:**
- Works normally regardless of the number of participants in the meeting
- All participants are completely unaware you're using translation

### Demo Video

📺 Watch full demo and technical details: [Meeting Translator Project Share](https://www.superlinear.academy/c/share-your-projects/f2e629)

### Quick Start

#### Prerequisites

1. **Operating System**: Windows 10/11, macOS
2. **Python**: 3.9 - 3.11
3. **Virtual Audio Device**:
   - Windows: [Voicemeeter](https://voicemeeter.com/)
   - macOS: BlackHole
4. **Translation Service API Key** (choose one):
   - **Alibaba Cloud DashScope** (default): [Apply here](https://dashscope.console.aliyun.com/)
   - **OpenAI Realtime API**: [Apply here](https://platform.openai.com/api-keys)

#### Installation Steps

##### 1. Clone the Repository

```bash
git clone https://github.com/eerenyuan/meeting_translator.git
cd meeting_translator
```

##### 2. Create Virtual Environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS
source .venv/bin/activate
```

##### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

> **Note**: PyAudio on Windows may require manual installation:
> ```bash
> pip install pipwin
> pipwin install pyaudio
> ```

##### 4. Install Virtual Audio Driver

**Windows Users:**

Download and install [Voicemeeter](https://voicemeeter.com/) (Voicemeeter Banana or Potato version recommended), restart your computer after installation.

**macOS Users:**

```bash
brew install portaudio blackhole-2ch
```

##### 5. Configure Environment Variables

```bash
# Copy configuration template
cp .env.example .env

# Edit .env file to configure translation service provider and API Key
```

**Using Alibaba Cloud (default):**
```bash
TRANSLATION_PROVIDER=aliyun
DASHSCOPE_API_KEY=your_dashscope_api_key_here
```

**Using OpenAI:**
```bash
TRANSLATION_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
```

##### 6. Configure Interface Language (Optional)

Edit the configuration file `~/Documents/meeting_translator/config/config.json`:

```json
{
  "lang": "zh_CN"  // Chinese interface (default)
  // or
  "lang": "en_US"  // English interface
}
```

Supported language codes:
- `zh_CN` or `zh` or `cn` - Chinese
- `en_US` or `en` - English

> **Note**: The configuration file will be created automatically after first run, defaulting to Chinese interface.

##### 7. Run the Program

**Windows**:
```bash
# Method 1: Using batch file (recommended)
run.bat

# Method 2: Manual run
cd meeting_translator && python main_app.py
```

**macOS**:
```bash
cd meeting_translator && python main_app.py
```

### Using UV (Recommended for Git Worktrees)

**UV** is a modern Python package manager that provides automatic environment management and dependency installation, especially suitable for multi-branch development scenarios using git worktree.

#### Why Use UV?

- ✅ **No Manual Virtual Environment Activation** - Automatically manages Python environments
- ✅ **Git Worktree Friendly** - Multiple worktrees share dependency cache, no duplicate installation
- ✅ **One-Click Run** - Just `uv run main.py`
- ✅ **Cross-Platform Support** - Unified experience on Windows, macOS, Linux
- ✅ **Faster Dependency Installation** - Parallel installation, cache-friendly

#### Installing UV

**macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Or using pip:**
```bash
pip install uv
```

#### Running with UV

##### Method 1: Using uv run (recommended)

```bash
# Run directly from repository root
uv run main.py
```

On first run, UV will:
1. Automatically detect Python version (based on `.python-version`)
2. Create virtual environment
3. Install all dependencies
4. Start the application

Subsequent runs will reuse the installed environment, instant startup!

##### Method 2: Using Startup Scripts

**macOS/Linux:**
```bash
./run.sh
```

**Windows:**
```bash
run.bat
```

The startup script automatically checks:
- ✓ Whether `.env` configuration file exists
- ✓ Whether `uv` is installed
- ✓ Provides friendly error messages

### User Guide

#### Basic Usage

1. **Start the Program**

   **Windows**:
   ```bash
   # Method 1: Using batch file (recommended)
   run.bat

   # Method 2: Manual run
   cd meeting_translator && python main_app.py
   ```

   **macOS**:
   ```bash
   cd meeting_translator && python main_app.py
   ```

2. **Select Mode**
   - Press `F1` to switch to "Speak Mode" (Chinese to English)
   - Press `F2` to switch to "Listen Mode" (English to Chinese)

3. **Set Up Meeting Software**
   - In your meeting software, select **"Voicemeeter Input"** as the microphone
   - Set system audio output to "Voicemeeter Input"

4. **Start Meeting**
   - Speak Mode: Speak in Chinese directly, others hear English
   - Listen Mode: Read subtitles on screen to understand English in real-time

#### Advanced Features

##### Switching Translation Service Providers

The system supports multiple translation service providers, easily switchable through configuration:

| Provider | Features | Configuration |
|----------|----------|---------------|
| **Alibaba Cloud DashScope** | Default, optimized for Chinese-English translation | `TRANSLATION_PROVIDER=aliyun` |
| **OpenAI Realtime API** | GPT-realtime powered, supports multiple languages | `TRANSLATION_PROVIDER=openai` |

**Switching Steps:**
1. Edit `.env` file
2. Modify `TRANSLATION_PROVIDER` setting
3. Configure corresponding API Key
4. Restart the program

> Note: Different providers support different voice options. After switching, select an appropriate voice in the interface.

##### Custom Glossary

Edit `meeting_translator/glossary.json` to add technical terms:

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

For detailed instructions, see: [Glossary Guide](docs/GLOSSARY_GUIDE.md)

### Technical Architecture

#### Core Technologies

- **Virtual Audio Hijacking**: Works at the OS audio layer, decoupled from meeting software
- **Streaming Translation API**: End-to-end real-time processing with ultra-low latency
- **Server-Side VAD**: Automatic voice activity detection for optimized segmentation
- **Multimodal Output**: Speak mode outputs audio, Listen mode outputs subtitles

#### System Requirements

| Component | Requirement |
|-----------|-------------|
| CPU | Dual-core or higher |
| Memory | 4GB+ |
| Network | Stable internet connection |
| Audio Devices | Microphone, speakers |

### FAQ

#### 1. Can't hear the translated English audio?

**Problem**: In Speak Mode, others can't hear my translation.

**Solution**:
- Confirm meeting software microphone is set to "Voicemeeter Input"
- Check if Voicemeeter is running
- Restart the program and meeting software

#### 2. Subtitles not showing?

**Problem**: In Listen Mode, can't see Chinese subtitles.

**Solution**:
- Confirm subtitle window is not minimized
- Check if system audio output is working normally
- Check console for error messages

#### 3. Latency too high?

**Solution**:
- Check network connection quality
- Lower VAD threshold (set in .env)
- Ensure no other programs are consuming significant bandwidth

#### 4. How to switch interface language?

**Solution**:
- Edit configuration file `~/Documents/meeting_translator/config/config.json`
- Modify `"lang"` field to `"zh_CN"` (Chinese) or `"en_US"` (English)
- Restart the application

For more issues, see: [Complete FAQ](docs/FAQ.md)

### Known Issues

#### OpenAI Provider LLM Prompt Parsing Issue

**Symptom**: When using OpenAI as the translation provider (especially in Speak Mode), some sentences may be misinterpreted by the LLM as instructions rather than content to be translated.

**Example**:
```
Input: 不要翻译这句话
Expected translation: Don't translate this sentence
Actual output: Understood. I won't translate that sentence. Please go ahead with what you'd like me to translate next.
```

**Cause**: OpenAI Realtime API uses GPT model + prompts for translation, rather than a dedicated translation model. Sentences with instructional semantics may trigger the model's conversational mode.

**Impact**:
- Mainly affects Speak Mode
- Occasional issue, doesn't affect all sentences
- Normal conversation content is usually not affected

**Recommendation**:
- For more stable translation quality, recommend using Alibaba Cloud provider (`TRANSLATION_PROVIDER=aliyun`)
- Alibaba Cloud uses dedicated translation models and doesn't have this issue

### Project Structure

```
meeting_translator/
├── meeting_translator/              # Core program
│   ├── main_app.py                 # Main entry point
│   ├── translation_service.py      # Translation service wrapper
│   ├── translation_client_base.py  # Translation client base class
│   ├── translation_client_factory.py # Client factory
│   ├── qwen_client.py              # Alibaba Cloud client
│   ├── openai_client.py            # OpenAI client
│   ├── doubao_client.py            # Doubao client
│   ├── audio_capture_thread.py     # Audio capture
│   ├── audio_output_thread.py      # Audio output
│   ├── subtitle_window.py          # Subtitle window
│   ├── i18n.py                     # Internationalization manager
│   ├── locales/                    # Translation files
│   │   ├── zh_CN.json             # Chinese translations
│   │   └── en_US.json             # English translations
│   ├── glossary.json               # Glossary
│   └── styles/                     # UI styles
├── docs/                           # Documentation
├── .env.example                    # Configuration template
├── .gitignore
├── requirements.txt
└── README.md
```

### Contributing

Contributions, issue reports, and suggestions are welcome!

1. Fork this repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Acknowledgments

- Thanks to Alibaba Cloud Tongyi Qianwen team for providing the real-time translation API
- Thanks to OpenAI for providing the Realtime API
- Thanks to VB-Audio for providing Voicemeeter virtual audio device

### Contact

- **Author**: Ren Yuan
- **GitHub**: [@eerenyuan](https://github.com/eerenyuan)
- **Project URL**: [https://github.com/eerenyuan/meeting_translator](https://github.com/eerenyuan/meeting_translator)

**If this project helps you, please give it a ⭐️ Star!**

**[Back to Top](#meeting-translator---实时会议翻译系统) | [中文](#中文)**
