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
BaseTranslationClient          # Core interface (connect, send_audio, handle_messages)
+ OutputMixin                   # 统一输出接口
+ AudioPlayerMixin              # 音频播放能力 (S2S only)
= Full-featured Client
```

**示例**：
```python
# S2S Client（语音到语音）
class QwenClient(BaseTranslationClient, OutputMixin, AudioPlayerMixin):
    pass  # 自动获得：核心接口 + 输出 + 音频播放

# S2T Client（语音到文本）
class QwenTextClient(BaseTranslationClient, OutputMixin):
    pass  # 自动获得：核心接口 + 输出（无音频播放）
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
1. 创建 `qwen_client.py` - 统一的 Qwen client
2. 根据 `audio_enabled` 参数动态应用 AudioPlayerMixin
3. 应用 OutputMixin 替换所有 logger/print 调用
4. 测试 S2S 和 S2T 两种模式

**实现策略**：
```python
class QwenLiveTranslateClient(
    BaseTranslationClient,
    OutputMixin,
    AudioPlayerMixin  # 只在 audio_enabled=True 时使用
):
    def __init__(self, audio_enabled=True, **kwargs):
        # audio_enabled 控制 S2S/S2T 模式
        super().__init__(audio_enabled=audio_enabled, **kwargs)

        if not audio_enabled:
            # S2T 模式：不使用音频播放功能
            pass
```

**关键变更**：
- 移除 `livetranslate_client.py` 和 `livetranslate_text_client.py`
- 创建统一的 `qwen_client.py`
- 所有输出通过 `self.output_translation()`, `self.output_status()` 等
- 音频播放统一通过 `self.start_audio_player()`, `self.queue_audio()`
