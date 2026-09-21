"""USB iPhone location control, with explicit restoration and recovery state.

All methods run on one asyncio loop. Callers serialize operations; the Tk app
keeps this loop on a worker thread so USB/tunnel setup cannot freeze the window.
"""
from __future__ import annotations

import asyncio
import argparse
import fcntl
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
import sys

from coordinates import to_wgs84

STATE_PATH = Path(__file__).resolve().parent / ".state" / "pending_restore.json"


class ControlError(RuntimeError):
    pass


def explain_error(exc):
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "设备响应超时。请解锁 iPhone、检查 USB 连接后重试；若已模拟，请优先恢复真实定位。"
    name = type(exc).__name__
    if isinstance(exc, PermissionError):
        return "系统拒绝访问设备服务。请从 Finder 双击启动程序，或允许终端访问设备。"
    if "DeveloperMode" in name:
        return "请在手机 设置 → 隐私与安全性 → 开发者模式 中开启，并完成重启及确认。"
    if "Pair" in name or "Password" in name or "Locked" in name:
        return "请解锁 iPhone，并确认“信任此电脑”；然后重新检查设备。"
    if "NoDevice" in name or "NotConnected" in name or "Connection" in name:
        return "设备连接中断或不可用。请解锁手机、重新插入 USB，再检查设备。"
    return f"{name}: {exc}" if str(exc) else name


class PhoneController:
    def __init__(self, log=lambda message: None, state_path=STATE_PATH):
        self.log = log
        self.state_path = Path(state_path)
        self.udid = None
        self.location = None
        self.device_info = None
        self.stack = None
        self.pending = self._load_pending()

    def _load_pending(self):
        if not self.state_path.exists():
            return None
        try:
            data = json.loads(self.state_path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get("udid"), str):
                raise ValueError("missing device id")
            return data
        except (OSError, ValueError) as exc:
            raise ControlError("恢复记录损坏，请保留 .state 文件并排查；不能确认上次是否已恢复。") from exc

    def _mark_pending(self, lat, lon):
        data = {"udid": self.udid, "latitude": lat, "longitude": lon}
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.state_path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.state_path)
        self.pending = data

    async def _phone(self):
        from pymobiledevice3 import usbmux
        from pymobiledevice3.lockdown import create_using_usbmux
        devices = [d for d in await asyncio.wait_for(usbmux.list_devices(), 10) if d.is_usb]
        expected = self.pending["udid"] if self.pending else self.udid
        if expected:
            devices = [d for d in devices if d.serial == expected]
        if not devices:
            raise ControlError("未找到目标 iPhone。请保持 USB 连接、解锁手机并信任此电脑。")
        if len(devices) != 1:
            raise ControlError("检测到多台 USB 设备。请仅连接要调试的 iPhone，避免改错设备。")
        lockdown = await asyncio.wait_for(create_using_usbmux(
            serial=devices[0].serial, connection_type="USB", pair_timeout=15), 25)
        self.udid = devices[0].serial
        return lockdown

    async def status(self):
        from pymobiledevice3.services.mobile_image_mounter import MobileImageMounterService
        async with await self._phone() as phone:
            enabled = await asyncio.wait_for(phone.get_developer_mode_status(), 15)
            async with MobileImageMounterService(phone) as mounter:
                mounted = await asyncio.wait_for(mounter.is_image_mounted("Personalized"), 15)
            info = {"name": phone.all_values.get("DeviceName", "iPhone"),
                    "version": phone.product_version, "developer_mode": enabled,
                    "mounted": mounted, "pending_restore": bool(self.pending)}
            self.log(f"USB 已连接：{info['name']} · iOS {info['version']} · 开发者模式{'已开' if enabled else '未开'}")
            return info

    async def reveal(self):
        from pymobiledevice3.services.amfi import AmfiService
        async with await self._phone() as phone:
            await asyncio.wait_for(AmfiService(phone).reveal_developer_mode_option_in_ui(), 15)
        self.log("手机已接受显示入口请求。请重新打开 设置 → 隐私与安全性，滑到最底部查看。")

    async def prepare(self):
        info = await self.status()
        if not info["developer_mode"]:
            raise ControlError("开发者模式尚未开启。先显示入口，再在手机上开启、重启并确认。")
        if not info["mounted"]:
            self.log("正在准备开发支持镜像，首次可能需要下载；请保持手机解锁与网络连接。")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pymobiledevice3", "--no-color", "mounter", "auto-mount",
                "--udid", self.udid, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            try:
                output, _ = await asyncio.wait_for(proc.communicate(), 900)
            except BaseException:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
                raise
            if proc.returncode:
                raise ControlError("镜像准备失败：" + output.decode(errors="replace")[-2000:])
            info = await self.status()
            if not info["mounted"]:
                raise ControlError("命令已退出，但设备未确认挂载开发镜像。请检查兼容性后重试。")
        self.log("开发支持镜像已就绪。")
        return info

    async def _connect_location(self):
        if self.location is not None:
            return
        from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
        from pymobiledevice3.services.dvt.instruments.device_info import DeviceInfo
        self.log("正在建立定位调试通道…")
        stack = AsyncExitStack()
        try:
            async with asyncio.timeout(60):
                rsd = await stack.enter_async_context(PreferredRsdTunnel(serial=self.udid))
                dvt = await stack.enter_async_context(DvtProvider(rsd))
                location = await stack.enter_async_context(LocationSimulation(dvt))
                device_info = await stack.enter_async_context(DeviceInfo(dvt))
                await device_info.mach_kernel_name()
        except BaseException:
            await stack.aclose()
            raise
        self.stack, self.location = stack, location
        self.device_info = device_info
        self.log("定位服务已连接。")

    async def _disconnect(self):
        stack, self.stack = self.stack, None
        self.location = None
        self.device_info = None
        if stack is not None:
            try:
                await asyncio.wait_for(stack.aclose(), 10)
            except Exception as exc:
                self.log("连接关闭提示：" + explain_error(exc))

    async def set_location(self, latitude, longitude, system="WGS-84"):
        # Validate before connecting or changing any device state.
        lat, lon = to_wgs84(latitude, longitude, system)
        await self.prepare()
        await self._connect_location()
        self._mark_pending(lat, lon)  # Persist before write; errors/timeouts may still have applied.
        try:
            await asyncio.wait_for(self.location.set(lat, lon), 20)
        except BaseException:
            await self._disconnect()
            raise
        self.log(f"模拟请求完成：WGS-84 {lat:.7f}, {lon:.7f}。请在交我办电子地图点击定位核验。")
        return {"latitude": lat, "longitude": lon}

    async def restore(self):
        # Reconnect if necessary; never equate terminating a process with clearing simulation.
        await self.prepare()
        await self._connect_location()
        try:
            await asyncio.wait_for(self.location.clear(), 20)
            # The clear selector has no reply. Check that the connection is responsive;
            # this verifies transport, not real coordinates or another app's cache.
            await asyncio.wait_for(self.device_info.mach_kernel_name(), 15)
        except BaseException:
            await self._disconnect()
            raise
        self.state_path.unlink(missing_ok=True)
        self.pending = None
        await self._disconnect()
        self.log("已发送清除模拟指令。请在电子地图重新定位，核对真实位置；程序无法读取手机的实际定位。")

    async def shutdown(self):
        if self.pending:
            await self.restore()
        await self._disconnect()

    async def heartbeat(self):
        if self.device_info is not None:
            try:
                await asyncio.wait_for(self.device_info.mach_kernel_name(), 10)
            except BaseException:
                await self._disconnect()
                raise


def acquire_instance_lock():
    """Prevent two local controllers from changing the same phone concurrently."""
    directory = STATE_PATH.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = (directory / "controller.lock").open("a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise ControlError("GPS Mock 已在运行。请使用已打开的窗口，或先关闭另一个控制进程。") from exc
    return handle


async def _cli(args):
    import signal
    controller = PhoneController(log=lambda message: print(message, flush=True))
    if args.command == "status":
        print(json.dumps(await controller.status(), ensure_ascii=False, indent=2))
    elif args.command == "reveal":
        await controller.reveal()
    elif args.command == "prepare":
        await controller.prepare()
    elif args.command == "clear":
        await controller.restore()
    else:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        try:
            await controller.set_location(args.lat, args.lon, args.system)
            print("连接保持中；按 Ctrl+C 清除模拟后退出。", flush=True)
            await stop.wait()
        finally:
            await controller.shutdown()


def main():
    parser = argparse.ArgumentParser(description="iPhone USB 定位控制（iOS 17+）")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "reveal", "prepare", "clear"):
        sub.add_parser(name)
    point = sub.add_parser("set")
    point.add_argument("--lat", required=True)
    point.add_argument("--lon", required=True)
    point.add_argument("--system", choices=("WGS-84", "GCJ-02"), default="WGS-84")
    args = parser.parse_args()
    try:
        with acquire_instance_lock():
            asyncio.run(_cli(args))
    except (Exception, KeyboardInterrupt) as exc:
        print(explain_error(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
