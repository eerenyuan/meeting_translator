# Client 重构计划

## 进度概览

- ✅ **阶段1**: 设计统一架构（完成）
  - ✅ 创建 OutputMixin - 统一输出接口
  - ✅ 创建 AudioPlayerMixin - 音频播放能力
  - ✅ 扩展 BaseTranslationClient - 添加通用方法
  - ✅ 设计 mixin 组合架构
- ⏳ **阶段2**: 重构 Qwen clients（待开始）
- ⏳ **阶段3**: 标准化其他 clients（待开始）
- ⏳ **阶段4**: 添加试听功能（待开始）

---

## 现状分析

### Client 文件
1. `translation_client_base.py` - 抽象基类
2. `livetranslate_client.py` - Qwen S2S client（语音到语音）
3. `livetranslate_text_client.py` - Qwen S2T client（语音到文本）
4. `doubao_client.py` - Doubao AST client
5. `openai_realtime_client.py` - OpenAI Realtime API client

### 现有问题
1. ❌ **输出不统一** - 各 client 使用 logger/print，没有统一接口
2. ❌ **Qwen 重复代码** - 两个 Qwen client 有大量重复逻辑
3. ❌ **缺少标准输出** - 翻译结果、状态、错误输出格式不一致
4. ❌ **没有试听功能** - Issue #8 要求

### BaseTranslationClient 接口
```python
- __init__(api_key, source_language, target_language, voice, audio_enabled)
- async connect() - 建立连接
- async configure_session() - 配置会话
- async send_audio_chunk(audio_data) - 发送音频
- async handle_server_messages(on_text_received) - 处理服务器消息
- async close() - 关闭连接
- @property input_rate - 输入采样率
- @property output_rate - 输出采样率
- @classmethod get_supported_voices() - 支持的音色
- start_audio_player() - 启动音频播放（可选）
```

## 重构目标

### 阶段1: 设计统一架构 ✅
1. **OutputMixin** - 统一输出接口
   ```python
   def output_translation(source, target, metadata)
   def output_partial(target, mode, metadata)
   def output_status(message, metadata)
   def output_error(message, exc_info, metadata)
   ```

2. **AudioPlayerMixin** - 音频播放能力
   ```python
   def start_audio_player()
   def stop_audio_player()
   def queue_audio(audio_data)
   def supports_voice_testing() -> bool
   async def test_voice_async(text)
   ```

3. **S2S/S2T 模式** - 区分两种模式
   - S2S (Speech-to-Speech): 语音输入 → 翻译 → 语音输出
   - S2T (Speech-to-Text): 语音输入 → 翻译 → 文本输出

4. **重构 BaseTranslationClient** - 添加通用方法
   - `get_translation_mode()` - 返回 S2S/S2T
   - `supports_voice_testing()` - 默认 False
   - `test_voice_async()` - 默认 raise NotImplementedError
   - `get_supported_voices()` - 默认返回空 dict

### 架构设计完成 ✅
**Mixin 组合架构**：
```
BaseTranslationClient          # 核心接口 (connect, send_audio, input_rate)
+ OutputMixin                   # 统一输出接口
+ AudioPlayerMixin              # 音频播放能力 (S2S only)
= Full-featured Client
```

**职责分离**：
| 组件 | 职责 | 属性/方法 |
|------|------|-----------|
| **BaseTranslationClient** | 核心翻译接口 | `api_key`, `source_language`, `target_language`<br>`connect()`, `send_audio_chunk()`, `handle_server_messages()`<br>`input_rate` - 输入采样率（麦克风） |
| **OutputMixin** | 统一输出 | `output_translation()`, `output_status()`, `output_error()` |
| **AudioPlayerMixin** | 音频播放（S2S only） | `voice`, `audio_enabled`, `output_rate`, `get_supported_voices()`<br>`start_audio_player()`, `stop_audio_player()`, `queue_audio()`<br>`supports_voice_testing()`, `test_voice_async()`<br>**参数验证**：audio_enabled=False 时拒绝 voice 参数 |

**关键设计决策**：
1. **使用 `audio_enabled` flag 控制模式**：
   - AudioPlayerMixin 接受并管理 `voice` 和 `audio_enabled` 参数
   - 通过 `audio_enabled=True/False` 控制 S2S/S2T 模式
   - 支持**一个 client 类同时支持两种模式**（合并重复代码）

2. **职责分离**：
   - `voice`, `audio_enabled`, `output_rate`, `get_supported_voices()` 在 AudioPlayerMixin（S2S-only）
   - `input_rate`, `send_audio_chunk()` 保留在 Base（S2S 和 S2T 都需要）
   - S2T clients 不混入 AudioPlayerMixin，不接受 `voice` 参数

3. **参数验证**：
   - AudioPlayerMixin.__init__() 检查参数一致性
   - 如果 `audio_enabled=False` 但提供了 `voice`，抛出 ValueError
   - 早期捕获配置错误

4. **为什么不用 isinstance 检测**：
   - 每个 provider 的音频实现方式不同（需要深度集成）
   - 无法用 composition 抽象通用组件
   - 参数控制更灵活（运行时切换模式）
   - 符合"合并两个 Qwen clients"的目标

**示例**：
```python
# 统一的 Qwen Client（一个类，两种模式）
class QwenClient(BaseTranslationClient, OutputMixin, AudioPlayerMixin):
    def __init__(self, api_key, source_language="zh", target_language="en",
                 voice=None, audio_enabled=True, **kwargs):
        super().__init__(
            api_key=api_key,
            source_language=source_language,
            target_language=target_language,
            voice=voice,
            audio_enabled=audio_enabled,
            **kwargs
        )

    @property
    def input_rate(self) -> int:
        return 16000  # 输入采样率（麦克风）

    @property
    def output_rate(self) -> int:
        return 24000  # 输出采样率（仅 S2S）

    @classmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        return {"zhichu": "知楚 (女声)", "zhiyan": "知燕 (女声)"}

    def start_audio_player(self):
        if not self.audio_enabled:
            return  # S2T 模式，不启动音频播放
        super().start_audio_player()

# 使用：
client_s2s = QwenClient(api_key, voice="zhichu", audio_enabled=True)   # ✅ S2S
client_s2t = QwenClient(api_key, audio_enabled=False)  # ✅ S2T

# 参数验证（AudioPlayerMixin 提供）：
client_error = QwenClient(api_key, voice="zhichu", audio_enabled=False)
# ❌ ValueError: audio_enabled=False (S2T 模式) 不应该指定 voice 参数
```

**文件**：
- ✅ `translation_client_base.py` - 抽象基类
- ✅ `client_output_mixin.py` - 输出接口
- ✅ `client_audio_mixin.py` - 音频播放能力

### 阶段2: 重构 Qwen Clients
1. 合并 `livetranslate_client` 和 `livetranslate_text_client`
2. 应用 OutputMixin
3. 支持模式切换

### 阶段3: 标准化其他 Clients
1. Doubao client 应用 OutputMixin
2. OpenAI client 应用 OutputMixin
3. 统一 console 输出格式（Issue #9）

### 阶段4: 添加试听功能
1. 定义 `test_voice(text)` 接口
2. 各 client 实现试听
3. UI 添加试听按钮（Issue #8）

## 设计原则
1. **向后兼容** - 不破坏现有功能
2. **渐进式** - 每个 client 独立重构和测试
3. **统一输出** - 所有输出通过 `Out` 单例
4. **清晰分层** - 基类 + Mixin + 具体实现

## 下一步

**当前阶段**: 阶段1 已完成 ✅

**阶段2: 重构 Qwen clients**
1. 创建 `qwen_client.py` - **统一的 Qwen client**（合并两个文件）
2. 应用 OutputMixin 替换所有 logger/print 调用
3. 根据 `audio_enabled` 参数控制 S2S/S2T 行为
4. 测试两种模式

**实现策略**：
```python
# 一个类支持两种模式（通过 audio_enabled 参数）
class QwenClient(BaseTranslationClient, OutputMixin, AudioPlayerMixin):
    def __init__(self, api_key, source_language="zh", target_language="en",
                 voice=None, audio_enabled=True, **kwargs):
        super().__init__(
            api_key=api_key,
            source_language=source_language,
            target_language=target_language,
            voice=voice,
            audio_enabled=audio_enabled,
            **kwargs
        )

    @property
    def input_rate(self) -> int:
        """输入采样率（麦克风）- S2S 和 S2T 都需要"""
        return 16000

    @property
    def output_rate(self) -> int:
        """输出采样率 - 仅 S2S 需要"""
        return 24000

    @classmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        """支持的音色列表 - 仅 S2S"""
        return {"zhichu": "知楚 (女声)", "zhiyan": "知燕 (女声)"}

    async def handle_server_messages(self, on_text_received=None):
        """处理服务器消息"""
        async for message in self.websocket:
            data = json.loads(message)

            # 共同逻辑：转录、翻译
            if "translation" in data:
                translation = data["translation"]
                self.output_translation(translation, source_text=source_text)

            # S2S 特有逻辑：处理音频
            if self.audio_enabled and "audio" in data:
                audio_data = base64.b64decode(data["audio"])
                self.queue_audio(audio_data)

    def start_audio_player(self):
        if not self.audio_enabled:
            return  # S2T 模式，跳过
        super().start_audio_player()
```

**关键变更**：
- ✅ 合并 `livetranslate_client.py` + `livetranslate_text_client.py` → `qwen_client.py`
- ✅ 所有输出通过 `self.output_translation()`, `self.output_status()` 等
- ✅ 音频相关方法检查 `self.audio_enabled`
- ✅ 使用 `audio_enabled` flag 控制模式（而非类型区分）
