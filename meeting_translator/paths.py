"""
应用路径配置
统一管理所有数据目录的路径
"""

import os
from pathlib import Path
from i18n import get_i18n


# ========== 根目录 ==========
# 使用项目根目录（不是用户目录）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# ========== 数据目录 ==========
# 应用数据放在用户目录下
MEETING_TRANSLATOR_ROOT = Path.home() / "Documents" / "meeting_translator"


# ========== 子目录（项目内）==========
ASSETS_DIR = PROJECT_ROOT / "assets"             # 资源文件（标准音频输入）
VOICE_SAMPLES_DIR = PROJECT_ROOT / "voice_samples"  # 音色样本文件（生成）

# ========== 用户数据子目录 ==========
LOGS_DIR = MEETING_TRANSLATOR_ROOT / "logs"           # 日志文件
CONFIG_DIR = MEETING_TRANSLATOR_ROOT / "config"       # 配置文件
RECORDS_DIR = MEETING_TRANSLATOR_ROOT / "records"     # 会议记录（字幕）


# ========== 旧路径（用于迁移） ==========
# 保留以便向后兼容和自动迁移旧文件
LEGACY_LOGS_DIR = Path.home() / "Documents" / "会议翻译日志"
LEGACY_CONFIG_DIR = Path.home() / "Documents" / "会议翻译配置"
LEGACY_RECORDS_DIR = Path.home() / "Documents" / "会议记录"


# ========== 迁移标记 ==========
# 用于记录是否已经完成过迁移
MIGRATION_MARKER = CONFIG_DIR / ".migrated"


def ensure_directories():
    """
    确保所有必要的目录存在
    如果不存在则创建
    """
    MEETING_TRANSLATOR_ROOT.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
    CONFIG_DIR.mkdir(exist_ok=True)
    RECORDS_DIR.mkdir(exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)  # 项目内目录
    VOICE_SAMPLES_DIR.mkdir(parents=True, exist_ok=True)  # 项目内目录


def migrate_legacy_files():
    """
    自动迁移旧目录中的文件到新目录

    只在以下情况下迁移：
    1. 迁移标记文件不存在（未迁移过）
    2. 旧目录存在且有文件

    Returns:
        dict: 迁移统计信息 {'logs': N, 'config': M, 'records': P, 'skipped': bool}
    """
    stats = {'logs': 0, 'config': 0, 'records': 0, 'skipped': False}

    # 检查是否已经迁移过
    if MIGRATION_MARKER.exists():
        stats['skipped'] = True
        return stats

    # 检查是否有旧文件需要迁移
    has_legacy = any([
        LEGACY_LOGS_DIR.exists() and list(LEGACY_LOGS_DIR.iterdir()),
        LEGACY_CONFIG_DIR.exists() and list(LEGACY_CONFIG_DIR.iterdir()),
        LEGACY_RECORDS_DIR.exists() and list(LEGACY_RECORDS_DIR.iterdir())
    ])

    if not has_legacy:
        # 没有旧文件，创建标记文件（表示已检查过）
        MIGRATION_MARKER.touch(exist_ok=True)
        stats['skipped'] = True
        return stats

    def migrate_files(src_dir, dst_dir, stat_key):
        """迁移单个目录的文件"""
        if not src_dir.exists():
            return 0

        dst_dir.mkdir(parents=True, exist_ok=True)
        count = 0

        for file in src_dir.iterdir():
            if file.is_file():
                dst_file = dst_dir / file.name
                # 只有目标文件不存在时才迁移（避免覆盖）
                if not dst_file.exists():
                    import shutil
                    try:
                        shutil.copy2(file, dst_file)
                        count += 1
                    except Exception as e:
                        from i18n import get_i18n
                        i18n = get_i18n()
                        print(i18n.t("paths.migration_file_failed", file=str(file), error=str(e)))

        return count

    stats['logs'] = migrate_files(LEGACY_LOGS_DIR, LOGS_DIR, 'logs')
    stats['config'] = migrate_files(LEGACY_CONFIG_DIR, CONFIG_DIR, 'config')
    stats['records'] = migrate_files(LEGACY_RECORDS_DIR, RECORDS_DIR, 'records')

    # 迁移完成，创建标记文件
    if sum(stats.values()) > 0:
        try:
            MIGRATION_MARKER.write_text(
                f"Migration completed at {__import__('datetime').datetime.now()}\n"
                f"Legacy files: {stats}\n"
            )
        except Exception:
            # 标记文件创建失败不影响迁移结果
            pass

    return stats


def get_initialization_message():
    """
    获取初始化信息（用于首次启动时的提示）

    Returns:
        str: 初始化信息或空字符串
    """
    i18n = get_i18n()
    messages = []

    # 检查是否是首次启动（新目录不存在）
    if not MEETING_TRANSLATOR_ROOT.exists():
        messages.append(i18n.t("paths.creating_data_dir", path=str(MEETING_TRANSLATOR_ROOT)))

    # 检查是否需要迁移（只有在未迁移过且有旧文件时才显示）
    stats = migrate_legacy_files()

    if not stats['skipped'] and sum(stats.values()) > 0:
        messages.append(i18n.t("paths.migrating_legacy"))
        messages.append(i18n.t("paths.migration_complete"))
        if stats['logs'] > 0:
            messages.append(i18n.t("paths.migration_logs", count=stats['logs']))
        if stats['config'] > 0:
            messages.append(i18n.t("paths.migration_config", count=stats['config']))
        if stats['records'] > 0:
            messages.append(i18n.t("paths.migration_records", count=stats['records']))
        messages.append(i18n.t("paths.legacy_files_kept"))
        messages.append(i18n.t("paths.legacy_logs_dir", path=str(LEGACY_LOGS_DIR)))
        messages.append(i18n.t("paths.legacy_config_dir", path=str(LEGACY_CONFIG_DIR)))
        messages.append(i18n.t("paths.legacy_records_dir", path=str(LEGACY_RECORDS_DIR)))
        messages.append(i18n.t("paths.can_delete_legacy"))

    return "\n".join(messages)
