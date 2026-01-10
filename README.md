# Meeting Translator - 实时会议翻译系统

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

**从"茶壶里装汤圆"到流畅对话：打造零延迟实时会议翻译系统**

一个真正零延迟、双向实时、完全本地化、与会议软件无关的翻译系统。

---

## 核心亮点

- 🎯 **完全本地运行**：只在你的电脑上，其他参会者无感知，不需要任何配合
- 🌐 **会议软件无关**：支持 Zoom、Teams、Google Meet、腾讯会议等所有会议平台
- ⚡ **真正零延迟**：<500ms 端到端延迟，不打断对话节奏
- 🔄 **多提供商支持**：支持阿里云、OpenAI 等多个翻译服务，可随时切换
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
4. **翻译服务 API Key** (选择其一):
   - **阿里云 DashScope** (默认): [申请地址](https://dashscope.console.aliyun.com/)
   - **OpenAI Realtime API**: [申请地址](https://platform.openai.com/api-keys)

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

## 使用 UV（推荐用于 Git Worktrees）

**UV** 是现代 Python 包管理器，提供自动环境管理和依赖安装，特别适合使用 git worktree 的多分支开发场景。

### 为什么使用 UV？

- ✅ **无需手动激活虚拟环境** - 自动管理 Python 环境
- ✅ **Git Worktree 友好** - 多个工作树共享依赖缓存，无需重复安装
- ✅ **一键运行** - `uv run main.py` 即可启动
- ✅ **跨平台支持** - Windows、macOS、Linux 统一体验
- ✅ **更快的依赖安装** - 并行安装，缓存友好

### 安装 UV

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

### 使用 UV 运行程序

#### 方法 1: 使用 uv run（推荐）

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

#### 方法 2: 使用启动脚本

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

### Git Worktree 工作流

使用 git worktree 可以在不同目录同时处理多个分支，非常适合并行开发和测试。

#### 创建 Worktree

```bash
# 在主仓库中创建一个新的 worktree
git worktree add ../meeting_translator-feature feature-branch

# 切换到 worktree 目录
cd ../meeting_translator-feature
```

#### 在 Worktree 中运行

```bash
# 1. 配置环境变量（首次）
cp .env.example .env
# 编辑 .env 填入你的 API Key

# 2. 直接运行 - UV 会自动处理一切
uv run main.py
```

**无需任何额外设置！** UV 会：
- 自动使用正确的 Python 版本
- 共享主仓库的依赖缓存（不会重复下载）
- 为每个 worktree 创建独立的虚拟环境
- 加载 worktree 中的 `.env` 配置

#### Worktree 管理

```bash
# 查看所有 worktrees
git worktree list

# 删除 worktree
git worktree remove ../meeting_translator-feature

# 清理已删除的 worktree 记录
git worktree prune
```

### 依赖管理

#### 安装核心依赖

```bash
# UV 会根据 pyproject.toml 自动安装
uv run main.py
```

#### 安装可选依赖（Doubao 提供商）

```bash
# 安装 Doubao 提供商所需的 protobuf
uv sync --extra doubao

# 或安装所有可选依赖
uv sync --extra all
```

#### 更新依赖

```bash
# 更新锁定文件
uv lock --upgrade

# 同步到最新版本
uv sync
```

### 迁移指南（从旧方法迁移到 UV）

如果你之前使用的是传统的 `venv` + `pip` 方式，可以平滑迁移：

**步骤 1: 安装 UV**
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**步骤 2: 测试 UV**
```bash
# 测试新方法
uv run main.py
```

**步骤 3: 验证旧方法仍然可用（向后兼容）**
```bash
# 旧方法依然可以使用
source .venv/bin/activate  # Windows: .venv\Scripts\activate
cd meeting_translator
python main_app.py
```

**步骤 4: 可选 - 清理旧虚拟环境**
```bash
# 确认 UV 方法工作正常后，可以删除旧的 .venv
rm -rf .venv  # Windows: rmdir /s .venv
```

### UV vs 传统方法对比

| 特性 | 传统方法 (venv + pip) | UV 方法 |
|-----|---------------------|---------|
| **环境激活** | 需要手动 `source .venv/bin/activate` | ❌ 不需要，自动管理 |
| **依赖安装** | 手动 `pip install -r requirements.txt` | ✅ 首次运行自动安装 |
| **运行位置** | 必须 `cd meeting_translator/` | ✅ 可从仓库根目录运行 |
| **Git Worktree** | 每个 worktree 需要独立安装 | ✅ 共享缓存，无需重复安装 |
| **Python 版本** | 手动管理 | ✅ 自动匹配 `.python-version` |
| **依赖更新** | 手动 `pip install --upgrade` | ✅ `uv lock --upgrade` |
| **启动速度** | 正常 | ⚡ 更快（并行安装） |

### 故障排除

#### UV 未找到

```bash
# 确保 UV 在 PATH 中
# macOS/Linux: 重新加载 shell 配置
source ~/.bashrc  # 或 ~/.zshrc

# Windows: 重启终端或添加到 PATH
```

#### Python 版本不匹配

```bash
# UV 会自动使用 .python-version 中指定的版本 (3.10)
# 如果需要使用不同版本：
UV_PYTHON=3.11 uv run main.py
```

#### 依赖安装失败

```bash
# 清除 UV 缓存
uv cache clean

# 重新安装
uv sync --reinstall
```

#### .env 文件未找到

```bash
# UV 方法同样需要 .env 文件
cp .env.example .env
# 编辑 .env 填入 API Key
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

#### 切换翻译服务提供商

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

## 已知问题

### OpenAI 提供商的 LLM 提示词解析问题

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

---

## 项目结构

```
meeting_translator/
├── meeting_translator/              # 核心程序
│   ├── main_app.py                 # 主程序入口
│   ├── translation_service.py      # 翻译服务封装
│   ├── translation_client_base.py  # 翻译客户端基类
│   ├── translation_client_factory.py # 客户端工厂
│   ├── livetranslate_client.py     # 阿里云客户端
│   ├── openai_realtime_client.py   # OpenAI 客户端
│   ├── audio_capture_thread.py     # 音频捕获
│   ├── audio_output_thread.py      # 音频输出
│   ├── subtitle_window.py          # 字幕窗口
│   ├── glossary.json               # 术语库
│   └── styles/                     # UI样式
├── docs/                           # 文档
├── .env.example                    # 配置模板
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

- 感谢阿里云通义千问团队提供的实时翻译 API
- 感谢 OpenAI 提供的 Realtime API
- 感谢 VB-Audio 提供的 Voicemeeter 虚拟音频设备

---

## 联系方式

- **作者**: Ren Yuan
- **GitHub**: [@eerenyuan](https://github.com/eerenyuan)
- **项目地址**: [https://github.com/eerenyuan/meeting_translator](https://github.com/eerenyuan/meeting_translator)

---

**如果这个项目对你有帮助，请给个⭐️ Star支持一下！**
