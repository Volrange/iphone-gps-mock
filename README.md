# iPhone GPS Mock

A macOS tool for simulating and restoring location on USB-connected iPhones, with a GUI and WGS-84/GCJ-02 coordinate support.

通过 USB 在 Mac 上设置 iPhone 的模拟定位，或清除模拟以恢复系统正常定位。提供图形界面和命令行，适用于位置相关功能的开发与调试。

> 本项目通过 iPhone 的开发服务进行**设备级定位模拟**，可能影响多个 App，不能指定只对某个 App 生效。模拟结果及恢复后的实际位置，需要在手机地图中核验。

## 功能

- **目标定位**：输入纬度、经度，将目标位置发送到 iPhone。
- **恢复定位**：调用清除模拟服务，让手机重新使用正常定位来源。
- **坐标转换**：支持 WGS-84，支持将高德 / 腾讯地图常用的 GCJ-02 坐标近似转换为 WGS-84。
- **设备检查**：显示 USB 连接、iOS 版本、开发者模式和开发支持镜像状态。
- **开发环境准备**：请求显示开发者模式入口，并按需下载、挂载开发支持镜像。
- **恢复提醒**：模拟前保存本地恢复记录，连接异常后提示重新连接并清除模拟。
- **单实例控制**：防止同一项目中的多个程序同时设置或清除定位。
- **GPX 工具**：单独提供单点、路线文件生成和基础校验，不与真机定位控制混淆。

## 环境要求

| 项目 | 要求 |
| --- | --- |
| 电脑 | macOS；当前控制程序使用 macOS / Unix 文件锁 |
| Python | Python 3.11 或更新版本，图形界面需要 Tk；已验证 Python 3.13 |
| 手机 | iPhone，当前开发服务连接实现面向 iOS 17+ |
| 连接 | 支持数据传输的 USB 线，手机已解锁并信任此电脑 |
| 开发配置 | iPhone 已开启开发者模式，具有兼容的开发支持镜像 |
| 网络 | 首次安装 Python 依赖、下载及个性化开发镜像时需要联网 |

无需越狱。完整 Xcode 并非所有情况下都必需；若开发者模式入口不显示，可通过 Xcode 的设备配对流程排查。不同 iOS 版本的支持情况取决于底层开发服务及镜像兼容性。

## 安装

### 1. 克隆项目

```bash
git clone https://github.com/Volrange/iphone-gps-mock.git
cd iphone-gps-mock
```

### 2. 准备 Python 和 Tk

如果已有 Python 3.11+，可以先检查 Tk：

```bash
python3 -c "import tkinter; print(tkinter.TkVersion)"
```

使用 Homebrew 的示例：

```bash
brew install python@3.13 python-tk@3.13
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

如果默认 `python3` 已满足要求，也可以直接运行安装脚本：

```bash
./setup.command
```

`requirements.txt` 固定设备通信库版本。`requirements-lock.txt` 保存已验证环境的完整依赖版本，供复现和排查使用；其他 Python 版本或平台未必适合使用同一份锁定列表。

### 3. 启动

```bash
./run_gps_mock.command
```

也可以在 Finder 中双击 `run_gps_mock.command`，或直接运行：

```bash
.venv/bin/python gps_mock_app.py
```

## 首次连接 iPhone

1. 通过 USB 连接手机，解锁并确认“信任此电脑”。
2. 点击程序中的 **检查设备**。
3. 在手机 **设置 → 隐私与安全性 → 开发者模式** 中开启开关，按系统提示重启，并在重启后确认开启。
4. 如果找不到入口，可点击 **显示开发者模式入口**，然后重新打开手机设置；仍无入口时，使用完整 Xcode 进行设备配对。
5. 点击 **准备开发服务**，等待开发支持镜像下载和挂载完成。首次准备可能较慢，请保持 USB 连接。

开发者模式的开启需要手机端确认。不要为了启用开发者模式关闭锁屏密码。

## 使用图形界面

### 设置目标位置

1. 填写 **纬度** 和 **经度**，注意顺序。
2. 选择输入坐标系：
   - **WGS-84**：GPS 原始坐标。
   - **GCJ-02**：高德 / 腾讯地图常用坐标，程序会转换后发送。
3. 核对界面显示的 WGS-84 坐标，点击 **使用目标定位**。
4. 在手机地图或待测 App 中重新请求定位，核验实际结果。

程序附带上海交通大学闵行校区思源门的候选点，方便首次测试。该预设仅作示例，不代表经过测绘确认的门口精确坐标。

### 恢复真实定位

点击 **恢复手机真实定位**，再到手机地图重新定位。

恢复操作是清除模拟，不是写回某一组旧坐标。正常关闭窗口时，程序也会尝试清除本程序记录的模拟状态。异常断线、强制退出或通信失败时，不能假定已恢复；重新连接后再次执行恢复操作。

保持 USB 连接和控制程序运行，避免测试期间失去定位服务连接。仅拔线不等同于已确认清除模拟。

## 命令行

图形界面与命令行共享单实例锁。使用命令行控制前，请先正常关闭图形界面。

```bash
# 检查设备和开发配置
.venv/bin/python iphone_control.py status

# 请求显示手机上的开发者模式入口
.venv/bin/python iphone_control.py reveal

# 准备开发支持镜像
.venv/bin/python iphone_control.py prepare

# 使用 WGS-84 经纬度设置模拟位置
.venv/bin/python iphone_control.py set --lat 31.2304 --lon 121.4737

# 输入 GCJ-02 坐标
.venv/bin/python iphone_control.py set --lat 31.017785 --lon 121.430895 --system GCJ-02

# 清除模拟位置
.venv/bin/python iphone_control.py clear
```

`set` 会保持连接；按 `Ctrl+C` 后程序尝试清除模拟并退出。失败时仍需重新连接并执行 `clear`，最终以手机地图显示为准。

## GPX 文件工具

`gps_mock.py` 只负责生成和基础校验 GPX 文件，不会向实体 iPhone 写入坐标。当前界面不提供真机路线回放。

```bash
python3 gps_mock.py point --lat 31.2304 --lon 121.4737 -o location.gpx
python3 gps_mock.py route --point 31.2304,121.4737 --point 31.2310,121.4750 -o route.gpx
python3 gps_mock.py route --input points.json -o route.gpx
python3 gps_mock.py validate location.gpx
```

JSON 输入示例：

```json
[
  {"lat": 31.2304, "lon": 121.4737, "name": "Start"},
  {"lat": 31.2310, "lon": 121.4750, "elevation": 8}
]
```

CSV 输入需要 `lat,lon` 列，可选 `elevation,name` 列。GPX 工具不会自动转换坐标系，请传入所需坐标。

## 已验证范围与限制

| 项目 | 状态 |
| --- | --- |
| Apple Silicon Mac / Python 3.13 | 图形界面启动及设备通信已验证 |
| iPhone 17 / iOS 26.6.1 | USB 识别、配对、开发模式检查、镜像挂载及 DVT 通信已验证 |
| 第三方 App 定位 | 已在真机地图功能中人工确认模拟位置生效 |
| 清除模拟 | 已实现；恢复记录和失败处理通过自动测试，恢复后真实坐标仍待真机核验 |
| 其他 iPhone / iOS 版本 | 未逐一验证，不保证兼容 |

- App 可能识别模拟定位，或使用缓存及其他定位来源；设置请求完成不代表所有 App 都会接受。
- 程序不读取 iPhone 的实际 GPS 坐标，界面显示的是目标坐标及操作状态。
- 清除模拟命令没有独立成功响应；程序随后检查通信连接，但不能据此证明某个 App 已恢复真实坐标。
- GCJ-02 转换使用近似模型，不用于测绘。百度 BD-09 坐标不可直接输入。
- 单实例锁只覆盖同一项目目录，不协调其他定位工具或另一份项目副本。

## 本地数据

| 路径 | 用途 |
| --- | --- |
| `.venv/` | 项目 Python 虚拟环境 |
| `.state/controller.lock` | 本地单实例锁 |
| `.state/pending_restore.json` | 记录需要清除模拟的设备标识和目标坐标 |

这些路径已加入 `.gitignore`。恢复记录不应提交到仓库；删除记录也不会清除手机上的模拟定位。开发镜像和配对缓存由 `pymobiledevice3` 在其用户数据目录中管理。

## 常见问题

| 问题 | 处理方式 |
| --- | --- |
| 找不到手机 | 解锁手机、确认 USB 数据连接和“信任此电脑”，再检查设备 |
| 找不到开发者模式 | 请求显示入口并重新打开设置；必要时通过 Xcode 完成配对 |
| `Device has a passcode set` | Mac 自动启用路径受限；保留锁屏密码，通过手机端手动开启 |
| 镜像下载或挂载失败 | 查看界面日志，检查网络、手机解锁状态及镜像兼容性；不要并行重复准备 |
| 提示 GPS Mock 已在运行 | 使用已有窗口，或正常关闭另一个控制实例 |
| `No module named tkinter` | 安装与当前 Python 版本对应的 Tk 支持，并确认虚拟环境使用正确解释器 |
| 地图位置没有改变 | 在 App 中重新请求定位，检查坐标系、缓存和模拟定位识别机制 |
| 恢复后仍显示旧位置 | 保持连接，再次清除模拟并重新请求定位；以手机端核验为准 |

## 项目结构

```text
iphone-gps-mock/
├── gps_mock_app.py          # Tk 图形界面
├── iphone_control.py        # USB 设备控制、恢复记录与命令行
├── coordinates.py           # 坐标校验与转换
├── gps_mock.py              # GPX 文件工具
├── test_iphone_control.py   # 坐标与恢复行为测试
├── requirements.txt        # 核心依赖
├── requirements-lock.txt   # 已验证环境的依赖快照
├── setup.command           # 安装脚本
├── run_gps_mock.command     # 启动脚本
└── Makefile                # 本地检查入口
```

## 开发与验证

```bash
make check
```

检查包括 6 项单元测试、Python 语法检查和 GPX 生成 / 基础校验。单元测试使用模拟设备对象，不会改变已连接手机的定位，也不能替代真机测试。

欢迎提交 Issue 或 Pull Request。报告连接问题时，请附上 macOS、Python、iOS 和 `pymobiledevice3` 版本及经过脱敏的错误信息，不要上传配对记录或 `.state` 文件。

## 致谢

- [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)：iOS 设备通信与开发服务，采用 GPL-3.0-or-later 许可证。
- [Apple：Enabling Developer Mode on a device](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)：开发者模式官方说明。

本仓库尚未指定自身代码的开源许可证；第三方依赖遵循其各自许可证。
