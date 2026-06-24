#!/bin/bash
# ============================================================
# AI Video Dubbing Pro — 打包脚本 (macOS / Windows)
# 用法: bash build.sh [mac|win|clean]
# ============================================================

set -e

APP_NAME="AI视频配音Pro"
SPEC_FILE="AI视频配音Pro.spec"
DIST_DIR="dist/${APP_NAME}"
BUILD_VERSION="${BUILD_VERSION:-4.3.1}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[BUILD]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ============================================================
# 平台检测
# ============================================================
detect_platform() {
    case "$(uname -s)" in
        Darwin)  PLATFORM="mac" ;;
        MINGW*|MSYS*|CYGWIN*) PLATFORM="win" ;;
        *)       PLATFORM="linux" ;;
    esac
    # 允许命令行覆盖
    if [ -n "$1" ] && [ "$1" != "clean" ]; then
        PLATFORM="$1"
    fi
}

# ============================================================
# 环境检查
# ============================================================
check_deps() {
    log "检查打包环境..."

    # Python
    if ! command -v python3 &> /dev/null; then
        err "未找到 python3，请先安装 Python 3.10+"
    fi
    PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log "  Python: $PYTHON_VER"

    # PyInstaller
    if ! python3 -c "import PyInstaller" &> /dev/null 2>&1; then
        warn "未安装 PyInstaller，正在安装..."
        pip3 install pyinstaller
    fi
    PYI_VER=$(python3 -c "import PyInstaller; print(PyInstaller.__version__)" 2>/dev/null || echo "?")
    log "  PyInstaller: $PYI_VER"

    # FFmpeg (macOS)
    if [ "$PLATFORM" = "mac" ]; then
        if command -v ffmpeg &> /dev/null; then
            FFMPEG_PATH=$(which ffmpeg)
            log "  FFmpeg: $FFMPEG_PATH"
        else
            warn "未找到 ffmpeg，请运行: brew install ffmpeg"
            warn "打包后用户需自行安装 FFmpeg"
        fi
    fi

    # FFmpeg (Windows)
    if [ "$PLATFORM" = "win" ]; then
        if [ -f "ffmpeg.exe" ]; then
            log "  FFmpeg: ./ffmpeg.exe (将随包分发)"
        else
            warn "未找到 ffmpeg.exe，请从 https://ffmpeg.org/download.html 下载"
            warn "并将 ffmpeg.exe 放到项目根目录"
        fi
    fi
}

# ============================================================
# macOS 打包
# ============================================================
build_mac() {
    log "开始 macOS 打包..."
    log "目标架构: $(uname -m)"

    # 生成 .icns 图标（如果没有的话）
    if [ ! -f "icon.icns" ]; then
        warn "未找到 icon.icns，将使用默认图标"
        warn "如需自定义图标: 准备 1024x1024 PNG → 用 sips/makeicns 转换"
    fi

    # 清理旧构建
    rm -rf build dist

    # PyInstaller 构建
    python3 -m PyInstaller \
        --clean \
        --noconfirm \
        "${SPEC_FILE}"

    if [ -d "dist/${APP_NAME}.app" ]; then
        APP_SIZE=$(du -sh "dist/${APP_NAME}.app" | cut -f1)
        log "✅ macOS 打包完成!"
        log "   路径: dist/${APP_NAME}.app"
        log "   大小: $APP_SIZE"

        # 创建 DMG（可选）
        if command -v create-dmg &> /dev/null; then
            log "正在创建 DMG..."
            create-dmg \
                --volname "${APP_NAME}" \
                --volicon "icon.icns" \
                --window-pos 200 120 \
                --window-size 600 400 \
                --icon-size 100 \
                --app-drop-link 400 200 \
                "dist/${APP_NAME}-v${BUILD_VERSION}.dmg" \
                "dist/${APP_NAME}.app"
            log "✅ DMG: dist/${APP_NAME}-v${BUILD_VERSION}.dmg"
        else
            warn "未安装 create-dmg，跳过 DMG 创建"
            warn "安装: brew install create-dmg"
        fi
    else
        err "macOS 打包失败"
    fi
}

# ============================================================
# Windows 打包
# ============================================================
build_win() {
    log "开始 Windows 打包..."

    rm -rf build dist

    python3 -m PyInstaller \
        --clean \
        --noconfirm \
        "${SPEC_FILE}"

    if [ -d "dist/${APP_NAME}" ]; then
        DIST_SIZE=$(du -sh "dist/${APP_NAME}" | cut -f1)
        log "✅ Windows 打包完成!"
        log "   路径: dist/${APP_NAME}/"
        log "   大小: $DIST_SIZE"

        # 创建 ZIP
        cd dist
        zip -r "${APP_NAME}-v${BUILD_VERSION}-win64.zip" "${APP_NAME}/"
        cd ..
        log "   压缩包: dist/${APP_NAME}-v${BUILD_VERSION}-win64.zip"
    else
        err "Windows 打包失败"
    fi
}

# ============================================================
# 清理
# ============================================================
clean() {
    log "清理构建文件..."
    rm -rf build dist *.spec.bak
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    log "清理完成"
}

# ============================================================
# 主入口
# ============================================================
main() {
    echo ""
    echo "  ╔════════════════════════════════════════╗"
    echo "  ║   AI 视频配音Pro — 打包工具 v${BUILD_VERSION}  ║"
    echo "  ╚════════════════════════════════════════╝"
    echo ""

    detect_platform "$1"

    if [ "$1" = "clean" ] || [ "$2" = "clean" ]; then
        clean
        return
    fi

    check_deps

    log "目标平台: $PLATFORM"

    case $PLATFORM in
        mac)
            build_mac
            ;;
        win)
            build_win
            ;;
        linux)
            warn "Linux 打包未经过充分测试，将使用 Windows 模式"
            build_win
            ;;
        *)
            err "未知平台: $PLATFORM"
            ;;
    esac

    echo ""
    log "════════════════════════════════════════"
    log "打包完成！输出目录: dist/"
    ls -lh dist/ 2>/dev/null || true
}

main "$@"
