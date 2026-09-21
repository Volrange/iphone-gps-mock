#!/usr/bin/env python3
"""Responsive macOS UI for USB iPhone location simulation."""
import asyncio
from datetime import datetime
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from coordinates import SIYUAN_GCJ02, to_wgs84
from iphone_control import (PhoneController, RECOVERY_GUIDE, VERIFICATION_STATES,
                            acquire_instance_lock, explain_error)


class GPSMockApp(tk.Tk):
    def __init__(self, auto_check=True):
        super().__init__()
        self.title("GPS Mock · iPhone 定位调试")
        self.geometry("780x760")
        self.minsize(720, 720)
        self.events = queue.Queue()
        self.loop = asyncio.new_event_loop()
        self.worker = threading.Thread(target=self._run_loop, daemon=True)
        self.worker.start()
        self.controller = PhoneController(log=lambda text: self.events.put(("log", text)))
        self.busy = False
        self.closing = False
        self.buttons = []
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._drain)
        self.after(20000, self._monitor)
        if self.controller.pending:
            if self.controller.pending.get("status") in VERIFICATION_STATES:
                self.position.set("上次恢复尚待手机核验 · 确认真实位置后点击“确认手机已恢复”")
            else:
                self.position.set("上次模拟尚未确认清除，请先恢复真实定位")
        if auto_check:
            self.after(200, lambda: self._submit("检查设备", self.controller.status))

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        self.loop.close()

    def _button(self, parent, text, action):
        button = ttk.Button(parent, text=text, command=action)
        button.pack(side="left", padx=(0, 8), pady=4)
        self.buttons.append(button)
        return button

    def _build_ui(self):
        root = ttk.Frame(self, padding=22)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="iPhone 定位调试", font=("Helvetica", 23, "bold")).pack(anchor="w")
        ttk.Label(root, text="USB 连接 · 指定坐标 · 恢复真实定位", foreground="#555").pack(anchor="w", pady=(4, 14))
        self.device = tk.StringVar(value="设备：尚未检查")
        self.position = tk.StringVar(value="定位：尚未设置，实际位置请在手机地图查看")
        self.task = tk.StringVar(value="就绪")
        ttk.Label(root, textvariable=self.device, wraplength=720).pack(anchor="w")
        ttk.Label(root, textvariable=self.position, wraplength=720, foreground="#215a80").pack(anchor="w", pady=(6, 8))
        row = ttk.Frame(root)
        row.pack(fill="x")
        self._button(row, "检查设备", lambda: self._submit("检查设备", self.controller.status))
        self._button(row, "显示开发者模式入口", lambda: self._submit("显示入口", self.controller.reveal))
        self._button(row, "准备开发服务", lambda: self._submit("准备开发服务", self.controller.prepare))
        ttk.Label(root, text="手机操作：设置 → 隐私与安全性 → 开发者模式；开启后重启并确认。", wraplength=720, foreground="#555").pack(anchor="w", pady=(4, 12))
        target = ttk.LabelFrame(root, text="目标位置", padding=14)
        target.pack(fill="x")
        self.lat = tk.StringVar(value=str(SIYUAN_GCJ02[0]))
        self.lon = tk.StringVar(value=str(SIYUAN_GCJ02[1]))
        self.system = tk.StringVar(value="GCJ-02")
        self.preview = tk.StringVar()
        coordinates = ttk.Frame(target)
        coordinates.pack(fill="x")
        for label, variable in (("纬度（南北）", self.lat), ("经度（东西）", self.lon)):
            column = ttk.Frame(coordinates)
            column.pack(side="left", fill="x", expand=True, padx=(0, 12))
            ttk.Label(column, text=label).pack(anchor="w")
            ttk.Entry(column, textvariable=variable, width=22).pack(fill="x", pady=(4, 6))
        options = ttk.Frame(target)
        options.pack(fill="x", pady=(4, 6))
        ttk.Label(options, text="输入坐标系").pack(side="left", padx=(0, 8))
        ttk.Combobox(options, textvariable=self.system, values=("GCJ-02", "WGS-84"), state="readonly", width=12).pack(side="left")
        self._button(options, "思源门候选点（待核验）", self._preset)
        ttk.Label(target, text="GCJ-02：高德 / 腾讯地图；WGS-84：GPS 原始坐标。百度坐标请先转换。", foreground="#555", wraplength=660).pack(anchor="w")
        ttk.Label(target, textvariable=self.preview, wraplength=660).pack(anchor="w", pady=(8, 0))
        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=12)
        self._button(actions, "使用目标定位", self._set)
        self._button(actions, "恢复手机真实定位", lambda: self._submit("恢复定位", self.controller.restore))
        self._button(actions, "确认手机已恢复", self._confirm_restore)
        recovery = ttk.Frame(root)
        recovery.pack(fill="x")
        self._button(recovery, "恢复后位置仍不正确？", self._show_recovery_help)
        ttk.Label(recovery, text="查看系统地图与 Wi-Fi / 蓝牙排查步骤", foreground="#555").pack(side="left")
        ttk.Label(root, text="模拟作用于设备定位服务，可能影响其他 App。请在交我办“电子地图”点击定位核验。", foreground="#875400", wraplength=720).pack(anchor="w")
        status = ttk.Frame(root)
        status.pack(fill="x", pady=(12, 6))
        ttk.Label(status, textvariable=self.task).pack(side="left")
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=130)
        self.progress.pack(side="right")
        self.log = tk.Text(root, height=10, wrap="word", state="disabled", font=("Menlo", 11))
        self.log.pack(fill="both", expand=True)
        for variable in (self.lat, self.lon, self.system):
            variable.trace_add("write", lambda *_: self._preview())
        self._preview()

    def _preview(self):
        try:
            lat, lon = to_wgs84(self.lat.get(), self.lon.get(), self.system.get())
            self.preview.set(f"将发送的 WGS-84：{lat:.7f}, {lon:.7f}（近似转换，用于调试）")
        except ValueError:
            self.preview.set("请输入有效经纬度")

    def _preset(self):
        self.lat.set(str(SIYUAN_GCJ02[0]))
        self.lon.set(str(SIYUAN_GCJ02[1]))
        self.system.set("GCJ-02")

    def _set(self):
        lat, lon, system = self.lat.get(), self.lon.get(), self.system.get()
        try:
            to_wgs84(lat, lon, system)
        except ValueError as exc:
            messagebox.showerror("坐标无效", str(exc), parent=self)
            return
        self._submit("设置定位", lambda: self.controller.set_location(lat, lon, system))

    def _submit(self, label, operation):
        if self.busy:
            return
        self.busy = True
        self.task.set(label + "…")
        if label == "恢复定位":
            self.position.set("恢复中：等待设备应答停止模拟请求，请保持 USB 连接")
        for button in self.buttons:
            button.state(["disabled"])
        self.progress.start(12)
        future = asyncio.run_coroutine_threadsafe(operation(), self.loop)
        def finished(task):
            try:
                self.events.put(("done", label, task.result(), None))
            except BaseException as exc:
                self.events.put(("done", label, None, explain_error(exc)))
        future.add_done_callback(finished)

    def _confirm_restore(self):
        if not self.controller.pending or self.controller.pending.get("status") not in VERIFICATION_STATES:
            messagebox.showinfo("尚未完成清除", "请先点击“恢复手机真实定位”，再到手机地图核验。", parent=self)
            return
        if messagebox.askyesno("核验手机真实位置", "你是否已在手机地图重新点击定位，并确认回到了实际所在位置？\n\n"
                              "这里只记录核验结果，不会向手机发送定位指令。", parent=self):
            self._submit("确认恢复", self.controller.confirm_restored)

    def _show_recovery_help(self):
        messagebox.showinfo("恢复定位排查步骤", RECOVERY_GUIDE, parent=self)

    def _append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {text}\n")
        if int(self.log.index("end-1c").split(".")[0]) > 300:
            self.log.delete("1.0", "100.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "log":
                    self._append(event[1])
                    continue
                _, label, result, error = event
                self.busy = False
                self.progress.stop()
                for button in self.buttons:
                    button.state(["!disabled"])
                if error:
                    self.task.set(label + "失败")
                    self._append(error)
                    if self.controller.pending:
                        self.position.set("定位状态待核验：可能仍在模拟，请重新连接后恢复")
                    if label in ("检查设备", "检查连接"):
                        self.device.set("设备不可用：请检查 USB 连接和手机解锁状态")
                    if label == "退出":
                        self.closing = False
                        if messagebox.askyesno("恢复未完成", error + "\n\n手机可能仍在模拟。仍要退出吗？下次启动会保留恢复提醒。", parent=self):
                            self._quit()
                            return
                else:
                    self.task.set("就绪")
                    if label in ("检查设备", "准备开发服务"):
                        self.device.set(f"{result['name']} · iOS {result['version']} · 开发者模式{'已开' if result['developer_mode'] else '未开'} · 镜像{'已就绪' if result['mounted'] else '待准备'}")
                    elif label == "设置定位":
                        self.position.set(f"模拟请求完成：{result['latitude']:.7f}, {result['longitude']:.7f} · 等待手机地图核验")
                    elif label == "恢复定位":
                        self.position.set("停止请求已应答 · 真实定位待手机核验，恢复记录仍保留")
                    elif label == "确认恢复":
                        self.position.set("已由你在手机端确认恢复真实定位")
                    elif label == "退出":
                        self._quit()
                        return
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _monitor(self):
        if not self.busy and self.controller.location is not None:
            self._submit("检查连接", self.controller.heartbeat)
        self.after(20000, self._monitor)

    def _close(self):
        if self.busy:
            messagebox.showinfo("正在处理", "请等待当前设备操作结束后再关闭。", parent=self)
            return
        if self.closing:
            return
        self.closing = True
        self._submit("退出", self.controller.shutdown)

    def _quit(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.worker.join(timeout=2)
        self.destroy()


def main():
    try:
        with acquire_instance_lock():
            app = GPSMockApp(auto_check="--ui-check" not in sys.argv)
            if "--ui-check" in sys.argv:
                app.after(1500, app._close)
            app.mainloop()
    except Exception as exc:
        print(explain_error(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
