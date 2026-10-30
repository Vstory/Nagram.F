#!/usr/bin/env python3
# SCRIPT_VERSION=1.0.0
"""CI 专用：在 runner 工作区把 Nagram 改写成 Nagram.F 形态，仓库源码一行都不落库。

为什么只在 CI 改：包名/显示名/版本号一旦提交进仓库，每次同步上游都要撞冲突；而 fork 身份
只在出包时才需要。故一律在 CI 工作区就地改写，「期望原文 → 改写后」逐条声明，任一条找不到
原文即整体失败 —— 上游改了写法必须回来同步，不允许静默漏改（漏改的产物能装、能跑，只是装
上去还是上游那个应用）。

改七类：
  1. 包名 / 显示名（与上游原版并存安装）
  2. native 层签名指纹 —— 内置的是上游发布证书的 SHA1，自签包会 JNI_ERR；换成我们自己的证书
     SHA1 而不是删掉校验（删掉等于把「防重打包」也一起扔了，任何人都能改我们的包重签发布）
  3. 版本号（APP_VERSION_CODE / APP_VERSION_NAME，来源 gradle.properties）
  4. 调试菜单：长按一次直接弹出（不再要求第 2 次），并去掉「发生错误」提示
  5. 调试菜单硬编码英文条目汉化（语言包管不到字面量）
  （隐藏功能开关保持上游默认关闭，由用户在设置页自行开启 —— CI 不代劳）

用法：
    python3 scripts/ci-fork-identity.py --version-code 5001 --version-name 13.0.2+ci.abc12345
    python3 scripts/ci-fork-identity.py --dry-run
    python3 scripts/ci-fork-identity.py --selftest
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

UPSTREAM_APP_ID = "xyz.nextalone.nagram"
DEFAULT_APP_ID = "xyz.nextalone.nagram.fork"
DEFAULT_LABEL = "Nagram.F"

SETTINGS = "TMessagesProj/src/main/java/org/telegram/ui/SettingsActivity.java"
JNIC = "TMessagesProj/jni/jni.c"
INTEGRITY = "TMessagesProj/jni/integrity/integrity.cpp"
# tokens/Signing/Vstory.jks 证书的 SHA1（大写无冒号）
FORK_CERT_SHA1 = "92A37D7C19D696CA2645D00A11C507358805B2D6"
UPSTREAM_CERT_SHA1 = "3A0F57FE06485D0B90D0ACD990E3A30328E3988D"
GRADLE_PROPS = "gradle.properties"
APP_GRADLE = "TMessagesProj/build.gradle"
STRINGS = "TMessagesProj/src/main/res/values/strings.xml"

# 调试菜单里硬编码的英文字面量（getString(R.string.*) 那些走语言包，不在表内）。
# 键是源码里的原文，值是对应中文；脚本按「出现即替换」处理（同一字面量可能出现在多处）。
DEBUG_MENU_ZH = {
    "Clean app update": "清理应用更新",
    "Clear Mini Apps Permissions and Files": "清除小程序权限与文件",
    "Clear all login tokens": "清除所有登录令牌",
    "Enable Invoice Payment": "启用发票支付",
    "Disable Invoice Payment": "禁用发票支付",
    "Enable tablet mode": "启用平板模式",
    "Disable tablet mode": "禁用平板模式",
    "Enable video qualities debug": "启用视频画质调试",
    "Disable video qualities debug": "禁用视频画质调试",
    "Enable voip audio effects": "启用语音通话音效",
    "Disable voip audio effects": "禁用语音通话音效",
    "Enable adaptive browser colors": "启用浏览器自适应配色",
    "Disabled adaptive browser colors": "禁用浏览器自适应配色",
    "Force Forum Tabs": "强制话题分页",
    "Do Not Force Forum Tabs": "不强制话题分页",
    "Force big camera for round": "强制圆形视频使用大摄像头",
    "Disable big camera for round": "禁用圆形视频大摄像头",
    "Force performance class": "强制性能等级",
    "Force remove premium suggestions": "强制移除 Premium 推荐",
    "Make Memory Dump": "生成内存转储",
    "Reload app config": "重新加载应用配置",
    "Reset suggestions": "重置建议",
    "Share device info": "分享设备信息",
    "Update Attach Bots": "更新附件机器人",
    "Use Camera 2 API": "使用 Camera2 API",
    "Use old Camera 1 API": "使用旧版 Camera1 API",
    "use SurfaceView in stories": "动态使用 SurfaceView",
    "back to TextureView in stories": "动态改回 TextureView",
    "use new gpu blur": "使用 GPU 模糊",
    "back to cpu blur": "改回 CPU 模糊",
    "blur in photoviewer": "在图片查看器中模糊",
    "do not blur in photoviewer": "不在图片查看器中模糊",
    "enable debug view metrics": "启用视图指标调试",
    "disable debug view metrics": "禁用视图指标调试",
    "enable shadows in settings": "设置页启用阴影",
    "disable shadows in settings": "设置页禁用阴影",
    "enable wallpaper shader": "启用壁纸着色器",
    "disable wallpaper shader": "禁用壁纸着色器",
    "hide experimental settings": "隐藏实验性功能",
    "show experimental settings": "显示实验性功能",
    "show frame metrics": "显示帧率指标",
    "hide frame metrics": "隐藏帧率指标",
}

# 长按版本号：原来是「第 2 次才弹菜单 + 第 5 次起每次取反隐藏功能 + 错误 Toast」。
LONG_PRESS_OLD = """        versionView.setOnLongClickListener(v -> {
            versionViewPressCount++;
            if (versionViewPressCount >= 5) {
                NaConfig.INSTANCE.getShowHiddenFeature().toggleConfigBool();
                Toast.makeText(getParentActivity(), LocaleController.getString("ErrorOccurred", R.string.ErrorOccurred), Toast.LENGTH_SHORT).show();
            }
            if (versionViewPressCount < 2 && !BuildVars.DEBUG_PRIVATE_VERSION) {
                try {
                    Toast.makeText(getParentActivity(), getString(R.string.DebugMenuLongPress), Toast.LENGTH_SHORT).show();
                } catch (Exception e) {
                    FileLog.e(e);
                }
                return true;
            }
            openDebugMenu();
            return true;
        });"""

LONG_PRESS_NEW = """        versionView.setOnLongClickListener(v -> {
            openDebugMenu();
            return true;
        });"""

INTEGRITY_SIGN = f'static const char *SIGN = "{UPSTREAM_CERT_SHA1}";'
INTEGRITY_SIGN_NEW = f'static const char *SIGN = "{FORK_CERT_SHA1}";'


def build_edits(app_id: str, label: str, version_code: str, version_name: str):
    """返回 [(相对路径, 期望原文, 改写后, 是否允许多次出现)]。"""
    edits = [
        # ── 身份：只改 applicationId，不动 namespace（class 包名一变，manifest 的相对名就崩）
        (APP_GRADLE, f'defaultConfig.applicationId = "{UPSTREAM_APP_ID}"',
         f'defaultConfig.applicationId = "{app_id}"', False),
        # 显示名：launcher / 系统设置 / 最近任务都读 AppName
        (STRINGS, '<string name="AppName">Telegram</string>',
         f'<string name="AppName">{label}</string>', False),
        # ── 签名指纹换成我们自己的：JNI_OnLoad 里 verifySign 仍会跑，只是改认 Vstory 证书。
        #    删调用也能让包起来，但那把「别人改包重签也拦不住」—— 防护白送。
        (INTEGRITY, INTEGRITY_SIGN, INTEGRITY_SIGN_NEW, False),
        # ── 长按一次直接弹调试菜单，且不再有「发生错误」提示
        (SETTINGS, LONG_PRESS_OLD, LONG_PRESS_NEW, False),
        # ── 版本号
        (GRADLE_PROPS, "APP_VERSION_CODE=7175", f"APP_VERSION_CODE={version_code}", False),
        (GRADLE_PROPS, "APP_VERSION_NAME=13.0.2", f"APP_VERSION_NAME={version_name}", False),
    ]
    # ── 调试菜单汉化：字面量可能出现在别处（如 SharedConfig 的提示），一律全量替换
    for en, zh in DEBUG_MENU_ZH.items():
        edits.append((SETTINGS, f'"{en}"', f'"{zh}"', True))
    return edits


def run(app_id: str, label: str, version_code: str, version_name: str, dry_run: bool) -> int:
    edits = build_edits(app_id, label, version_code, version_name)
    changed: dict[Path, str] = {}
    failures: list[str] = []

    for rel, old, new, allow_multi in edits:
        path = REPO_ROOT / rel
        if path not in changed:
            if not path.is_file():
                failures.append(f"{rel}: 文件不存在")
                continue
            changed[path] = path.read_text(encoding="utf-8")
        text = changed[path]
        count = text.count(old)
        if count == 0:
            failures.append(f"{rel}: 找不到原文（上游可能改过写法）→ {old.splitlines()[0][:80]!r}")
            continue
        if count > 1 and not allow_multi:
            failures.append(f"{rel}: 原文出现 {count} 次（要求恰好 1 次）→ {old.splitlines()[0][:80]!r}")
            continue
        changed[path] = text.replace(old, new)
        print(f"  ✔ {rel}: {count} 处 ← {old.splitlines()[0][:60]!r}")

    if failures:
        print("\n❌ 改写失败，源码未改动：", file=sys.stderr)
        for f in failures:
            print(f"   - {f}", file=sys.stderr)
        return 1

    if dry_run:
        print(f"\n[dry-run] 共 {len(changed)} 个文件、{len(edits)} 条规则全部命中，未写入")
        return 0

    for path, text in changed.items():
        path.write_text(text, encoding="utf-8")
    print(f"\n✅ 已改写 {len(changed)} 个文件（{len(edits)} 条规则）")
    return 0


def selftest() -> int:
    """不联网、不碰仓库：只校验规则表自身结构。"""
    edits = build_edits(DEFAULT_APP_ID, DEFAULT_LABEL, "5000", "13.0.2+ci.test")
    if not edits:
        print("FAIL: 规则表为空")
        return 1
    for rel, old, new, _ in edits:
        if old == new:
            print(f"FAIL: 规则新旧一致且为空操作 → {rel}: {old[:40]!r}")
            return 1
    if len(DEBUG_MENU_ZH) < 40:
        print(f"FAIL: 汉化条目只有 {len(DEBUG_MENU_ZH)} 条，疑似被删")
        return 1
    print(f"PASS: {len(edits)} 条规则 / 汉化 {len(DEBUG_MENU_ZH)} 条")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-id", default=DEFAULT_APP_ID)
    ap.add_argument("--label", default=DEFAULT_LABEL)
    ap.add_argument("--version-code", default="5000")
    ap.add_argument("--version-name", default="13.0.2+ci.local")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    return run(a.app_id, a.label, a.version_code, a.version_name, a.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
